#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
机器翻译 4 列（B/D/E/F），无“搜索抽取官方名”，避免噪声。
- D: Partners —— 直接整公司名机翻 + 规范化（Co., Ltd. 等），缓存去重
- E: Province —— 固定对照表 + 机翻兜底
- F: City/County —— 机翻
- B: Station name —— 正文机翻；【…】内按品牌规则处理：
    * '星星*' -> StarCharge（联合品牌如 '星星寅元特' -> 'StarCharge + Yuante'）
    * 其他 token 机翻；如出现“奇怪串”回退到拼音/原文
- 结果尽量 Title Case（公司名/品牌名）

使用：
  pip install pandas openpyxl deep-translator pypinyin requests

  # Google（默认）
  python translate_ev_columns_mt.py --excel input.xlsx --sheet sample --out output.xlsx --cache company_cache.json

  # 有道API（可选，需环境变量）
  set YD_APP_KEY=你的key
  set YD_APP_SECRET=你的secret
  python translate_ev_columns_mt.py --excel input.xlsx --sheet sample --out output.xlsx --cache company_cache.json
"""

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

# Google 翻译
try:
    from deep_translator import GoogleTranslator

    _HAS_GOOGLE = True
except Exception:
    GoogleTranslator = None
    _HAS_GOOGLE = False

# 拼音兜底
try:
    from pypinyin import Style, lazy_pinyin

    _HAS_PINYIN = True
except Exception:
    _HAS_PINYIN = False

# ----------- 基础工具 -----------


def title_case_en(s: str) -> str:
    if not s:
        return s
    # 简单 Title Case（保留常见小词）
    small = {"and", "or", "of", "the", "a", "an", "for", "in", "on", "at", "by", "to"}
    words = re.split(r"(\s+|-|,|\.|/|&)", s.strip())
    out = []
    for w in words:
        if not w or re.match(r"\s+|-|,|\.|/|&", w):
            out.append(w)
            continue
        lw = w.lower()
        if lw in small:
            out.append(lw)
        else:
            out.append(lw[0:1].upper() + lw[1:])
    return "".join(out).strip()


def is_garbage_en(s: str) -> bool:
    """判断是否像 hash/追踪参数：含大量非字母数字、很长、或包含明显URL参数符号"""
    if not s:
        return True
    if any(c in s for c in ["=", "%", "&", "?", "#"]):
        return True
    if len(s) > 80:
        return True
    # 数字占比过高或无空格的很长串
    digits = sum(c.isdigit() for c in s)
    if digits >= max(5, len(s) // 3):  # 数字太多
        return True
    # 至少要有字母
    if not re.search(r"[A-Za-z]", s):
        return True
    return False


def to_pinyin(s: str) -> str:
    if not _HAS_PINYIN or not s:
        return s
    py = "".join(lazy_pinyin(str(s), style=Style.NORMAL))
    return title_case_en(py)


# ----------- 机翻（Google / 有道） -----------


def youdao_translate(q: str) -> Optional[str]:
    """调用有道开放平台（若配置了 YD_APP_KEY/SECRET）"""
    app_key = os.getenv("YD_APP_KEY") or ""
    app_secret = os.getenv("YD_APP_SECRET") or ""
    if not app_key or not app_secret:
        return None
    url = "https://openapi.youdao.com/api"

    def truncate(qs: str) -> str:
        return qs if len(qs) <= 20 else (qs[:10] + str(len(qs)) + qs[-10:])

    salt = str(random.randint(10000, 99999))
    curtime = str(int(time.time()))
    signStr = app_key + truncate(q) + salt + curtime + app_secret
    sign = hashlib.sha256(signStr.encode("utf-8")).hexdigest()
    data = {
        "q": q,
        "from": "zh-CHS",
        "to": "en",
        "appKey": app_key,
        "salt": salt,
        "sign": sign,
        "signType": "v3",
        "curtime": curtime,
    }
    try:
        r = requests.post(url, data=data, timeout=10)
        j = r.json()
        if j.get("errorCode") == "0":
            t = " ".join(j.get("translation", []))
            return t
    except Exception:
        return None
    return None


def google_translate(q: str) -> str:
    if not _HAS_GOOGLE:
        return q
    try:
        return GoogleTranslator(source="auto", target="en").translate(q)
    except Exception:
        return q


def mt_cn2en(q: str) -> str:
    if not q:
        return q
    # 优先有道（若配置），否则 Google
    yt = youdao_translate(q)
    t = yt if yt else google_translate(q)
    if not t:
        t = q
    return t


# ----------- 省份映射 -----------

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


def norm_province(x: str) -> str:
    s = (x or "").strip()
    return PROVINCE_MAP.get(s, mt_cn2en(s))


# ----------- 公司名规范化（翻译后） -----------

COMPANY_SUFFIX_ZH = [
    "有限责任公司",
    "股份有限公司",
    "有限公司",
    "集团有限公司",
    "控股有限公司",
    "公司",
    "集团",
]
COMPANY_SUFFIX_EN = "Co., Ltd."

# 温和行业词替换（仅当英文里没有这些词时）
INDUSTRY_HINTS = [
    ("新能源", "New Energy"),
    ("数字能源", "Digital Energy"),
    ("电气", "Electric"),
    ("电力", "Power"),
    ("充电", "Charging"),
    ("科技", "Technology"),
    ("技术", "Technology"),
    ("停车管理", "Parking Management"),
]


def normalize_company_en(cn: str, en: str) -> str:
    """
    - 统一中文后缀为 Co., Ltd.
    - 对明显公司名做 Title Case
    - 尽量避免垃圾串
    """
    if not en:
        return cn
    s = en.strip()

    # 发现是垃圾串：回退机器翻译重试/原文
    if is_garbage_en(s):
        # 再试一次 google（若之前是有道）
        try_again = google_translate(cn) if youdao_translate(cn) else ""
        if try_again and not is_garbage_en(try_again):
            s = try_again
        else:
            # 仍不行则回退拼音或原文
            py = to_pinyin(cn)
            s = py if py and not is_garbage_en(py) else cn

    # 有中文公司后缀痕迹：统一为 Co., Ltd.
    if any(z in cn for z in COMPANY_SUFFIX_ZH) or "company" in s.lower():
        # 去掉多余标点和多重 Company/Limited
        s = re.sub(
            r"\b(Company|Limited|Ltd\.?|Incorporated|Incorp\.?)\b", "", s, flags=re.I
        )
        s = re.sub(r"\s{2,}", " ", s).strip(" ,.-")
        s = f"{s} {COMPANY_SUFFIX_EN}".strip()

    # 行业提示词：若中文包含、英文未包含，则轻量追加（不强制）
    lower = s.lower()
    for zh, en_hint in INDUSTRY_HINTS:
        if zh in cn and en_hint.lower() not in lower:
            # 仅当长度较短时追加，避免太啰嗦
            if len(s) < 60:
                s = f"{s}, {en_hint}"

    # Title Case
    s = title_case_en(s)
    return s


# ----------- 站名里【…】处理 -----------

STAR_WORDS = {"星星", "星星充", "星星充电"}
STAR_EN = "StarCharge"
BRACKET_RE = re.compile(r"【([^】]+)】")


def translate_brand_token(token: str, cache: Dict[str, str]) -> str:
    tk = token.strip()
    if not tk:
        return tk
    if tk in STAR_WORDS:
        return STAR_EN
    if tk.startswith("星星"):
        other = tk[2:].strip()
        if not other:
            return STAR_EN
        # 其他品牌机翻 + 轻度规范
        if other not in cache:
            raw_en = mt_cn2en(other)
            cache[other] = normalize_company_en(other, raw_en)
        return f"{STAR_EN} + {cache[other]}"
    # 普通品牌：机翻 + 规范
    if tk not in cache:
        raw_en = mt_cn2en(tk)
        cache[tk] = normalize_company_en(tk, raw_en)
    return cache[tk]


def translate_station_name(name_cn: str, cache: Dict[str, str]) -> str:
    if not name_cn:
        return name_cn
    s = str(name_cn)
    out = []
    last = 0
    for m in BRACKET_RE.finditer(s):
        before = s[last : m.start()]
        if before:
            out.append(mt_cn2en(before))
        inner = m.group(1).strip()
        toks = [t for t in re.split(r"[、，,/\s·]+", inner) if t]
        en_toks = [translate_brand_token(tk, cache) for tk in toks]
        out.append("【" + " ".join(en_toks).strip() + "】")
        last = m.end()
    tail = s[last:]
    if tail:
        out.append(mt_cn2en(tail))
    res = "".join(out)
    res = re.sub(r"\s+", " ", res).strip()
    return res


# ----------- Partners 处理 -----------


def split_partners(s: str) -> List[str]:
    if not s:
        return []
    return [t.strip() for t in re.split(r"[、，,;/\s·]+", str(s)) if t.strip()]


def translate_partner_company(cn: str, cache: Dict[str, str]) -> str:
    if cn in STAR_WORDS:
        return STAR_EN
    if cn.startswith("星星"):
        other = cn[2:].strip()
        if not other:
            return STAR_EN
        if other not in cache:
            raw_en = mt_cn2en(other)
            cache[other] = normalize_company_en(other, raw_en)
        return f"{STAR_EN} + {cache[other]}"
    if cn not in cache:
        raw_en = mt_cn2en(cn)
        cache[cn] = normalize_company_en(cn, raw_en)
    return cache[cn]


# ----------- 主流程 -----------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True)
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default="", help="公司名翻译缓存 JSON（读写）")
    args = ap.parse_args()

    try:
        df = pd.read_excel(args.excel, sheet_name=args.sheet)
    except Exception as e:
        print(f"[Error] read excel: {e}")
        sys.exit(1)

    for col in ["Station name", "Partners", "Province", "City/County"]:
        if col not in df.columns:
            df[col] = ""

    # 加载缓存
    cache: Dict[str, str] = {}
    if args.cache and os.path.exists(args.cache):
        try:
            cache = json.load(open(args.cache, "r", encoding="utf-8"))
            print(f"[cache] loaded {len(cache)} entries")
        except Exception:
            cache = {}

    # 省/市
    df["Province"] = df["Province"].apply(norm_province)
    df["City/County"] = df["City/County"].apply(
        lambda x: mt_cn2en(str(x)) if str(x).strip() else x
    )

    # 先收集 Partners & 站名【…】中的唯一 token，先批量翻译（减少重复请求）
    unique_tokens = set()
    for v in df["Partners"].fillna(""):
        unique_tokens.update(split_partners(v))
    for v in df["Station name"].fillna(""):
        for m in BRACKET_RE.finditer(str(v)):
            inner = m.group(1).strip()
            unique_tokens.update([t for t in re.split(r"[、，,/\s·]+", inner) if t])

    # 预翻译（写入缓存）
    for tk in unique_tokens:
        if tk in cache:
            continue
        if tk in STAR_WORDS:
            cache[tk] = STAR_EN
            continue
        if tk.startswith("星星"):
            other = tk[2:].strip()
            if not other:
                cache[tk] = STAR_EN
            else:
                raw_en = mt_cn2en(other)
                cache[other] = normalize_company_en(other, raw_en)
                cache[tk] = f"{STAR_EN} + {cache[other]}"
            continue
        raw_en = mt_cn2en(tk)
        cache[tk] = normalize_company_en(tk, raw_en)
        # 轻微限流，避免被风控
        time.sleep(0.05)

    # 持久化缓存
    if args.cache:
        try:
            json.dump(
                cache,
                open(args.cache, "w", encoding="utf-8"),
                ensure_ascii=False,
                indent=2,
            )
            print(f"[cache] saved {len(cache)} entries")
        except Exception:
            pass

    # 应用到 Partners
    def trans_partners_field(val: str) -> str:
        toks = split_partners(val)
        ens = [translate_partner_company(t, cache) for t in toks]
        return ", ".join([title_case_en(e) for e in ens if e])

    print("[step] Applying Partners mapping...", flush=True)
    df["Partners"] = df["Partners"].apply(trans_partners_field)
    print("[ok] Partners done.", flush=True)

    # 应用到 Station name（含【】）
    print("[step] Translating Station name with bracket rules...", flush=True)
    df["Station name"] = df["Station name"].apply(
        lambda x: translate_station_name(x, cache)
    )
    print("[ok] Station name done.", flush=True)

    # 写文件（明确写入引擎 & 改个新文件名避免锁）
    out_path = args.out
    print(f"[step] Writing Excel to {out_path} ...", flush=True)
    try:
        # 指定 xlsxwriter，通常比 openpyxl 快且更稳定
        df.to_excel(out_path, sheet_name=args.sheet, index=False, engine="xlsxwriter")
        print("[ok] Excel written.", flush=True)
    except Exception as e:
        print(
            f"[warn] Excel write failed with xlsxwriter: {e} ; try openpyxl...",
            flush=True,
        )
        df.to_excel(out_path, sheet_name=args.sheet, index=False, engine="openpyxl")
        print("[ok] Excel written with openpyxl.", flush=True)

    # # 输出
    # try:
    #     # df.to_excel(args.out, sheet_name=args.sheet, index=False)
    #     df.to_excel(args.out, sheet_name=args.sheet, index=False, engine="xlsxwriter")
    # except Exception as e:
    #     print(f"[Error] write excel: {e}")
    #     sys.exit(1)

    # print(f"Done. Wrote: {args.out}")


if __name__ == "__main__":
    main()
