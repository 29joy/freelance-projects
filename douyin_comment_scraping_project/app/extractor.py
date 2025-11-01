
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
import time
from loguru import logger
from playwright.sync_api import sync_playwright

from .rate_control import polite_wait

COMMENT_HEADERS = [
    "run_id","url","platform","video_id",
    "comment_id","parent_id","is_reply","reply_depth",
    "user_id","username","text","like_count","publish_time",
    "rank_tab","capture_ts","status","notes"
]

@dataclass
class ExtractConfig:
    headless: bool
    polite_mode: bool
    screenshot_on_error: bool
    rank_preference: str
    top_n_comments: int
    grab_replies: bool
    max_replies_per_parent: int
    like_threshold: Optional[int]

def open_browser(headless: bool = False):
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=headless)
    context = browser.new_context(locale="zh-CN")
    page = context.new_page()
    return pw, browser, context, page

def close_all(pw, browser, context):
    try:
        context.close()
        browser.close()
        pw.stop()
    except Exception:
        pass

def _close_popups(page):
    sels = [
        "button[aria-label='close']",
        "button[aria-label='Close']",
        "button:has-text('关闭')",
        "text=×",
        ".semi-modal-close, .semi-modal-close-icon",
        ".dy-account-close, .dy-dialog__close",
    ]
    for sel in sels:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click(timeout=800)
                time.sleep(0.5)
        except Exception:
            continue

def _enter_comments(page):
    triggers = [
        "text=评论",
        "button:has-text('评论')",
        "a:has-text('评论')",
        "[data-e2e='comment']",
    ]
    for sel in triggers:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click(timeout=1200)
                time.sleep(1.0)
                return True
        except Exception:
            continue
    return False

def _click_rank_tab(page, pref: str):
    if pref == "hot":
        cands = ["text=最热", "text=最热评论"]
    else:
        cands = ["text=全部", "text=所有评论"]
    for sel in cands:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click(timeout=800)
                time.sleep(0.6)
                return True
        except Exception:
            continue
    return False

def _scroll_comments(page, rounds: int = 8):
    candidates = [
        "[role='dialog']",
        ".semi-modal, .semi-modal-content, .semi-drawer, .semi-drawer-content",
        "div:has(div[class*='comment'])",
    ]
    target = None
    for sel in candidates:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                target = loc.first
                break
        except Exception:
            continue

    for _ in range(rounds):
        try:
            if target:
                target.evaluate("(el) => el.scrollBy(0, el.clientHeight)")
            else:
                page.mouse.wheel(0, 1500)
        except Exception:
            pass
        time.sleep(0.9)
        for sel in ["text=展开", "text=更多回复", "button:has-text('展开')", "button:has-text('更多')"]:
            try:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.click(timeout=600)
                    time.sleep(0.3)
            except Exception:
                continue

def _collect_comments(page, cap: int = 200) -> List[Dict[str, Any]]:
    texts = []
    seen_blocks = set()
    selectors = [
        ".DCommentItem, .comment-item",
        "div[class*='comment']",
        "li[class*='comment']",
        "[data-e2e*='comment']",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            cnt = loc.count()
            for i in range(cnt):
                try:
                    t = loc.nth(i).inner_text(timeout=900).strip()
                    norm = " ".join(t.split())
                    if norm and norm not in seen_blocks:
                        texts.append({"raw": t, "norm": norm})
                        seen_blocks.add(norm)
                    if len(texts) >= cap * 3:
                        return texts
                except Exception:
                    continue
        except Exception:
            continue
    return texts

def _postprocess_blocks(raw_blocks: List[Dict[str, Any]], cap: int) -> List[Dict[str, Any]]:
    rows = []
    for idx, blk in enumerate(raw_blocks, 1):
        rows.append({
            "comment_id": "",
            "parent_id": "",
            "is_reply": 0,
            "reply_depth": 0,
            "user_id": "",
            "username": "",
            "text": blk["norm"],
            "like_count": "",
            "publish_time": "",
            "rank_tab": "",
            "status": "ok",
            "notes": "",
        })
        if len(rows) >= cap:
            break
    return rows

def extract_for_url(page, url: str, cfg: ExtractConfig) -> Tuple[List[Dict[str, Any]], str]:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3.0)
        _close_popups(page)
        _enter_comments(page)
        _click_rank_tab(page, cfg.rank_preference)
        _scroll_comments(page, rounds=10)
        raw = _collect_comments(page, cap=max(200, cfg.top_n_comments*2))
        rows = _postprocess_blocks(raw, cap=cfg.top_n_comments)
        return rows, "ok" if rows else "empty"
    except Exception as e:
        logger.exception(f"Failed to extract for url={url}: {e}")
        return [], "failed"
