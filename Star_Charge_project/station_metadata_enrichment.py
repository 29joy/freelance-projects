#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Station metadata enrichment script
==================================
给定含有站点信息的 Excel（如 sheet: "sample"），脚本会尝试自动检索并填充：
  - Number of vehicle bays
  - Year operational
  - Investment (CNY)

搜索优先中文，倾向微信公众号、政务与权威媒体；解析中文数字与金额单位（万/亿），回填为整数。
仅对为空/Unknown 的目标列写回；已有值不覆盖。证据写入 Notes 列（追加 [auto-evidence]）。

USAGE（示例）
------------
# 方式A：SerpAPI（推荐，有 key 时）
SERPAPI_API_KEY=xxxx python station_metadata_enrichment.py \
  --excel ./Upwork_truck_charging_2.xlsx --sheet "sample" \
  --backend serpapi --out ./Upwork_truck_charging_2_enriched.xlsx

# 方式B：Selenium（无 key；需 Chrome + chromedriver）
python station_metadata_enrichment.py \
  --excel ./Upwork_truck_charging_2.xlsx --sheet "sample" \
  --backend selenium --engine bing \
  --out ./Upwork_truck_charging_2_enriched.xlsx

依赖：pip install pandas openpyxl selenium serpapi
"""

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd

# 可选：SerpAPI
try:
    from serpapi import GoogleSearch
except Exception:
    GoogleSearch = None

# 可选：Selenium
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except Exception:
    webdriver = None


# ------------------------------
# 工具函数
# ------------------------------
CHINESE_NUM_MAP = {
    "零": 0,
    "〇": 0,
    "○": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
    "億": 100000000,
    "亿": 100000000,
}


def chinese_num_to_int(text: str) -> Optional[int]:
    if not text:
        return None
    s = text.strip()

    m = re.match(r"(?P<num>\d+(\.\d+)?)(?P<unit>万|亿)", s)
    if m:
        num = float(m.group("num"))
        unit = m.group("unit")
        mul = 10000 if unit == "万" else 100000000
        return int(round(num * mul))

    if re.fullmatch(r"\d+", s):
        return int(s)

    m2 = re.search(r"(?P<num>\d+(\.\d+)?)(?P<unit>万|亿)", s)
    if m2:
        num = float(m2.group("num"))
        unit = m2.group("unit")
        mul = 10000 if unit == "万" else 100000000
        return int(round(num * mul))

    s = s.replace("億", "亿")
    total = 0
    section = 0
    number = 0
    unit_map = {"十": 10, "百": 100, "千": 1000}
    big_units = {"万": 10000, "亿": 100000000}

    i = 0
    have_num = False
    while i < len(s):
        ch = s[i]
        if ch in CHINESE_NUM_MAP and ch not in unit_map and ch not in big_units:
            number = CHINESE_NUM_MAP[ch]
            have_num = True
        elif ch in unit_map:
            if have_num:
                section += number * unit_map[ch]
            else:
                section += 1 * unit_map[ch]
            number = 0
            have_num = False
        elif ch in big_units:
            section += number
            total += section * big_units[ch]
            section = 0
            number = 0
            have_num = False
        i += 1
    total += section + number
    return total if (section or number or total) else None


def normalize_investment(text: str) -> Optional[int]:
    if not text:
        return None
    s = text.replace(",", "").replace("，", "")

    m = re.search(
        r"(?P<num>\d+(\.\d+)?)\s*(?P<unit>亿元|万亿元|亿|万元|万|元|人民币|RMB|CNY)", s
    )
    if m:
        num = float(m.group("num"))
        unit = m.group("unit")
        if unit in ("万亿元",):
            num = num * 1e12 / 1e4  # 万亿元到元（保守折算）
            return int(round(num))
        if unit in ("亿元", "亿"):
            return int(round(num * 100000000))
        elif unit in ("万元", "万"):
            return int(round(num * 10000))
        else:
            return int(round(num))

    m2 = re.search(r"([零一二两三四五六七八九十百千万亿]+)", s)
    if m2 and ("万" in s or "亿" in s):
        num = chinese_num_to_int(m2.group(1))
        if "亿" in s:
            return int(num * 100000000) if num else None
        if "万" in s:
            return int(num * 10000) if num else None

    m3 = re.search(r"投资(总额)?(约|达|超)?\D*(\d{5,12})", s)
    if m3:
        return int(m3.group(3))
    return None


def extract_vehicle_bays(text: str) -> Optional[int]:
    if not text:
        return None
    patterns = [
        r"(?:停车位|车位|泊位|充电车位|重卡泊位|重卡车位)\D{0,5}(\d{1,5})\s*个",
        r"可同时停(?:放|靠)\D{0,3}(\d{1,5})\s*(?:台|辆)",
        r"共\D{0,3}(\d{1,5})\s*(?:个)?(?:停车位|车位|泊位)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            try:
                return int(m.group(1))
            except:
                pass
    m2 = re.search(
        r"(停车位|车位|泊位|充电车位|重卡泊位|重卡车位)\D{0,3}([零一二两三四五六七八九十百千万亿]+)",
        text,
    )
    if m2:
        num = chinese_num_to_int(m2.group(2))
        return int(num) if num else None
    return None


def extract_year_operational(text: str) -> Optional[int]:
    if not text:
        return None
    m = re.search(
        r"(20[0-3]\d)\s*年.*?(投运|投入运营|正式运营|启用|建成|投产|开放)", text
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


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    score: float


def build_queries(station: Dict) -> List[str]:
    """增强后的模板：在原有基础上，加入星星官网与地方政务/媒体关键词组合（最小diff）。"""
    name = station.get("Station name", "") or ""
    province = station.get("Province", "") or ""
    city = station.get("City/County", "") or ""
    company = station.get("Companies", "") or ""
    base = f"{name} {city} {province} {company}".strip()
    base = re.sub(r"\s+", " ", base)

    # 原有核心查询
    core = [
        f"{base} 投运 投入运营 星星充电",
        f"{base} 停车位 泊位 车位 星星充电",
        f"{base} 总投资 投资额 亿元 万元 星星充电",
        f"{base} 充电站 竣工 启用 星星充电",
        f"{base} 公众号 星星充电",
        f"{name} 投运 车位 投资",
    ]

    # 新增：公众号/政务/官网的定向 site 搜索
    site_pref = []
    if name:
        site_pref.extend(
            [
                f"site:mp.weixin.qq.com {name} 投运",
                f"site:mp.weixin.qq.com {name} 充电站",
                f"site:gov.cn {name} 充电站 投资",
                f"site:starcharge.com {name} 充电站",
            ]
        )

    # 新增：地方政务与媒体关键词（无 site 限制，让搜索引擎匹配本地门户）
    gov_keys = "发改委 工信局 交通运输局 国资委 经信局 住建局"
    media_keys = "日报 新闻网 广播电视台 电视台 媒体 报道"
    locality = []
    if city or province:
        loc = f"{city} {province}".strip()
        locality.extend(
            [
                f"{base} {gov_keys}",
                f"{base} {media_keys}",
                f"{loc} {name} 充电站 投运",
                f"{loc} {name} 投资 亿元 万元",
            ]
        )

    queries = core + site_pref + locality
    return list(dict.fromkeys([q.strip() for q in queries if q.strip()]))


def serp_search(query: str, num: int = 10) -> List[SearchResult]:
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
    query: str, num: int = 10, engine: str = "bing"
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
                    out.append(
                        SearchResult(url=url, title=title, snippet=snippet, score=0.0)
                    )
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
                    out.append(
                        SearchResult(url=url, title=title, snippet=snippet, score=0.0)
                    )
                except Exception:
                    continue
    finally:
        driver.quit()
    return out


def score_result(sr: SearchResult, station: Dict) -> float:
    score = 0.0
    title = (sr.title or "").lower()
    snippet = (sr.snippet or "").lower()
    url = (sr.url or "").lower()
    name = (station.get("Station name", "") or "").lower()
    if name and name in title:
        score += 3
    if name and name in snippet:
        score += 2
    for k in ("City/County", "Province", "Companies"):
        v = (station.get(k, "") or "").lower()
        if v and v in title:
            score += 1.5
        if v and v in snippet:
            score += 1.0
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


def extract_all_from_text(
    text: str,
) -> Tuple[Optional[int], Optional[int], Optional[int], Dict[str, str]]:
    notes = {}
    vb = extract_vehicle_bays(text)
    if vb is not None:
        # 简单片段记录
        notes["vehicle_bays_snippet"] = f"vb≈{vb}"
    yo = extract_year_operational(text)
    if yo is not None:
        notes["year_operational_snippet"] = f"year={yo}"
    inv = None
    for line in text.splitlines():
        if "投资" in line:
            inv = normalize_investment(line)
            if inv:
                notes["investment_snippet"] = line.strip()
                break
    return vb, yo, inv, notes


def enrich_row(
    station: Dict, backend: str = "serpapi", engine: str = "bing", max_results: int = 10
) -> Tuple[Optional[int], Optional[int], Optional[int], str]:
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
        time.sleep(0.8)

    uniq: Dict[str, SearchResult] = {}
    for r in results:
        if not r.url:
            continue
        if r.url not in uniq or r.score > uniq[r.url].score:
            uniq[r.url] = r
    ranked = sorted(uniq.values(), key=lambda x: x.score, reverse=True)[:max_results]

    best_vb = None
    best_yo = None
    best_inv = None
    evidence = {}

    for r in ranked:
        text = fetch_page_text(r.url)
        if not text:
            continue
        vb, yo, inv, notes = extract_all_from_text(text)
        if best_vb is None and vb is not None:
            best_vb = vb
            evidence["vb_url"] = r.url
            evidence.update(
                {f"vb_{k}": v for k, v in notes.items() if k.startswith("vehicle")}
            )
        if best_yo is None and yo is not None:
            best_yo = yo
            evidence["yo_url"] = r.url
            evidence.update(
                {f"yo_{k}": v for k, v in notes.items() if k.startswith("year")}
            )
        if best_inv is None and inv is not None:
            best_inv = inv
            evidence["inv_url"] = r.url
            evidence.update(
                {f"inv_{k}": v for k, v in notes.items() if k.startswith("investment")}
            )

        if best_vb is not None and best_yo is not None and best_inv is not None:
            break

    return best_vb, best_yo, best_inv, json.dumps(evidence, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--excel", required=True, help="Path to the input Excel file")
    parser.add_argument(
        "--sheet", required=True, help="Sheet name to process (e.g., 'sample')"
    )
    parser.add_argument("--out", required=True, help="Path to write enriched Excel")
    parser.add_argument("--backend", choices=["serpapi", "selenium"], default="serpapi")
    parser.add_argument("--engine", choices=["bing", "google"], default="bing")
    parser.add_argument(
        "--limit", type=int, default=0, help="Process only first N rows (0 = all)"
    )
    args = parser.parse_args()

    df = pd.read_excel(args.excel, sheet_name=args.sheet)

    # 目标列，不存在则创建
    for col in ["Number of vehicle bays", "Year operational", "Investment (CNY)"]:
        if col not in df.columns:
            df[col] = ""

    # 证据列：Notes（不存在则创建）
    if "Notes" not in df.columns:
        df["Notes"] = ""

    processed = 0
    for idx, row in df.iterrows():
        if args.limit and processed >= args.limit:
            break

        vb_cell = str(row.get("Number of vehicle bays", "")).strip()
        yo_cell = str(row.get("Year operational", "")).strip()
        inv_cell = str(row.get("Investment (CNY)", "")).strip()

        needs_vb = vb_cell == "" or vb_cell.lower() == "unknown"
        needs_yo = yo_cell == "" or yo_cell.lower() == "unknown"
        needs_inv = inv_cell == "" or inv_cell.lower() == "unknown"

        if not (needs_vb or needs_yo or needs_inv):
            continue

        station = row.to_dict()

        try:
            vb, yo, inv, ev_json = enrich_row(
                station, backend=args.backend, engine=args.engine, max_results=10
            )
        except Exception as e:
            ev_json = json.dumps({"error": str(e)}, ensure_ascii=False)
            vb = yo = inv = None

        if needs_vb and vb is not None:
            df.at[idx, "Number of vehicle bays"] = int(vb)
        if needs_yo and yo is not None:
            df.at[idx, "Year operational"] = int(yo)
        if needs_inv and inv is not None:
            df.at[idx, "Investment (CNY)"] = int(inv)

        # === 最小diff增强：在 Notes 里追加“人读友好”的来源链接 ===
        prev_notes = str(df.at[idx, "Notes"]).strip()
        joiner = " | " if prev_notes else ""

        # 原有 JSON 证据
        tail = f"[auto-evidence] {ev_json}"

        # 解析 JSON，追加简洁来源链接（如有）
        human_tail = ""
        try:
            ev = json.loads(ev_json)
            human_links = []
            if ev.get("vb_url"):
                human_links.append(f'source(vb): {ev["vb_url"]}')
            if ev.get("yo_url"):
                human_links.append(f'source(year): {ev["yo_url"]}')
            if ev.get("inv_url"):
                human_links.append(f'source(inv): {ev["inv_url"]}')
            if human_links:
                human_tail = " " + "; ".join(human_links)
        except Exception:
            pass

        df.at[idx, "Notes"] = prev_notes + joiner + tail + human_tail

        processed += 1
        time.sleep(0.5)

    df.to_excel(args.out, sheet_name=args.sheet, index=False)
    print(f"Done. Wrote: {args.out}")


if __name__ == "__main__":
    main()
