#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
去重并重排 ID 列（A 列）
- 去重键：Station name（B）+ Partners（D）+ Province（E）+ City/County（F）
- 发现重复则删除后续重复行，仅保留首个出现的行
- 去重结束后，把 A 列 ID 按 1..N 重新编号（无论原来是否连续）
- 如果没有重复项，打印提示后仍会输出文件（仅重排 ID）

依赖：
  pip install pandas openpyxl
用法示例：
  python dedupe_reindex.py --excel ./input.xlsx --sheet "sample" --out ./output.xlsx
"""

import argparse
import sys

import pandas as pd

REQUIRED_COLS = ["ID", "Station name", "Partners", "Province", "City/County"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", required=True, help="输入 Excel 路径")
    ap.add_argument("--sheet", required=True, help="工作表名（如：sample）")
    ap.add_argument("--out", required=True, help="输出 Excel 路径（.xlsx）")
    args = ap.parse_args()

    # 读取
    try:
        df = pd.read_excel(args.excel, sheet_name=args.sheet)
    except Exception as e:
        print(f"[Error] 读取 Excel 失败：{e}")
        sys.exit(1)

    # 校验必需列是否存在
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        print(f"[Error] 缺少必要列：{missing}\n当前列：{list(df.columns)}")
        sys.exit(1)

    # 记录原始行数
    n_before = len(df)

    # 计算重复（首个保留，后续重复标记为 True）
    dup_mask = df.duplicated(
        subset=["Station name", "Partners", "Province", "City/County"], keep="first"
    )
    dup_count = int(dup_mask.sum())

    if dup_count == 0:
        print("没有发现重复项。仍将重新编号 ID 并导出。")
    else:
        print(f"发现重复项：{dup_count} 行，将删除重复行，仅保留首个出现的记录。")

    # 删除重复行
    df = df[~dup_mask].copy()

    # 去重后重排 ID（A 列）
    df["ID"] = range(1, len(df) + 1)

    # 输出
    try:
        df.to_excel(args.out, sheet_name=args.sheet, index=False)
    except Exception as e:
        print(f"[Error] 写出 Excel 失败：{e}")
        sys.exit(1)

    n_after = len(df)
    print(
        f"完成：由 {n_before} 行 -> {n_after} 行。已重排 ID 为 1..{n_after}。写出：{args.out}"
    )


if __name__ == "__main__":
    main()
