import re
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup


def _normalize_url(u: str):
    u, _frag = urldefrag(u.strip())
    return u.rstrip("/")


def _allow(u, cfg):
    if not u.startswith(cfg["allow_prefix"]):
        return False
    for bad in cfg.get("block_substrings", []):
        if bad in u:
            return False
    return True


def discover_urls(cfg, max_pages=1):
    """最简单稳定：抓主索引页，抽 a[href]；可扩展分页/站点地图。"""
    from .http import get_html

    seen = set()
    out = []

    for entry_url in cfg["entry_pages"][:max_pages]:
        html = get_html(entry_url, timeout=10.0, retry=2)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        for a in soup.select("a[href]"):
            href = _normalize_url(urljoin(entry_url, a.get("href")))
            if _allow(href, cfg) and href not in seen:
                seen.add(href)
                out.append(href)
    return out
