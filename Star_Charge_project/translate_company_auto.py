#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd

# translate
try:
    from deep_translator import GoogleTranslator

    _HAS_TRANS = True
except Exception:
    GoogleTranslator = None
    _HAS_TRANS = False

# pinyin
try:
    from pypinyin import Style, lazy_pinyin

    _HAS_PINYIN = True
except Exception:
    _HAS_PINYIN = False

# serpapi
try:
    from serpapi import GoogleSearch
except Exception:
    GoogleSearch = None

# selenium
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except Exception:
    webdriver = None


# ---------- helpers


def t_en(text: str) -> str:
    s = ("" if text is None else str(text)).strip()
    if not s or not _HAS_TRANS:
        return s
    try:
        return GoogleTranslator(source="auto", target="en").translate(s)
    except Exception:
        return s


def to_pinyin(text: str) -> str:
    if not _HAS_PINYIN:
        return text
    s = "".join(lazy_pinyin(str(text), style=Style.NORMAL))
    return s.title() if s and len(s) <= 40 else s


# 省份标准表
PROVINCE_MAP = {
    "北京市": "Beijing Municipality",
    "天津市": "Tianjin Municipality",
    "上海市": "Shanghai Municipality",
    "重庆市": "Chongqing Municipality",
    "河北省": "Hebei Province",
    "山西省": "Shanxi Province",
    "辽宁省": "Liaoning Province",
    "吉林省": "Jilin Province",
    "黑龙江省": "Heilongjiang Province",
    "江苏省": "Jiangsu Province",
    "浙江省": "Zhejiang Province",
    "安徽省": "Anhui Province",
    "福建省": "Fujian Province",
    "江西省": "Jiangxi Province",
    "山东省": "Shandong Province",
    "河南省": "Henan Province",
    "湖北省": "Hubei Province",
    "湖南省": "Hunan Province",
    "广东省": "Guangdong Province",
    "海南省": "Hainan Province",
    "四川省": "Sichuan Province",
    "贵州省": "Guizhou Province",
    "云南省": "Yunnan Province",
    "陕西省": "Shaanxi Province",
    "甘肃省": "Gansu Province",
    "青海省": "Qinghai Province",
    "台湾省": "Taiwan Province",
    "内蒙古自治区": "Inner Mongolia Autonomous Region",
    "广西壮族自治区": "Guangxi Zhuang Autonomous Region",
    "西藏自治区": "Tibet Autonomous Region",
    "宁夏回族自治区": "Ningxia Hui Autonomous Region",
    "新疆维吾尔自治区": "Xinjiang Uygur Autonomous Region",
    "香港特别行政区": "Hong Kong SAR",
    "澳门特别行政区": "Macao SAR",
    "北京": "Beijing",
    "上海": "Shanghai",
    "天津": "Tianjin",
    "重庆": "Chongqing",
    "内蒙古": "Inner Mongolia",
    "广西": "Guangxi",
    "西藏": "Tibet",
    "宁夏": "Ningxia",
    "新疆": "Xinjiang",
}


def normalize_province(x: str) -> str:
    s = (x or "").strip()
    if not s:
        return s
    return PROVINCE_MAP.get(s, t_en(s))


# StarCharge 规范
STAR_WORDS = {"星星", "星星充", "星星充电"}
STARCHAR_GE_EN = "StarCharge"

# 站名中【…】的识别
BRACKET_RE = re.compile(r"【([^】]+)】")

# 为“公司后缀”提供一个温和的规则集（只在 fallback 需要时用）
SUFFIX_MAP = [
    ("有限公司", "Co., Ltd."),
    ("有限责任公司", "Co., Ltd."),
    ("股份有限公司", "Co., Ltd."),
    ("科技", "Technology"),
    ("技术", "Technology"),
    ("新能源", "New Energy"),
    ("数字能源", "Digital Energy"),
    ("电气", "Electric"),
    ("电力", "Power"),
    ("充电", "Charging"),
    ("停车管理", "Parking Management"),
    ("信息", "Information"),
    ("网络", "Network"),
]


