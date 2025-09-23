# tools/crawl_clean.py
# -*- coding: utf-8 -*-
import argparse
import hashlib
import json
import random
import re
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

import requests
import yaml
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

requests.adapters.DEFAULT_RETRIES = 2
SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (compatible; DataCollectionBot/1.0; +https://example.org/bot)"
    }
)

# ---- 标点与空白清理 ----
_FW = "，。！？【】（）％＃＠＆：；“”‘’《》"
_HW = ",.!?[]()%#@&:;\"\"''<>"
FULL2HALF = str.maketrans(_FW, _HW)

EMOJI_PAT = re.compile(
    "["  # 统一去 emoji/装饰符
    "\U0001f300-\U0001faff"
    "\U00002702-\U000027b0"
    "\U000024c2-\U0001f251"
    "\u2600-\u27ff"
    "]",
    flags=re.UNICODE,
)
CN_SPACE = "\u3000"
NBSP = "\u00a0"
MULTI_NL = re.compile(r"\n{2,}")
HTML_ENTITY = re.compile(r"&[a-zA-Z0-9#]+;")
HTML_TAG = re.compile(r"<[^>]+>")

# 统一符号：dash/ellipsis/multiply 等
DASHES = (
    "\u2010"  # hyphen
    "\u2011"  # non-breaking hyphen
    "\u2012"  # figure dash
    "\u2013"  # en dash –
    "\u2014"  # em dash —
    "\u2015"  # horizontal bar
)
ELLIPSIS = "\u2026"  # …
MULTIPLY = "\u00d7"  # ×
MINUS_SIGN = "\u2212"  # − (math minus)

# 新增：数学符号 => ASCII 近似
MATH_REPL = (
    ("±", "+/-"),
    ("×", "x"),
    ("÷", "/"),
    ("√", "sqrt"),
    ("∑", "sum"),
    ("∏", "prod"),
    ("≈", "~"),
    ("≤", "<="),
    ("≥", ">="),
    ("∞", "inf"),
    ("∫", "integral"),
    ("∂", "d"),
    ("∆", "delta"),
    ("∇", "nabla"),
)

# ========= 新增：仅图片内容的判定 =========
IMG_ONLY_PAT = re.compile(
    r"^\s*\[Image:\s*https?://[^\]]+\]\s*$",
    re.I,
)
# ========= 新增结束 =========


# -------- YAML 读取 --------
class SiteConfig:
    def __init__(
        self,
        domain: str,
        index_pages: List[str],
        sitemap: bool,
        selectors: dict,
        allow,
        deny,
        meta: dict,
        # NEW: 允许在 YAML 中覆盖 sitemap URL（例如 sitemap_index.xml）
        sitemap_url: str | None = None,  # <<< 新增
    ):
        self.domain = domain
        self.index_pages = index_pages or []
        self.sitemap = bool(sitemap)
        self.selectors = selectors or {}
        self.allow = allow
        self.deny = deny
        self.meta = meta or {}
        self.sitemap_url = sitemap_url  # <<< 新增

    @staticmethod
    def from_yaml(path: Path) -> "SiteConfig":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        domain = data["domain"]
        discover = data.get("discover", {})
        index_pages = discover.get("index_pages") or []
        if isinstance(index_pages, str):
            index_pages = [index_pages]
        sitemap = bool(discover.get("sitemap", True))
        selectors = data.get("selectors", {})
        allow = discover.get("allow", None)
        deny = discover.get("deny", None)
        meta = data.get("meta", {})
        # NEW: 读出 sitemap_url
        sitemap_url = discover.get("sitemap_url")  # <<< 新增
        return SiteConfig(
            domain, index_pages, sitemap, selectors, allow, deny, meta, sitemap_url
        )  # <<< 新增


# ---- 工具：容错选择器 & 规则 ----
def iter_selectors(sel) -> List[str]:
    if not sel:
        return []
    if isinstance(sel, str):
        return [sel]
    if isinstance(sel, (list, tuple)):
        return [s for s in sel if isinstance(s, str)]
    if isinstance(sel, dict):
        if "any" in sel and isinstance(sel["any"], (list, tuple)):
            return [s for s in sel["any"] if isinstance(s, str)]
        if "all" in sel and isinstance(sel["all"], (list, tuple)):
            return [s for s in sel["all"] if isinstance(s, str)]
    return []


def safe_select(soup: BeautifulSoup, selector) -> List:
    out = []
    for css in iter_selectors(selector):
        try:
            out.extend(soup.select(css))
        except Exception:
            continue
    return out


