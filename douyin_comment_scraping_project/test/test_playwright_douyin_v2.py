
import argparse
import csv
import sys
import time
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

DEFAULT_EXCEL = "data_Sept 3.xlsx"
DEFAULT_LINK_COLUMN = "Link1"

def load_df(excel_path: Path, sheet_name: str | None):
    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    if isinstance(df, dict):  # multiple sheets returned
        # take the first sheet
        df = next(iter(df.values()))
    return df

def pick_douyin_urls(df, link_column, limit=3):
    urls = []
    if link_column not in df.columns:
        return urls
    series = df[link_column].dropna().astype(str)
    for url in series:
        if "douyin.com" in url:
            urls.append(url.strip())
        if len(urls) >= limit:
            break
    return urls

def click_if_exists(page, selector, timeout=1500):
    try:
        if page.locator(selector).count() > 0:
            page.locator(selector).first.click(timeout=timeout)
            return True
    except Exception:
        pass
    return False

def get_comment_text_candidates(page, max_items=1000):
    texts = []
    seen = set()
    selectors = [
        # Common/Douyin-ish possibilities
        "div[class*='comment']",
        "li[class*='comment']",
        "[data-e2e*='comment']",
        ".comment-item, .comment-list .item, .DCommentItem",
        # Try visible paragraph/text nodes inside comment containers
        "div[class*='comment'] p, li[class*='comment'] p",
        "[data-e2e*='comment'] p",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            cnt = loc.count()
            for i in range(min(cnt, max_items - len(texts))):
                try:
                    t = loc.nth(i).inner_text(timeout=1000).strip()
                    t = " ".join(t.split())
                    if t and t not in seen:
                        texts.append(t if len(t) <= 500 else t[:500])
                        seen.add(t)
                except Exception:
                    pass
            if len(texts) >= max_items:
                break
        except Exception:
            pass
    return texts

def try_find_scroll_container(page):
    # Heuristics: the comment panel often is a side drawer or a panel with scroll.
    candidates = [
        # role dialog / drawer
        "[role='dialog']",
        ".semi-modal, .semi-modal-content, .semi-drawer, .semi-drawer-content",
        # A generic container that holds many comment items
        "div:has(div[class*='comment'])",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                # pick the largest one (by area) if possible
                # fallback to first
                return loc.first
        except Exception:
            pass
    return None

def scroll_element(loc, steps=8, sleep_sec=0.8):
    try:
        for _ in range(steps):
            loc.evaluate("(el) => el.scrollBy(0, el.clientHeight)")
            time.sleep(sleep_sec)
        return True
    except Exception:
        return False

def run_test_on_url(page, url, max_scroll_rounds=10, sleep_after_load=4, sample_cap=500):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(sleep_after_load)

    # Close login/dialogs if any
    for sel in [
        "button[aria-label='close']",
        "button[aria-label='Close']",
        "button:has-text('关闭')",
        "text=×",
        ".semi-modal-close, .semi-modal-close-icon",
        ".dy-account-close, .dy-dialog__close",
    ]:
        click_if_exists(page, sel, timeout=800)

    # Try to open comments
    for sel in ["text=评论", "button:has-text('评论')", "a:has-text('评论')", "[data-e2e='comment']"]:
        if click_if_exists(page, sel, timeout=1000):
            time.sleep(1.2)
            break

    # If there's a "Most popular/All" tab, try clicking both
    for sel in ["text=最热", "text=全部", "text=最 新", "text=最热评论"]:
        click_if_exists(page, sel, timeout=800)

    texts = get_comment_text_candidates(page, max_items=sample_cap//4)
    # Attempt to scroll comment panel specifically
    panel = try_find_scroll_container(page)
    stagnant_rounds = 0
    for r in range(max_scroll_rounds):
        before = len(texts)

        if panel:
            scrolled = scroll_element(panel, steps=3, sleep_sec=0.9)
            if not scrolled:
                # fallback scroll page
                page.mouse.wheel(0, 1500)
                time.sleep(0.8)
        else:
            # scroll the page
            page.mouse.wheel(0, 1500)
            time.sleep(0.8)

        # try expanding "More replies"
        for sel in ["text=展开", "text=更多回复", "button:has-text('展开')", "button:has-text('更多')"]:
            click_if_exists(page, sel, timeout=600)

        time.sleep(0.8)
        # collect again
        new_texts = get_comment_text_candidates(page, max_items=sample_cap)
        texts = new_texts

        if len(texts) <= before:
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0

        if stagnant_rounds >= 3:
            break

    return texts

def main():
    parser = argparse.ArgumentParser(description="Heuristic Douyin comment tester with scrolling via Playwright.")
    parser.add_argument("--excel", default=DEFAULT_EXCEL, help="Path to Excel containing URLs (default: data_Sept 3.xlsx)")
    parser.add_argument("--sheet", default=None, help="Excel sheet name (default: first sheet)")
    parser.add_argument("--link-column", default=DEFAULT_LINK_COLUMN, help="Column name containing URLs (default: Link1)")
    parser.add_argument("--limit", type=int, default=3, help="Number of URLs to test (default: 3)")
    parser.add_argument("--headless", action="store_true", help="Run headless browser (default: False)")
    parser.add_argument("--scroll-rounds", type=int, default=10, help="Max scroll rounds per URL (default: 10)")
    parser.add_argument("--sample-cap", type=int, default=500, help="Max comments to capture per URL (default: 500)")
    args = parser.parse_args()

    excel_path = Path(args.excel)
    if not excel_path.exists():
        print(f"[ERROR] Excel not found: {excel_path.resolve()}")
        sys.exit(1)

    try:
        df = load_df(excel_path, args.sheet)
    except Exception as e:
        print(f"[ERROR] Failed to read Excel: {e}")
        sys.exit(1)

    urls = pick_douyin_urls(df, args.link_column, limit=args.limit)
    if not urls:
        print("[ERROR] No Douyin URLs found.")
        sys.exit(1)

    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(locale="zh-CN")
        page = context.new_page()

        for idx, url in enumerate(urls, 1):
            print(f"\n[INFO] ({idx}/{len(urls)}) Testing: {url}")
            try:
                texts = run_test_on_url(
                    page,
                    url,
                    max_scroll_rounds=args.scroll_rounds,
                    sleep_after_load=4,
                    sample_cap=args.sample_cap,
                )
                print(f"[RESULT] Collected {len(texts)} text blocks (deduplicated).")

                # Save sample for this URL
                csv_path = out_dir / f"douyin_comments_sample_{idx}.csv"
                with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["url", "index", "text"])
                    for i, t in enumerate(texts, 1):
                        w.writerow([url, i, t])
                print(f"[SAVE] Sample saved to {csv_path.resolve()}")
            except Exception as e:
                print(f"[WARN] Failed on URL {url}: {e}")

        browser.close()

if __name__ == "__main__":
    main()