def gentle_company_fallback(zh_name: str) -> str:
    """
    保守 fallback：拼音主干 + 合理后缀（不做生硬机翻“易慧->Easy Smart”）
    """
    if not zh_name:
        return zh_name
    core = zh_name
    # 去掉常见组织后缀以便拼音更短
    for zh_suf, _ in SUFFIX_MAP:
        core = core.replace(zh_suf, "")
    core = core.strip("（(）) ") or zh_name
    en_core = to_pinyin(core)
    # 复原一个最常见的公司后缀
    suffix = None
    for zh_suf, en_suf in SUFFIX_MAP:
        if zh_suf in zh_name:
            suffix = en_suf
            break
    return f"{en_core} {suffix}".strip() if suffix else en_core


# ----------- 搜索实现（SerpAPI 或 Selenium）-----------


def serp_search(query: str, num: int = 8) -> List[Tuple[str, str, str]]:
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not api_key or GoogleSearch is None:
        return []
    params = {"engine": "google", "q": query, "num": num, "hl": "zh-CN", "gl": "cn"}
    search = GoogleSearch(params | {"api_key": api_key})
    results = search.get_dict().get("organic_results", [])
    out = []
    for r in results:
        out.append((r.get("link", ""), r.get("title", ""), r.get("snippet", "")))
    return out


def selenium_search(
    query: str, num: int = 8, engine: str = "bing"
) -> List[Tuple[str, str, str]]:
    if webdriver is None:
        return []
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1280,1024")
    driver = webdriver.Chrome(options=opts)
    out = []
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
            items = driver.find_elements(By.CSS_SELECTOR, "li.b_algo")[:num]
            for it in items:
                try:
                    a = it.find_element(By.CSS_SELECTOR, "h2 a")
                    url = a.get_attribute("href")
                    title = a.text
                    snip_el = it.find_element(By.CSS_SELECTOR, ".b_caption p")
                    snippet = snip_el.text if snip_el else ""
                    out.append((url, title, snippet))
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
            items = driver.find_elements(By.CSS_SELECTOR, "div.g")[:num]
            for it in items:
                try:
                    a = it.find_element(By.CSS_SELECTOR, "a")
                    url = a.get_attribute("href")
                    title_el = it.find_element(By.TAG_NAME, "h3")
                    title = title_el.text if title_el else ""
                    snippet = it.text
                    out.append((url, title, snippet))
                except Exception:
                    continue
    finally:
        driver.quit()
    return out


LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9&\.\-,\s]{1,80}")

PRIORITY_DOMAINS = [
    "linkedin.com",
    "mp.weixin.qq.com",
    ".gov.cn",
    "starcharge",
    "xevse",
    ".com",
    ".cn",
    ".net",
]


def pick_best_english(candidates: List[str]) -> Optional[str]:
    # 去噪：去掉全小写网址片段/过短词
    cleaned = []
    for c in candidates:
        cc = c.strip().strip("-–|·•,")
        if len(cc) < 2:
            continue
        # 至少包含一个大写字母作为公司名判据之一
        if re.search(r"[A-Z]", cc):
            cleaned.append(cc)

    # 简单优先：长度合适的、包含 Co|Ltd|Technology 等常见词更靠前
    def score(s: str) -> int:
        sc = 0
        for kw in [
            "Co",
            "Ltd",
            "Limited",
            "Technology",
            "Energy",
            "Power",
            "Charging",
            "Group",
            "Holdings",
            "Inc",
            "Corp",
        ]:
            if re.search(rf"\b{kw}\b", s, flags=re.I):
                sc += 2
        if len(s) >= 6:
            sc += 1
        return sc

    cleaned.sort(key=score, reverse=True)
    return cleaned[0] if cleaned else None


def extract_english_from_text(texts: List[str]) -> Optional[str]:
    cands = []
    for t in texts:
        for m in LATIN_RE.finditer(t or ""):
            cands.append(m.group(0))
    return pick_best_english(cands)


def query_company_english(
    zh_name: str, backend: str = "serpapi", engine: str = "bing"
) -> Optional[str]:
    """
    通过搜索引擎抓取公司“通行英文名”，并做启发式抽取。
    """
    if not zh_name:
        return None

    queries = [
        f"{zh_name} 英文名",
        f"{zh_name} 英文",
        f"{zh_name} official English name",
        f'site:linkedin.com "{zh_name}"',
        f'site:mp.weixin.qq.com "{zh_name}"',
        f"{zh_name} 官网 English",
    ]

    seen_urls = set()
    texts = []
    for q in queries:
        try:
            results = (
                serp_search(q, 8)
                if backend == "serpapi"
                else selenium_search(q, 8, engine)
            )
        except Exception:
            results = []
        for url, title, snippet in results:
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            texts.extend([url, title, snippet])
        time.sleep(0.3)

    # 优先处理出现括注的情形：中文（English …）
    joined = " ".join(texts)
    m = re.search(r"[（(]\s*([A-Za-z][A-Za-z0-9&\.\-,\s]{1,80})\s*[)）]", joined)
    if m:
        cand = m.group(1).strip()
        if len(cand) > 1:
            return cand

    # 一般拉丁串抽取
    pick = extract_english_from_text(texts)
    return pick


