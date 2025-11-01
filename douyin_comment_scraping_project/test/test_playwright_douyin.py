
import argparse
import sys
import time
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

DEFAULT_EXCEL = "data_Sept 3.xlsx"
DEFAULT_LINK_COLUMN = "Link1"

def pick_first_douyin_url(df, link_column):
    # Prefer iesdouyin.com or v.douyin.com style links
    series = df[link_column].dropna().astype(str)
    for url in series:
        if "douyin.com" in url:
            return url.strip()
    # Fallback: return the first non-empty
    return series.iloc[0].strip() if not series.empty else None

def run_test(url: str, headless: bool = False, wait_seconds: int = 6, max_print: int = 5):
    print(f"[INFO] Launching Chromium (headless={headless}) ...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(locale="zh-CN")
        page = context.new_page()

        print(f"[INFO] Goto: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # Give time for dynamic content
        time.sleep(wait_seconds)

        # Close potential login/modal dialogs by clicking close buttons if found
        # Try some common selectors
        possible_close_selectors = [
            "button[aria-label='close']",
            "button[aria-label='Close']",
            "button:has-text('关闭')",
            "text=×",
            "svg[aria-label='Close']",
            ".xgplayer .xgplayer-close",
            ".dy-account-close, .dy-dialog__close, .semi-modal-close, .semi-modal-close-icon",
        ]
        for sel in possible_close_selectors:
            try:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.click(timeout=1000)
                    time.sleep(1)
            except Exception:
                pass

        # Try to click "评论" or comment icon/button
        possible_comment_triggers = [
            "text=评论",
            "button:has-text('评论')",
            "a:has-text('评论')",
            "[data-e2e='comment']",
            "[aria-label*='comment']",
        ]
        clicked = False
        for sel in possible_comment_triggers:
            try:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.click(timeout=2000)
                    clicked = True
                    time.sleep(2)
                    break
            except Exception:
                pass

        # Scroll a bit to trigger lazy loading
        try:
            for _ in range(4):
                page.mouse.wheel(0, 1500)
                time.sleep(1)
        except Exception:
            pass

        # Try a set of likely comment item selectors
        comment_candidate_selectors = [
            # Generic
            "div[class*='comment']",
            "li[class*='comment']",
            "[data-e2e*='comment']",
            # Douyin possible classes
            ".comment-item, .comment-list .item, .xgplayer-comment, .DCommentItem",
        ]

        total_found = 0
        texts = []
        for sel in comment_candidate_selectors:
            try:
                loc = page.locator(sel)
                cnt = loc.count()
                if cnt > 0:
                    # collect a few texts
                    for i in range(min(cnt, max_print - len(texts))):
                        try:
                            t = loc.nth(i).inner_text(timeout=1500).strip()
                            if t and t not in texts:
                                texts.append(t if len(t) <= 200 else t[:200])
                        except Exception:
                            pass
                    total_found += cnt
            except Exception:
                pass
            if len(texts) >= max_print:
                break

        print(f"[RESULT] Candidate comment nodes found: {total_found}")
        if texts:
            print("[SAMPLE] First few comment blocks:\n")
            for idx, t in enumerate(texts, 1):
                print(f"--- Comment {idx} ---")
                print(t)
                print()
        else:
            print("[WARN] No obvious comment nodes detected. Comments may require deeper selectors or authenticated API.")

        browser.close()

def main():
    parser = argparse.ArgumentParser(description="Lightweight Douyin comment feasibility test via Playwright.")
    parser.add_argument("--excel", default=DEFAULT_EXCEL, help="Path to Excel containing URLs (default: data_Sept 3.xlsx)")
    parser.add_argument("--sheet", default=None, help="Excel sheet name (default: first sheet)")
    parser.add_argument("--link-column", default=DEFAULT_LINK_COLUMN, help="Column name containing URLs (default: Link1)")
    parser.add_argument("--headless", action="store_true", help="Run browser headless (default: UI visible)")
    parser.add_argument("--wait", type=int, default=6, help="Seconds to wait after load (default: 6)")
    parser.add_argument("--max-print", type=int, default=5, help="Max sample comments to print (default: 5)")
    args = parser.parse_args()

    excel_path = Path(args.excel)
    if not excel_path.exists():
        print(f"[ERROR] Excel not found: {excel_path.resolve()}")
        sys.exit(1)

    try:
        df = pd.read_excel(excel_path, sheet_name=args.sheet)
    except Exception as e:
        print(f"[ERROR] Failed to read Excel: {e}")
        sys.exit(1)

    if args.link_column not in df.columns:
        print(f"[ERROR] Column '{args.link_column}' not in Excel columns: {list(df.columns)}")
        sys.exit(1)

    url = pick_first_douyin_url(df, args.link_column)
    if not url:
        print("[ERROR] No valid Douyin URL found in the specified column.")
        sys.exit(1)

    print(f"[INFO] Testing URL from Excel: {url}")
    run_test(url, headless=args.headless, wait_seconds=args.wait, max_print=args.max_print)

if __name__ == "__main__":
    main()
