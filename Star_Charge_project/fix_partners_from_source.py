#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用原始中文文件的 D 列（Partners）重做英文翻译（保守：拼音 + 常见后缀、StarCharge 规范化），
然后覆盖已翻译文件中的 Partners 列，避免出现 hash/追踪参数一类的垃圾字符串。
用法示例：
  python fix_partners_from_source.py --src_cn input_cn.xlsx --src_sheet sample \
                                     --dst_en translated.xlsx --dst_sheet sample \
                                     --out fixed.xlsx
"""

import argparse
import re
import sys

import pandas as pd

try:
    from pypinyin import Style, lazy_pinyin

    _HAS_PINYIN = True
except Exception:
    _HAS_PINYIN = False

STAR_WORDS = {"星星", "星星充", "星星充电"}
STAR_EN = "StarCharge"

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


def to_pinyin(x: str) -> str:
    if not _HAS_PINYIN:
        return x
    s = "".join(lazy_pinyin(str(x), style=Style.NORMAL))
    return s.title() if s and len(s) <= 40 else s


def gentle_company_fallback(zh: str) -> str:
    if not zh:
        return zh
    core = zh
    for zh_suf, _ in SUFFIX_MAP:
        core = core.replace(zh_suf, "")
    core = core.strip("（）() ") or zh
    en_core = to_pinyin(core)
    suffix = None
    for zh_suf, en_suf in SUFFIX_MAP:
        if zh_suf in zh:
            suffix = en_suf
            break
    return f"{en_core} {suffix}".strip() if suffix else en_core


def trans_partner_cn_token(tk: str) -> str:
    tk = tk.strip()
    if not tk:
        return tk
    if tk in STAR_WORDS:
        return STAR_EN
    if tk.startswith("星星"):  # 星星寅元特/星星驰云涧
        other = tk[2:].strip()
        return STAR_EN if not other else f"{STAR_EN} + {gentle_company_fallback(other)}"
    return gentle_company_fallback(tk)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src_cn", required=True, help="原始中文 Excel（含Partners中文）")
    ap.add_argument("--src_sheet", required=True)
    ap.add_argument(
        "--dst_en", required=True, help="已翻译的 Excel（需要覆盖Partners列）"
    )
    ap.add_argument("--dst_sheet", required=True)
    ap.add_argument("--out", required=True, help="输出修正后的 Excel")
    args = ap.parse_args()

    df_cn = pd.read_excel(args.src_cn, sheet_name=args.src_sheet)
    df_en = pd.read_excel(args.dst_en, sheet_name=args.dst_sheet)

    if "ID" in df_cn.columns and "ID" in df_en.columns:
        key = "ID"
    else:
        # 回退：按行对齐
        key = None

    if key:
        df_merged = pd.merge(
            df_en, df_cn[["ID", "Partners"]], on="ID", how="left", suffixes=("", "_CN")
        )
        partners_cn_series = df_merged["Partners_CN"].fillna(
            df_merged.get("Partners", "")
        )
    else:
        partners_cn_series = (
            df_cn["Partners"]
            if "Partners" in df_cn.columns
            else df_en.get("Partners", "")
        )

    fixed = []
    for val in partners_cn_series.fillna(""):
        toks = [t.strip() for t in re.split(r"[、，,;/\s·]+", str(val)) if t.strip()]
        out = [trans_partner_cn_token(t) for t in toks]
        fixed.append(", ".join(out))

    df_en["Partners"] = fixed
    df_en.to_excel(args.out, sheet_name=args.dst_sheet, index=False)
    print(f"Done. Wrote: {args.out}")


if __name__ == "__main__":
    main()