# ---------- 核心翻译逻辑：D 列 + B 列【…】 ----------


# 星星系列统一成 StarCharge
def translate_brand_token(
    token: str, backend: str, engine: str, cache: Dict[str, str]
) -> str:
    tk = token.strip()
    if not tk:
        return tk
    if tk in STAR_WORDS:
        return STARCHAR_GE_EN
    if tk.startswith("星星"):  # 星星寅元特 / 星星驰云涧
        other = tk[2:].strip()
        if not other:
            return STARCHAR_GE_EN
        en_other = cache.get(other)
        if not en_other:
            en_other = query_company_english(
                other, backend, engine
            ) or gentle_company_fallback(other)
            cache[other] = en_other
        return f"{STARCHAR_GE_EN} + {en_other}"
    # 其他品牌：先查缓存/搜索，后保守 fallback
    en = cache.get(tk)
    if not en:
        en = query_company_english(tk, backend, engine) or gentle_company_fallback(tk)
        cache[tk] = en
    return en


def translate_station_name(
    name_cn: str, backend: str, engine: str, cache: Dict[str, str]
) -> str:
    if not name_cn:
        return name_cn
    s = str(name_cn)
    out = []
    last = 0
    for m in BRACKET_RE.finditer(s):
        before = s[last : m.start()]
        if before:
            out.append(t_en(before))
        inner = m.group(1).strip()
        tokens = re.split(r"[、，,/\s·]+", inner)
        en_tokens = []
        for tk in tokens:
            if not tk:
                continue
            en_tokens.append(translate_brand_token(tk, backend, engine, cache))
        out.append("【" + " ".join(en_tokens).strip() + "】")
        last = m.end()
    tail = s[last:]
    if tail:
        out.append(t_en(tail))
    res = "".join(out)
    return re.sub(r"\s+", " ", res).strip()


def translate_partners(
    partners_cn: str, backend: str, engine: str, cache: Dict[str, str]
) -> str:
    if not partners_cn:
        return partners_cn
    parts = re.split(r"[、，,;/\s·]+", str(partners_cn).strip())
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if p in STAR_WORDS:
            out.append(STARCHAR_GE_EN)
            continue
        en = cache.get(p)
        if not en:
            en = query_company_english(p, backend, engine) or gentle_company_fallback(p)
            cache[p] = en
        out.append(en)
    return ", ".join(out)


# ---------- Orchestrator ----------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--backend", choices=["serpapi", "selenium"], default="serpapi")
    ap.add_argument("--engine", choices=["bing", "google"], default="bing")
    args = ap.parse_args()

    try:
        df = pd.read_excel(args.excel, sheet_name=args.sheet)
    except Exception as e:
        print(f"[Error] read excel: {e}")
        sys.exit(1)

    # 确保目标列存在
    for col in ["Station name", "Partners", "Province", "City/County"]:
        if col not in df.columns:
            df[col] = ""

    # 省/市列
    df["Province"] = df["Province"].apply(normalize_province)
    df["City/County"] = df["City/County"].apply(t_en)

    # 公司名/站名中的【…】品牌 → 先搜“官方/通行英文名”，再 fallback
    cache: Dict[str, str] = {}

    # D 列 Partners
    df["Partners"] = df["Partners"].apply(
        lambda x: translate_partners(x, args.backend, args.engine, cache)
    )

    # B 列 Station name（含【…】）
    df["Station name"] = df["Station name"].apply(
        lambda x: translate_station_name(x, args.backend, args.engine, cache)
    )

    try:
        df.to_excel(args.out, sheet_name=args.sheet, index=False)
    except Exception as e:
        print(f"[Error] write excel: {e}")
        sys.exit(1)

    print(f"Done. Wrote: {args.out}")


if __name__ == "__main__":
    main()