def _norm_rule_list(rules) -> List:
    out = []
    if not rules:
        return out
    if isinstance(rules, str):
        rules = [rules]
    if isinstance(rules, dict):
        rules = []
    for r in rules:
        if not isinstance(r, str):
            continue
        r = r.strip()
        if not r:
            continue
        if len(r) >= 2 and r[0] == "/" and r[-1] == "/":
            try:
                out.append(re.compile(r[1:-1], re.I))
            except re.error:
                out.append(r[1:-1].lower())
        else:
            out.append(r.lower())
    return out


def url_allowed(url: str, allow_rules, deny_rules) -> bool:
    u = url.lower()
    denies = _norm_rule_list(deny_rules)
    for d in denies:
        if isinstance(d, re.Pattern):
            if d.search(u):
                return False
        else:
            if d in u:
                return False
    allows = _norm_rule_list(allow_rules)
    if not allows:
        return True
    for a in allows:
        if isinstance(a, re.Pattern):
            if a.search(u):
                return True
        else:
            if a in u:
                return True
    return False


# ---- 抓取与发现 ----
def fetch(url: str, timeout=10) -> requests.Response | None:
    for _ in range(3):
        try:
            r = SESSION.get(url, timeout=timeout)
            if r.status_code == 200:
                return r
        except requests.RequestException:
            time.sleep(0.3 + random.random() * 0.5)
    return None


def discover_from_index(
    index_pages: List[str], allow, deny, max_pages: int
) -> Set[str]:
    urls = set()
    for idx in index_pages:
        r = fetch(idx)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            if (
                not href
                or href.startswith("#")
                or href.startswith("mailto:")
                or href.startswith("javascript:")
            ):
                continue
            if url_allowed(href, allow, deny):
                urls.add(href)
        # 翻页：rel=next
        next_link = soup.select_one("a[rel='next']")
        page = 1
        while next_link and page < max_pages:
            href = next_link.get("href")
            if not href:
                break
            r2 = fetch(href)
            if not r2:
                break
            s2 = BeautifulSoup(r2.text, "lxml")
            for a in s2.select("a[href]"):
                h = a.get("href", "").strip()
                if h and url_allowed(h, allow, deny):
                    urls.add(h)
            next_link = s2.select_one("a[rel='next']")
            page += 1
    return urls


def _sitemap_links(xml_text: str) -> Tuple[List[str], List[str]]:
    soup = BeautifulSoup(xml_text, "lxml-xml")
    sitemaps = [loc.get_text().strip() for loc in soup.select("sitemap > loc")]
    pages = [loc.get_text().strip() for loc in soup.select("url > loc")]
    return sitemaps, pages


def discover_from_sitemap(root: str, allow, deny, max_pages: int) -> Set[str]:
    """递归抓 sitemapindex 与 urlset。"""
    visited = set()
    found = set()

    def _walk(url: str):
        if url in visited:
            return
        visited.add(url)
        r = fetch(url)
        if not r:
            return
        try:
            sitemaps, pages = _sitemap_links(r.text)
        except Exception:
            soup = BeautifulSoup(r.text, "lxml")
            locs = [x.get_text().strip() for x in soup.select("loc")]
            sitemaps = [u for u in locs if "sitemap" in u.lower()]
            pages = [u for u in locs if "sitemap" not in u.lower()]

        for sm in sitemaps:
            _walk(sm)
        for p in pages:
            if url_allowed(p, allow, deny):
                found.add(p)

    # 允许 root 直接给到 sitemap_index.xml
    candidates = [root]  # <<< 改动：不再强制拼 /sitemap.xml
    if not root.endswith(".xml"):
        candidates = [root.rstrip("/") + "/sitemap.xml", root]

    for c in candidates:
        _walk(c)
    return found


# ---- JSON-LD Recipe 兜底提取 ----
def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _get_image_urls_from_jsonld(image_field: Any) -> List[str]:
    out = []
    for it in _as_list(image_field):
        if isinstance(it, str):
            if it.startswith("http"):
                out.append(it)
        elif isinstance(it, dict):
            u = it.get("url") or it.get("@id") or ""
            if isinstance(u, str) and u.startswith("http"):
                out.append(u)
    # 去重
    seen = set()
    res = []
    for u in out:
        if u not in seen:
            seen.add(u)
            res.append(u)
    return res


