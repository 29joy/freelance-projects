
from __future__ import annotations
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
import pandas as pd
from loguru import logger

def read_input_excel(excel_path: Path, sheet_name: Optional[str] = None) -> pd.DataFrame:
    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    if isinstance(df, dict):
        df = next(iter(df.values()))
    return df

def find_columns(df: pd.DataFrame,
                 url_candidates: List[str],
                 content_candidates: List[str],
                 segmented_candidates: List[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    cols = list(df.columns)

    def first_hit(cands: List[str]) -> Optional[str]:
        for cand in cands:
            for c in cols:
                if c.strip().lower() == cand.strip().lower():
                    return c
        lower_cols = [c.lower() for c in cols]
        for cand in cands:
            for i, lc in enumerate(lower_cols):
                if cand.strip().lower() in lc:
                    return cols[i]
        return None

    url_col = first_hit(url_candidates)
    content_col = first_hit(content_candidates)
    seg_col = first_hit(segmented_candidates)

    logger.info(f"Detected columns -> url: {url_col}, content: {content_col}, segmented: {seg_col}")
    return url_col, content_col, seg_col

def write_csv(path: Path, rows: List[Dict[str, Any]], header: List[str]):
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if new_file:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})

def write_failed_report(path: Path, failed_rows: List[Dict[str, Any]]):
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        if not failed_rows:
            f.write("url,status,notes\n")
            return
        keys = sorted(set().union(*[set(d.keys()) for d in failed_rows]))
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in failed_rows:
            w.writerow(r)
