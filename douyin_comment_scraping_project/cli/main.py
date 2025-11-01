
from __future__ import annotations
import argparse
import time
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd
from loguru import logger

from app.config import load_config, AppConfig
from app.io_utils import read_input_excel, find_columns, write_csv, write_failed_report, initialize_csv
from app.extractor import open_browser, close_all, extract_for_url, COMMENT_HEADERS, ExtractConfig
from app.search_matcher import pick_best_candidate

RUN_ID_FMT = "%Y%m%d-%H%M%S"

def ensure_output_files(cfg: AppConfig, run_id: str):
    out_dir = Path(cfg.output.dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    initialize_csv(out_dir / cfg.output.aggregate_filename, COMMENT_HEADERS)
    initialize_csv(out_dir / cfg.output.backfill_report_filename, ["row_index","match_score","matched_title","matched_url"])

def append_rows(cfg: AppConfig, run_id: str, url: str, rows: List[Dict[str, Any]]):
    out_dir = Path(cfg.output.dir)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    for r in rows:
        r.update({
            "run_id": run_id,
            "url": url,
            "platform": "douyin",
            "video_id": "",
            "capture_ts": ts
        })
    write_csv(out_dir / cfg.output.aggregate_filename, rows, COMMENT_HEADERS)

def collect_candidates_from_search(page, query: str, max_candidates: int = 5):
    from urllib.parse import quote
    import time as _t
    url = "https://www.douyin.com/search/" + quote(query)
    tries = 0
    while tries < 3:
        tries += 1
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            _t.sleep(2.0)
            for sel in ["text=暂不登录", "text=取消", "button:has-text('取消')", "button:has-text('暂不登录')"]:
                try:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.click(timeout=800)
                        _t.sleep(0.6)
                        break
                except Exception:
                    pass

            candidates = []
            sels = ["a[href*='/video/']"]
            for sel in sels:
                try:
                    loc = page.locator(sel)
                    cnt = min(loc.count(), max_candidates*2)
                    for i in range(cnt):
                        try:
                            href = loc.nth(i).get_attribute("href") or ""
                            title = loc.nth(i).inner_text(timeout=600) or ""
                            if "/video/" in href:
                                candidates.append((title.strip(), href.strip()))
                        except Exception:
                            continue
                except Exception:
                    continue
                if len(candidates) >= max_candidates:
                    break

            if candidates:
                return candidates[:max_candidates]
            _t.sleep(1.2 * tries)
        except Exception:
            _t.sleep(1.2 * tries)
            continue
    return []

def main():
    parser = argparse.ArgumentParser(description="Douyin Comment Extractor (Pilot CLI)")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to config yaml/json")
    parser.add_argument("--excel", default=None, help="Override excel path")
    parser.add_argument("--sheet", default=None, help="Override sheet name")
    parser.add_argument("--enable-backfill", action="store_true", help="Force enable search backfill (override config)")
    parser.add_argument("--start", type=int, default=0, help="Start row index (inclusive), 0-based in DataFrame order")
    parser.add_argument("--end", type=int, default=None, help="End row index (exclusive). If omitted, process till the end")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    if args.excel: cfg.input.excel_path = args.excel
    if args.sheet: cfg.input.sheet_name = args.sheet
    if args.enable_backfill: cfg.search_backfill.enabled = True

    run_id = time.strftime(RUN_ID_FMT)
    ensure_output_files(cfg, run_id)

    df = read_input_excel(Path(cfg.input.excel_path), sheet_name=cfg.input.sheet_name)
    url_col, content_col, seg_col = find_columns(
        df,
        cfg.input.url_column_candidates or ["Link1","URL","Url"],
        cfg.input.content_column_candidates or ["Content","Text","Title"],
        cfg.input.segmented_column_candidates or ["content_segmented","Segmented","Keywords"],
    )
    if not url_col and not content_col and not seg_col:
        raise SystemExit("Neither URL nor Content columns detected. Please adjust config column candidates.")

    start = max(0, args.start or 0)
    end = args.end if args.end is not None else len(df)
    df_slice = df.iloc[start:end].copy()

    pw, browser, context, page = open_browser(headless=cfg.runtime.headless)
    total = len(df_slice)
    processed = 0

    ext_cfg = ExtractConfig(
        headless=cfg.runtime.headless,
        polite_mode=cfg.runtime.polite_mode,
        screenshot_on_error=cfg.runtime.screenshot_on_error,
        rank_preference=cfg.extraction.rank_preference,
        top_n_comments=cfg.extraction.top_n_comments,
        grab_replies=cfg.extraction.grab_replies,
        max_replies_per_parent=cfg.extraction.max_replies_per_parent,
        like_threshold=cfg.extraction.like_threshold,
    )

    failed_rows: List[Dict[str, Any]] = []
    backfill_rows: List[Dict[str, Any]] = []

    try:
        for local_idx, (row_index, row) in enumerate(df_slice.iterrows(), start=start):
            url = (str(row[url_col]).strip() if url_col and not pd.isna(row[url_col]) else "")
            content_text = ""
            if not url and content_col and not pd.isna(row.get(content_col, "")):
                content_text = str(row.get(content_col, "")).strip()
            if not content_text and seg_col and not pd.isna(row.get(seg_col, "")):
                content_text = str(row.get(seg_col, "")).strip()

            if not url and cfg.search_backfill.enabled and content_text:
                candidates = collect_candidates_from_search(page, content_text, max_candidates=cfg.search_backfill.max_candidates)
                best = pick_best_candidate(candidates, content_text, min_score=cfg.search_backfill.min_match_score)
                if best:
                    url = best["url"]
                    backfill_rows.append({
                        "row_index": row_index,
                        "match_score": best["score"],
                        "matched_title": best["title"],
                        "matched_url": best["url"]
                    })
                else:
                    failed_rows.append({"row_index": row_index, "url": "", "status": "search_unmatched", "notes": ""})
                    processed += 1
                    continue

            if not url:
                failed_rows.append({"row_index": row_index, "url": "", "status": "no_url_and_backfill_disabled", "notes": ""})
                processed += 1
                continue

            rows, status = extract_for_url(page, url, ext_cfg)
            if status == "ok" and rows:
                append_rows(cfg, run_id, url, rows)
            else:
                failed_rows.append({"row_index": row_index, "url": url, "status": status, "notes": ""})

            processed += 1
            if processed % 10 == 0:
                logger.info(f"Progress: {processed}/{total}")

        # Write reports
        write_failed_report(Path(cfg.output.dir) / cfg.output.failed_filename, failed_rows)
        if backfill_rows:
            write_csv(Path(cfg.output.dir) / cfg.output.backfill_report_filename, backfill_rows, ["row_index","match_score","matched_title","matched_url"])

    finally:
        close_all(pw, browser, context)

if __name__ == "__main__":
    main()