def _get_instructions_from_jsonld(instr_field: Any) -> str:
    parts = []
    if not instr_field:
        return ""
    if isinstance(instr_field, str):
        return instr_field.strip()
    for it in _as_list(instr_field):
        if isinstance(it, str):
            parts.append(it.strip())
        elif isinstance(it, dict):
            txt = it.get("text") or it.get("name")
            if txt:
                parts.append(str(txt).strip())
            ils = it.get("itemListElement")
            if ils:
                for step in _as_list(ils):
                    if isinstance(step, dict):
                        t = step.get("text") or step.get("name")
                        if t:
                            parts.append(str(t).strip())
                    elif isinstance(step, str):
                        parts.append(step.strip())
    return "\n".join([p for p in parts if p])


def extract_recipe_from_jsonld(
    soup: BeautifulSoup,
) -> Tuple[str, List[str], str, str, str]:
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    candidates: List[dict] = []
    for sc in scripts:
        txt = sc.string or sc.get_text()
        if not txt:
            continue
        try:
            data = json.loads(txt)
        except Exception:
            continue
        objs = _as_list(data)
        for obj in objs:
            if not isinstance(obj, dict):
                continue
            if "@graph" in obj and isinstance(obj["@graph"], list):
                for g in obj["@graph"]:
                    if isinstance(g, dict):
                        candidates.append(g)
            else:
                candidates.append(obj)

    recipe = None
    for obj in candidates:
        t = obj.get("@type")
        types = _as_list(t)
        types = [x.lower() for x in types if isinstance(x, str)]
        if "recipe" in types:
            recipe = obj
            break
    if not recipe:
        return "", [], "", "", ""

    title = str(recipe.get("name") or "").strip()
    images = _get_image_urls_from_jsonld(recipe.get("image"))
    ings_list = _as_list(recipe.get("recipeIngredient"))
    ingredients = "\n".join([str(x).strip() for x in ings_list if str(x).strip()])
    instructions = _get_instructions_from_jsonld(recipe.get("recipeInstructions"))
    notes = ""
    return title, images, ingredients, instructions, notes


# ---- 内容抽取与清洗 ----
def _extract_first_text(soup: BeautifulSoup, selector) -> str:
    for node in safe_select(soup, selector):
        t = node.get_text("\n", strip=True)
        if t:
            return t
    return ""


def _extract_list_text(soup: BeautifulSoup, selector) -> str:
    acc = []
    for node in safe_select(soup, selector):
        txt = node.get_text("\n", strip=True)
        if txt:
            acc.append(txt)
    return "\n".join(acc).strip()


