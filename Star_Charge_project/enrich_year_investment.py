#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enrich "Year operational" & "Investment (CNY)" using public web sources.
- Only fills cells that are blank/empty.
- Station name cleaned by your rules before searching:
  1) Remove content inside 【】.
  2) Remove leading classification prefixes like "星星充电-" / "城建星充-".
  3) Remove blacklisted parentheses like "（不对外）" but keep meaningful ones (e.g., "（胶东机场）").
  4) Combine Station name + Province + City/County for disambiguation; also search by Partners + station.

Sources preference (same as before):
- mp.weixin.qq.com
- *.gov.cn
- starcharge/xevse (add more if needed)

Writes evidence to Notes: [auto-evidence]{...} + source(year/inv): URL

Usage:
  pip install pandas openpyxl selenium serpapi deep-translator
  python enrich_year_investment.py --excel ./input.xlsx --sheet "sample" --out ./output.xlsx --backend serpapi
"""

import argparse
import json
import os
import re
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd

# Optional deps
try:
    from serpapi import GoogleSearch
except Exception:
    GoogleSearch = None

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except Exception:
    webdriver = None


# ---------------- Station name cleaning per your rules ----------------

CLASS_PREFIXES = [
    "星星充电",
    "城建星充",
    "星星寅元特",
    "星星驰云涧",
    # 如需扩展，在此追加
]

PAREN_BLACKLIST = [
    "不对外",
    "内部专用",
    "仅限内部",
    "仅内部",
    "内部",
    "仅限",
    # 可按需扩展
]


def remove_brackets_fullwidth(s: str) -> str:
    """Remove content inside 【...】 including the brackets."""
    return re.sub(r"【[^】]*】", "", s)


def remove_leading_class_prefix(s: str) -> str:
    """
    Remove leading '星星充电-' / '城建星充-' like prefixes.
    Strategy: if the string starts with any of CLASS_PREFIXES + '-', drop the prefix + dash.
    """
    for pref in CLASS_PREFIXES:
        if s.startswith(pref + "-"):
            return s[len(pref) + 1 :]
    return s


def remove_blacklisted_parentheses(s: str) -> str:
    """
    Remove parentheses content only if it contains blacklisted tokens.
    Keep others (e.g., （胶东机场） must be kept).
    """

    def repl(m):
        inner = m.group(1)
        if any(tok in inner for tok in PAREN_BLACKLIST):
            return ""  # drop this pair of parentheses entirely
        return m.group(0)  # keep as-is

    return re.sub(r"（(.*?)）", repl, s)


def clean_station_for_query(raw_name: str) -> str:
    if not raw_name:
        return ""
    s = str(raw_name)
    s = remove_brackets_fullwidth(s)
    s = remove_leading_class_prefix(s)
    s = remove_blacklisted_parentheses(s)
    s = re.sub(r"\s+", " ", s).strip("-—· ").strip()
    return s


# ---------------- Search & extraction ----------------


class SearchResult:
    def __init__(self, url: str, title: str, snippet: str, score: float = 0.0):
        self.url = url
        self.title = title
        self.snippet = snippet
        self.score = score


def build_queries(station: Dict) -> List[str]:
    """
    Build prioritized queries using cleaned station name + city/province + partner
    """
    raw_name = station.get("Station name", "") or ""
    name = clean_station_for_query(raw_name)

    province = station.get("Province", "") or ""
    city = station.get("City/County", "") or ""
    partner = station.get("Partners", "") or ""

    base_loc = f"{name} {city} {province}".strip()
    base_loc = re.sub(r"\s+", " ", base_loc)
    base_partner = f"{partner} {name} {city} {province}".strip()

    queries = [
        f"{base_loc} 投运 投入运营 充电站",
        f"{base_loc} 总投资 投资额 亿元 万元 充电站",
        f"{base_loc} 启用 建成 投产 开放 充电站",
        f"site:mp.weixin.qq.com {base_loc} 投运",
        f"site:mp.weixin.qq.com {base_loc} 充电站",
        f"site:gov.cn {base_loc} 充电站 投资",
        f"site:starcharge.com {base_loc} 充电站",
    ]

    if partner:
        queries += [
            f"{base_partner} 投运 投入运营 充电站",
            f"{base_partner} 总投资 投资额 亿元 万元 充电站",
            f"site:mp.weixin.qq.com {base_partner} 投运",
            f"site:gov.cn {base_partner} 充电站 投资",
        ]

    # de-dup
    seen, uniq = set(), []
    for q in queries:
        qq = q.strip()
        if qq and qq not in seen:
            seen.add(qq)
            uniq.append(qq)
    return uniq


def serp_search(query: str, num: int = 8) -> List[SearchResult]:
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not api_key or GoogleSearch is None:
        return []
    params = {"engine": "google", "q": query, "num": num, "hl": "zh-CN", "gl": "cn"}
    search = GoogleSearch(params | {"api_key": api_key})
    results = search.get_dict()
    out = []
    for item in results.get("organic_results", []):
        out.append(
            SearchResult(
                url=item.get("link", ""),
                title=item.get("title", ""),
                snippet=item.get("snippet", ""),
                score=0.0,
            )
        )
    return out


def selenium_search(
    query: str, num: int = 8, engine: str = "bing"
) -> List[SearchResult]:
    if webdriver is None:
        return []
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1280,1024")
    driver = webdriver.Chrome(options=opts)
    out: List[SearchResult] = []
    try:
        if engine == "bing":
            driver.get("https://www.bing.com/")
            box = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.NAME, "q"))
            )
            box.clear()
            box.send_keys(query)
            box.submit()
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "b_content"))
            )
            results = driver.find_elements(By.CSS_SELECTOR, "li.b_algo")
            for r in results[:num]:
                try:
                    a = r.find_element(By.CSS_SELECTOR, "h2 a")
                    url = a.get_attribute("href")
                    title = a.text
                    snip_el = r.find_element(By.CSS_SELECTOR, ".b_caption p")
                    snippet = snip_el.text if snip_el else ""
                    out.append(SearchResult(url=url, title=title, snippet=snippet))
                except Exception:
                    continue
        else:
            driver.get("https://www.google.com/")
            box = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.NAME, "q"))
            )
            box.clear()
            box.send_keys(query)
            box.submit()
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "search"))
            )
            results = driver.find_elements(By.CSS_SELECTOR, "div.g")
            for r in results[:num]:
                try:
                    a = r.find_element(By.CSS_SELECTOR, "a")
                    url = a.get_attribute("href")
                    title_el = r.find_element(By.TAG_NAME, "h3")
                    title = title_el.text if title_el else ""
                    snippet = r.text
                    out.append(SearchResult(url=url, title=title, snippet=snippet))
                except Exception:
                    continue
    finally:
        driver.quit()
    return out


def score_result(sr: SearchResult, station: Dict) -> float:
    """Heuristic scoring: station/company/location matches + domain preference."""
    score = 0.0
    title = (sr.title or "").lower()
    snippet = (sr.snippet or "").lower()
    url = (sr.url or "").lower()

    name = (clean_station_for_query(station.get("Station name", "") or "")).lower()
    if name and name in title:
        score += 3.0
    if name and name in snippet:
        score += 2.0

    for k in ("City/County", "Province", "Partners"):
        v = (station.get(k, "") or "").lower()
        if v and v in title:
            score += 1.5
        if v and v in snippet:
            score += 1.0

    # domain preference
    if "mp.weixin.qq.com" in url:
        score += 3.5
    if url.endswith(".gov.cn") or ".gov.cn/" in url:
        score += 3.0
    if any(d in url for d in ["news.cn", "people.com.cn", "xinhuanet.com", "ce.cn"]):
        score += 2.0
    if any(d in url for d in ["starcharge", "xevse"]):
        score += 1.5

    return score


def fetch_page_text(url: str) -> str:
    if webdriver is None:
        return ""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1280,2000")
    driver = webdriver.Chrome(options=opts)
    try:
        driver.get(url)
        time.sleep(2.0)
        body_text = driver.find_element(By.TAG_NAME, "body").text
        return body_text
    except Exception:
        return ""
    finally:
        driver.quit()


def extract_year_operational(text: str) -> Optional[int]:
    if not text:
        return None
    # 20xx年 + 投运/投入运营/正式运营/启用/建成/投产/开放
    m = re.search(
        r"(20[0-3]\d)\s*年.{0,15}?(投运|投入运营|正式运营|启用|建成|投产|开放)", text
    )
    if m:
        y = int(m.group(1))
        if 2000 <= y <= 2035:
            return y
    m2 = re.search(
        r"(投运|投入运营|正式运营|启用|建成|投产|开放).{0,30}?(20[0-3]\d)年?", text
    )
    if m2:
        y = int(m2.group(2))
        if 2000 <= y <= 2035:
            return y
    m3 = re.search(r"(20[0-3]\d)年", text)
    if m3:
        y = int(m3.group(1))
        if 2000 <= y <= 2035:
            return y
    return None


def chinese_num_to_int(text: str) -> Optional[int]:
    if not text:
        return None
    s = str(text).strip()
    m = re.search(
        r"(?P<num>\d+(\.\d+)?)\s*(?P<unit>亿元|万亿元|亿|万元|万|元|人民币|RMB|CNY)", s
    )
    if m:
        num = float(m.group("num"))
        unit = m.group("unit")
        if unit == "万亿元":
            return int(round(num * 1e12 / 1e4))
        if unit in ("亿元", "亿"):
            return int(round(num * 100000000))
        if unit in ("万元", "万"):
            return int(round(num * 10000))
        return int(round(num))

    # 粗略兜底
    m2 = re.search(r"投资(总额)?(约|达|超)?\D*(\d{5,12})", s)
    if m2:
        return int(m2.group(3))
    return None


def extract_investment(text: str) -> Optional[int]:
    if not text:
        return None
    for line in text.splitlines():
        if "投资" in line:
            val = chinese_num_to_int(line)
            if val:
                return val
    return None


def extract_from_text(text: str) -> Tuple[Optional[int], Optional[int], Dict[str, str]]:
    notes = {}
    yo = extract_year_operational(text)
    if yo:
        notes["year_operational"] = str(yo)
    inv = extract_investment(text)
    if inv:
        notes["investment_line"] = "found"
    return yo, inv, notes


def enrich_row(
    station: Dict, backend: str = "serpapi", engine: str = "bing", max_results: int = 10
) -> Tuple[Optional[int], Optional[int], str]:
    queries = build_queries(station)
    results: List[SearchResult] = []
    for q in queries:
        try:
            rs = (
                serp_search(q, num=8)
                if backend == "serpapi"
                else selenium_search(q, num=8, engine=engine)
            )
        except Exception:
            rs = []
        for r in rs:
            r.score = score_result(r, station)
        results.extend(rs)
        time.sleep(0.4)  # avoid being too aggressive

    # unique urls, keep best score
    uniq: Dict[str, SearchResult] = {}
    for r in results:
        if not r.url:
            continue
        if r.url not in uniq or r.score > uniq[r.url].score:
            uniq[r.url] = r
    ranked = sorted(uniq.values(), key=lambda x: x.score, reverse=True)[:max_results]

    best_yo = None
    best_inv = None
    evidence = {}

    for r in ranked:
        text = fetch_page_text(r.url)
        if not text:
            continue
        yo, inv, notes = extract_from_text(text)
        if best_yo is None and yo is not None:
            best_yo = yo
            evidence["yo_url"] = r.url
            evidence.update(notes)
        if best_inv is None and inv is not None:
            best_inv = inv
            evidence["inv_url"] = r.url
            evidence.update(notes)
        if best_yo is not None and best_inv is not None:
            break

    return best_yo, best_inv, json.dumps(evidence, ensure_ascii=False)


# ---------------- Orchestration ----------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--backend", choices=["serpapi", "selenium"], default="serpapi")
    ap.add_argument("--engine", choices=["bing", "google"], default="bing")
    ap.add_argument("--limit", type=int, default=0, help="first N rows (0=all)")
    args = ap.parse_args()

    df = pd.read_excel(args.excel, sheet_name=args.sheet)

    # ensure columns
    for col in [
        "Year operational",
        "Investment (CNY)",
        "Notes",
        "Station name",
        "Province",
        "City/County",
        "Partners",
    ]:
        if col not in df.columns:
            df[col] = ""

    processed = 0
    filled_yo = 0
    filled_inv = 0

    for idx, row in df.iterrows():
        if args.limit and processed >= args.limit:
            break

        yo_cell = str(row.get("Year operational", "")).strip()
        inv_cell = str(row.get("Investment (CNY)", "")).strip()
        needs_yo = yo_cell == ""
        needs_inv = inv_cell == ""

        if not (needs_yo or needs_inv):
            continue

        station = row.to_dict()
        try:
            yo, inv, ev_json = enrich_row(
                station, backend=args.backend, engine=args.engine, max_results=10
            )
        except Exception as e:
            yo = inv = None
            ev_json = json.dumps({"error": str(e)}, ensure_ascii=False)

        if needs_yo and yo is not None:
            df.at[idx, "Year operational"] = int(yo)
            filled_yo += 1
        if needs_inv and inv is not None:
            df.at[idx, "Investment (CNY)"] = int(inv)
            filled_inv += 1

        # append evidence to Notes
        prev = str(df.at[idx, "Notes"]).strip()
        joiner = " | " if prev else ""
        human = ""
        try:
            ev = json.loads(ev_json)
            links = []
            if ev.get("yo_url"):
                links.append(f'source(year): {ev["yo_url"]}')
            if ev.get("inv_url"):
                links.append(f'source(inv): {ev["inv_url"]}')
            if links:
                human = " " + "; ".join(links)
        except Exception:
            pass
        df.at[idx, "Notes"] = prev + joiner + f"[auto-evidence] {ev_json}" + human

        processed += 1
        time.sleep(0.3)

    df.to_excel(args.out, sheet_name=args.sheet, index=False)
    print(
        f"Done. Processed rows: {processed}; filled year: {filled_yo}; filled investment: {filled_inv}."
    )
    print(f"Wrote: {args.out}")


if __name__ == "__main__":
    main()
