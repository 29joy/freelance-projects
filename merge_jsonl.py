# merge_jsonl.py
import argparse
import glob
import os
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(
        description="Merge JSONL files with volume splitting."
    )
    parser.add_argument(
        "--inputs",
        required=True,
        help=r"Glob pattern to input files, e.g. deliveries\round_all\clean_files\*clean.jsonl",
    )
    parser.add_argument(
        "--min_lines",
        type=int,
        default=10000,
        help="Minimum lines per volume before considering split.",
    )
    parser.add_argument(
        "--soft_max",
        type=int,
        default=10010,
        help="Only split when lines exceed this value.",
    )
    args = parser.parse_args()

    files = sorted(glob.glob(args.inputs))
    if not files:
        print(f"❌ 没有找到匹配的文件: {args.inputs}")
        return

    input_dir = os.path.dirname(args.inputs)
    if not input_dir:
        input_dir = "."

    out_dir = input_dir
    os.makedirs(out_dir, exist_ok=True)

    date_tag = datetime.now().strftime("%Y%m%d")

    def out_path(idx: int) -> str:
        return os.path.join(out_dir, f"{date_tag}_clean_file_{idx}.jsonl")

    vol_idx = 1
    vol_count = 0
    total_count = 0
    out_files = []  # 记录已写出的卷文件路径
    out_fh = open(out_path(vol_idx), "w", encoding="utf-8")
    out_files.append(out_path(vol_idx))

    for fp in files:
        print(f"➡️ 合并: {fp}")
        with open(fp, "r", encoding="utf-8") as fin:
            for line in fin:
                # 超过 soft_max(10010) 才切卷；确保每卷至少 min_lines(10000)
                if vol_count > args.soft_max:
                    out_fh.close()
                    vol_idx += 1
                    vol_count = 0
                    out_fh = open(out_path(vol_idx), "w", encoding="utf-8")
                    out_files.append(out_path(vol_idx))
                out_fh.write(line)
                vol_count += 1
                total_count += 1

    out_fh.close()

    # 如果最后一卷不足 min_lines 且存在上一卷，则并入上一卷
    if vol_idx > 1 and vol_count < args.min_lines:
        last_path = out_files[-1]
        prev_path = out_files[-2]
        print(
            f"ℹ️ 最后一卷不足 {args.min_lines} 行，合并到上一卷: {last_path} -> {prev_path}"
        )
        with open(prev_path, "a", encoding="utf-8") as fout, open(
            last_path, "r", encoding="utf-8"
        ) as fin:
            for line in fin:
                fout.write(line)
        try:
            os.remove(last_path)
            out_files.pop()
            vol_idx -= 1
        except OSError:
            pass

    print(f"✅ 合并完成：总行数 {total_count}，生成卷数 {vol_idx}")
    for i, p in enumerate(out_files, 1):
        print(f"  - 卷{i}: {p}")


if __name__ == "__main__":
    main()