def _image_urls_from_nodes(soup: BeautifulSoup, selector) -> List[str]:
    urls = []
    for node in safe_select(soup, selector):
        for img in node.select("img"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if src and src.startswith("http"):
                urls.append(src)
        for src in node.select("source[srcset]"):
            ss = src.get("srcset", "").split(",")
            for seg in ss:
                u = seg.strip().split(" ")[0]
                if u.startswith("http"):
                    urls.append(u)
    # 去掉 data:image 占位
    urls = [u for u in urls if not u.startswith("data:image")]
    # 若容器没抓到，回退 OG/Twitter
    if not urls:  # <<< 新增：OG/Twitter 兜底
        for m in soup.select(
            'meta[property="og:image"][content], meta[name="og:image"][content], meta[name="twitter:image"][content]'
        ):
            c = m.get("content", "").strip()
            if c.startswith("http"):
                urls.append(c)
    # 去重
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            out.append(u)
            seen.add(u)
    return out


NOISE_PAT = re.compile(
    r"\b("
    r"photo\s*credit|image\s*source|stock\s*image|affiliate|sponsored|buy\s*now|add\s*to\s*cart|"
    r"comments?|newsletter|subscribe|related\s+(posts|recipes)|read\s+more|share|pin\s+it|follow\s+me|"
    r"amazon|world\s+market|copyright|all\s+rights\s+reserved|"
    r"watch\s+the\s+video(?:\s+(?:above|below))?|video\s+tutorial|tiktok|faqs?"
    r")\b",
    re.I,
)


def clean_text(s: str) -> str:
    if not s:
        return ""
    # 空白与全角
    s = s.replace(CN_SPACE, " ").replace(NBSP, " ")
    s = s.translate(FULL2HALF)
    # HTML
    s = HTML_TAG.sub("", s)
    s = HTML_ENTITY.sub(" ", s)
    # 统一 dash / 省略号 / 乘号 / 数学减号
    s = re.sub(f"[{DASHES}]", "-", s)
    s = s.replace(ELLIPSIS, "...")
    s = s.replace(MULTIPLY, "x").replace(MINUS_SIGN, "-")
    # 统一各类数学符号为 ASCII（避免 R5）
    for src, rep in MATH_REPL:
        if src in s:
            s = s.replace(src, rep)
    # 去列表勾选、emoji
    s = s.replace("▢", "").replace("☐", "")
    s = EMOJI_PAT.sub("", s)
    # 常见噪声词（含 FAQ/FAQs）
    s = re.sub(NOISE_PAT, "", s)
    # 去除括号里的短 FAQ 提示（如 "(answers many FAQs)"）
    s = re.sub(r"\([^)]*\bfaqs?\b[^)]*\)", "", s, flags=re.I)

    # 行级规整：去行首项目符/标点；删掉仅由标点/符号组成的行
    lines = []
    for line in s.splitlines():
        # 去项目符（-/*/•/·/▪/●/◦/—/– 等）
        line = re.sub(r"^\s*([\-–—/*•·▪●◦])\s+", "", line)
        # 删仅由标点或符号构成的行（补充 *）
        if line and re.match(r"^[,:;.!?)\"'`\-*\u00d7]+$", line.strip()):
            continue
        # 去前导标点
        if line and re.match(r"^[,:;.!?)\"'`\-]+\s*", line):
            line = re.sub(r"^[,:;.!?)\"'`\-]+\s*", "", line)
        lines.append(line)
    s = "\n".join(lines)

    # 合并多余空行
    s = MULTI_NL.sub("\n", s)
    return s.strip()


def build_content(
    title: str, img_urls: List[str], ings: str, instr: str, notes: str
) -> str:
    parts = []
    if img_urls:
        parts.append(f"[Image: {img_urls[0]}]")
    if ings:
        parts.append("Ingredients:\n" + ings)
    if instr:
        parts.append("Instructions:\n" + instr)
    if notes:
        parts.append("Notes:\n" + notes)
    return "\n".join(parts).strip()


def hash_id(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def extract_article(url: str, cfg: SiteConfig) -> Dict:
    r = fetch(url)
    if not r:
        raise RuntimeError("fetch_failed")
    soup = BeautifulSoup(r.text, "lxml")

    title = _extract_first_text(soup, cfg.selectors.get("title") or "h1")
    img_sel = cfg.selectors.get("image") or [
        ".wprm-recipe",
        ".tasty-recipe",
        "article",
        "main",
    ]
    img_urls = _image_urls_from_nodes(soup, img_sel)

    ings_raw = _extract_list_text(soup, cfg.selectors.get("ingredients"))
    instr_raw = _extract_list_text(soup, cfg.selectors.get("instructions"))
    notes_sel = cfg.selectors.get("notes")
    notes_raw = _extract_list_text(soup, notes_sel) if notes_sel else ""

    # 去除 UI 标题行
    def strip_ui_headers(t: str) -> str:
        return re.sub(
            r"^\s*(ingredients\s*&\s*substitutes|ingredients|instructions|notes)\b.*?$",
            "",
            t,
            flags=re.I | re.M,
        ).strip()

    ings_raw = strip_ui_headers(ings_raw)
    instr_raw = strip_ui_headers(instr_raw)
    notes_raw = strip_ui_headers(notes_raw)

    ings = clean_text(ings_raw)
    instr = clean_text(instr_raw)
    notes = clean_text(notes_raw)

    # JSON-LD 兜底条件：只要任一核心缺失就尝试（ingredients / instructions / title / image）
    need_fallback = (
        (len(ings) < 10) or (len(instr) < 10) or (not title) or (not img_urls)
    )  # <<< 放宽触发条件
    if need_fallback:
        jl_title, jl_imgs, jl_ings, jl_instr, jl_notes = extract_recipe_from_jsonld(
            soup
        )
        if jl_title and not title:
            title = jl_title
        if (not img_urls) and jl_imgs:
            img_urls = jl_imgs
        if len(ings) < 10 and jl_ings:
            ings = clean_text(jl_ings)
        if len(instr) < 10 and jl_instr:
            instr = clean_text(jl_instr)
        if len(notes) < 5 and jl_notes:
            notes = clean_text(jl_notes)

    content = build_content(title, img_urls, ings, instr, notes)
    content = clean_text(content)

    text = f"{title}\n{content}".strip()
    item = {
        "id": hash_id(url),
        "text": text,
        "meta": {
            "data_info": {
                "lang": "en",
                "url": url,
                "source": cfg.domain,
                "type": cfg.meta.get("type", "Recipe/HowTo"),
                "processing_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "delivery_version": cfg.meta.get("delivery_version", "V1.0"),
                "title": title,
                "content": content,
            },
            "content_info": {
                "domain": cfg.meta.get("domain", "Cooking"),
                "subdomain": cfg.meta.get("subdomain", "Recipes"),
            },
            "collector": cfg.meta.get("collector", "joy"),
            "collected_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M"),
        },
    }
    return item


# ---- 主流程 ----
def run_one_site(cfg_path: Path, args) -> Tuple[int, int, Path, Path, str]:
    cfg = SiteConfig.from_yaml(cfg_path)
    domain = cfg.domain
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    clean_path = out_dir / f"{domain}.clean.jsonl"
    rejected_path = out_dir / f"{domain}.rejected.jsonl"

    seen_urls = set()

    idx_urls = (
        discover_from_index(cfg.index_pages, cfg.allow, cfg.deny, args.max_pages)
        if cfg.index_pages
        else set()
    )
    # 改为优先使用 YAML 的 sitemap_url（若提供）
    sm_root = cfg.sitemap_url or f"https://{domain}/sitemap.xml"  # <<< 新增
    sm_urls = (
        discover_from_sitemap(sm_root, cfg.allow, cfg.deny, args.max_pages)  # <<< 改动
        if cfg.sitemap
        else set()
    )
    all_urls = idx_urls | sm_urls

    print(
        f"[DISCOVER] index={len(idx_urls)} sitemap={len(sm_urls)} total={len(all_urls)}"
    )
    print(f"[DISCOVER_DONE] {domain} total_urls={len(all_urls)}")

    ok = rej = 0
    with clean_path.open("w", encoding="utf-8") as f_ok, rejected_path.open(
        "w", encoding="utf-8"
    ) as f_bad:
        for u in all_urls:
            if args.max_articles and ok + rej >= args.max_articles:
                break
            if u in seen_urls:
                continue
            seen_urls.add(u)
            try:
                item = extract_article(u, cfg)

                # ========= 新增：写入前过滤仅图片内容 =========
                content_str = (
                    item.get("meta", {}).get("data_info", {}).get("content", "")
                )
                if IMG_ONLY_PAT.match(content_str or ""):
                    f_bad.write(json.dumps({"url": u, "reason": "image_only"}) + "\n")
                    rej += 1
                    continue
                # ========= 新增结束 =========

                if len(item["text"]) < args.min_chars:
                    f_bad.write(json.dumps({"url": u, "reason": "too_short"}) + "\n")
                    rej += 1
                    continue
                f_ok.write(json.dumps(item, ensure_ascii=False) + "\n")
                ok += 1
            except Exception as e:
                f_bad.write(
                    json.dumps({"url": u, "reason": f"exception:{type(e).__name__}"})
                    + "\n"
                )
                rej += 1
            time.sleep(0.15 + random.random() * 0.2)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[DONE {ts}] site={domain} ok={ok} rejected={rej} out_dir={out_dir}")
    print(f"clean: {clean_path}")
    print(f"rejected: {rejected_path}")
    return ok, rej, clean_path, rejected_path, domain


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site_config", required=True, help="YAML 文件或目录")
    parser.add_argument("--out_dir", required=True)
    parser.add_argument("--delivery_version", default="V1.0")
    parser.add_argument("--collector", default="joy")
    parser.add_argument("--min_chars", type=int, default=220)
    parser.add_argument("--max_pages", type=int, default=1)
    parser.add_argument("--max_articles", type=int, default=200)
    args = parser.parse_args()

    path = Path(args.site_config)
    if path.is_dir():
        ymls = sorted([p for p in path.glob("*.yml") if p.is_file()])
        print(f"[BATCH] Found {len(ymls)} site configs in: {path}")
        total_ok = total_rej = 0
        for y in ymls:
            print(f"\n[RUN] {y}")
            try:
                ok, rej, *_ = run_one_site(y, args)
                total_ok += ok
                total_rej += rej
            except Exception as e:
                print(f"[ERROR] {y.name}: {e}")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(
            f"\n[BATCH DONE {ts}] sites={len(ymls)} total_ok={total_ok} total_rejected={total_rej} out_dir={args.out_dir}"
        )
    else:
        run_one_site(path, args)


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    main()
