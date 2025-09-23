#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
通用交付文件校验器（最终版）
- 作用范围与顺序：
  1) 文件级：UTF-8/JSONL、(strict 时) 行数≥10k
  2) 逐对象：结构/元信息完整
  3) text 专属：R9（长度≥200）
  4) content 专属：R2–R8、N1–N6、文本规范/失败回退
  5) 跨文件：重复 id
- 输出：
  - 控制台逐条 ERROR
  - 每个输入文件旁生成同名 .report.txt
  - 若多文件，生成 ALL.report.txt 汇总
  - 额外输出：总条数/通过条数/通过率（%）
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set, Tuple

TAG = {
    "R1": "R1",
    "R2": "R2",
    "R3": "R3",
    "R4": "R4",
    "R5": "R5",
    "R6": "R6",
    "R7": "R7",
    "R8": "R8",
    "R9": "R9",
    "N1": "N1",
    "N2": "N2",
    "N3": "N3",
    "N4": "N4",
    "N5": "N5",
    "N6": "N6",
    "DUP_URL": "DUP_URL",
    "DUP_ID": "DUP_ID",
}

HTML_TAG_RE = re.compile(r"<\s*\/?\s*[a-zA-Z][^>]*>", re.S)
HTML_ENTITY_RE = re.compile(r"&[a-zA-Z0-9#]+;")

EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF]"
)
FANCY_BULLETS = {"•", "●", "○", "■", "□", "▢", "◆", "◇", "▪", "▫"}

MULTI_NL_RE = re.compile(r"\n{2,}")
MD_H1_6_RE = re.compile(r"^#+\s", re.M)
MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
MD_TABLE_ROW_RE = re.compile(r"^\s*\|.+\|\s*$", re.M)

MATH_SYMBOLS = set("±×÷√∑∏≈≠≤≥∞∫∂∆∇")
DOLLAR_BLOCK_RE = re.compile(r"\$(?:\\\$|[^\$])+\$")
DISPLAY_BRACKET_RE = re.compile(r"\\\[(?:.|\n)+?\\\]")

CJK_PUNCT = "，。！？【】（）％＃＠：；、“”‘’—…《》·"
CJK_PUNCT_RE = re.compile(f"[{re.escape(CJK_PUNCT)}]")

# —— 噪音检测关键字（更保守，降低误报）——
NOISE_KEYWORDS = [
    # 页面结构/模板噪音（不含 breadcrumb，避免食材误杀）
    "home >",
    "site map",
    "copyright",
    "all rights reserved",
    "terms of use",
    "privacy policy",
    # "about us",  # 去除，避免把 "about using" 误报
    "contact us",
    "menu",
    "footer",
    # 广告与推广
    "sponsored",
    "advertisement",
    "buy now",
    "add to cart",
    "shop now",
    "affiliate",
    "amazon",
    "ebay",
    # 图片与媒体相关
    "photo credit",
    "image source",
    "stock image",
    "watch the video",
    "play video",
    # 外部链接/参考信息
    "related posts",
    "related recipes",
    # "read more",  # 改为正则匹配，避免把 s**read more** 当成噪音
    # 评论与交互
    "leave a reply",
    "comments",
    "like & share",
    "share this",
    "pin it",
    "newsletter",
    "subscribe",
    "get updates",
    # 低质量或重复内容
    "popular posts",
    "latest posts",
    "seo keywords",
    "hot posts",
    # 明确排除块
    "faq",
]

# 更精确的噪音正则（避免误判 e.g. s**read more**）
NOISE_REGEX: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\breferences\b", re.I), "references"),  # 避免匹配 preferences
    (re.compile(r"\bread\s+more\b", re.I), "read more"),  # 新增：带词边界的 read more
]

TEMPLATE_HEAD_HINTS = [
    "table of contents",
    "jump to recipe",
    "print recipe",
    "as seen on",
    "related posts",
    "related recipes",
]

ALLOWED_TYPES = {"Recipe/HowTo", "HowTo", "百科", "问答"}
ALLOWED_DOMAINS = {"Cooking", "Daily Life"}
ALLOWED_SUBDOMAINS = {"Recipes", "Cleaning"}

EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(
    r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})\b"
)
CARD_RE = re.compile(r"\b(?:\d{4}[-\s]){3}\d{4}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

IMAGE_LINE_RE = re.compile(r"^\s*\[Image:\s*https?://[^\]\s]+?\]\s*$", re.M)


@dataclass
class ErrorItem:
    path: str
    line: int
    tag: str
    msg: str


def safe_readlines(path: str) -> Tuple[Optional[List[str]], Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines(), None
    except Exception as e:
        return None, f"无法以 UTF-8 打开：{e}"


def write_report(path: str, errors: List[ErrorItem], passed: int, total: int) -> None:
    rpt = os.path.splitext(path)[0] + ".report.txt"
    with open(rpt, "w", encoding="utf-8") as w:
        w.write(
            f"Validate Report ({datetime.utcnow().isoformat(timespec='seconds')}Z)\n"
        )
        w.write(f"File: {path}\n")
        w.write("=" * 80 + "\n")
        if not errors:
            w.write("[PASS] 无错误\n")
        else:
            for e in errors:
                w.write(f"{e.path}:{e.line}: ERROR [{e.tag}] {e.msg}\n")
        w.write("-" * 80 + "\n")
        rate = (passed / total * 100.0) if total else 0.0
        w.write(f"Summary: total={total} passed={passed} pass_rate={rate:.2f}%\n")


def contains_unprotected_math_symbols(text: str) -> bool:
    if not any(sym in text for sym in MATH_SYMBOLS):
        return False
    protected_spans: List[Tuple[int, int]] = []
    for m in DOLLAR_BLOCK_RE.finditer(text):
        protected_spans.append((m.start(), m.end()))
    for m in DISPLAY_BRACKET_RE.finditer(text):
        protected_spans.append((m.start(), m.end()))

    def is_protected(idx: int) -> bool:
        for a, b in protected_spans:
            if a <= idx < b:
                return True
        return False

    for i, ch in enumerate(text):
        if ch in MATH_SYMBOLS and not is_protected(i):
            return True
    return False


def detect_noise_keyword(text: str) -> Optional[str]:
    for pat, name in NOISE_REGEX:
        if pat.search(text):
            return name
    low = text.lower()
    for kw in NOISE_KEYWORDS:
        if kw in low:
            return kw
    return None


def detect_template_head(text: str) -> Optional[str]:
    low = text.lower()
    for kw in TEMPLATE_HEAD_HINTS:
        if kw in low:
            return kw
    return None


def is_sha_like(s: str) -> bool:
    return bool(
        re.fullmatch(r"[0-9a-fA-F]{32}|[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", s or "")
    )


def is_yyyy_mm_dd(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def is_yyyy_mm_dd_hh_mm(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%dT%H:%M")
        return True
    except Exception:
        return False


def check_file_format(
    path: str, lines: Optional[List[str]], err_msg: Optional[str]
) -> List[ErrorItem]:
    errors: List[ErrorItem] = []
    if err_msg:
        errors.append(ErrorItem(path, 0, TAG["R1"], f"UTF-8/读文件失败：{err_msg}"))
        return errors
    return errors


def check_file_linecount(path: str, lines: List[str], strict: bool) -> List[ErrorItem]:
    errors: List[ErrorItem] = []
    if strict and len(lines) < 10000:
        errors.append(ErrorItem(path, 0, TAG["R1"], "strict 模式：单文件行数 < 10000"))
    return errors


def check_object_structure(path: str, i: int, obj: dict) -> List[ErrorItem]:
    e: List[ErrorItem] = []
    if "id" not in obj:
        e.append(ErrorItem(path, i, TAG["R1"], "缺少字段 `id`"))
    if "text" not in obj:
        e.append(ErrorItem(path, i, TAG["R1"], "缺少字段 `text`"))
    if "meta" not in obj or not isinstance(obj["meta"], dict):
        e.append(ErrorItem(path, i, TAG["R1"], "缺少或非法字段 `meta`"))
        return e
    meta = obj["meta"]

    di = meta.get("data_info")
    if not isinstance(di, dict):
        e.append(ErrorItem(path, i, TAG["R1"], "缺少或非法字段 `meta.data_info`"))
        return e
    required_di = [
        "lang",
        "url",
        "source",
        "type",
        "processing_date",
        "delivery_version",
        "title",
        "content",
    ]
    for k in required_di:
        if k not in di:
            e.append(ErrorItem(path, i, TAG["R1"], f"缺少字段 `meta.data_info.{k}`"))

    ci = meta.get("content_info")
    if not isinstance(ci, dict):
        e.append(ErrorItem(path, i, TAG["R1"], "缺少或非法字段 `meta.content_info`"))
    else:
        for k in ["domain", "subdomain"]:
            if k not in ci:
                e.append(
                    ErrorItem(path, i, TAG["R1"], f"缺少字段 `meta.content_info.{k}`")
                )

    if meta.get("collector") != "joy":
        e.append(ErrorItem(path, i, TAG["R1"], "meta.collector 必须为 'joy'"))
    ct = meta.get("collected_time")
    if not isinstance(ct, str) or not is_yyyy_mm_dd_hh_mm(ct):
        e.append(
            ErrorItem(path, i, TAG["R1"], "meta.collected_time 非 'YYYY-MM-DDThh:mm'")
        )

    if isinstance(di, dict):
        if di.get("lang") not in {"en", "zh"}:
            e.append(
                ErrorItem(path, i, TAG["R1"], "meta.data_info.lang 仅允许 'en' 或 'zh'")
            )
        if di.get("type") not in {"Recipe/HowTo", "HowTo", "百科", "问答"}:
            e.append(
                ErrorItem(
                    path,
                    i,
                    TAG["R1"],
                    f"meta.data_info.type 不在允许集合 {sorted({'Recipe/HowTo','HowTo','百科','问答'})}",
                )
            )
        if not is_yyyy_mm_dd(di.get("processing_date", "")):
            e.append(
                ErrorItem(
                    path, i, TAG["R1"], "meta.data_info.processing_date 非 'YYYY-MM-DD'"
                )
            )
        if di.get("delivery_version") != "V1.0":
            e.append(
                ErrorItem(
                    path, i, TAG["R1"], "meta.data_info.delivery_version 必须为 'V1.0'"
                )
            )

    if isinstance(ci, dict):
        if ci.get("domain") not in {"Cooking", "Daily Life"}:
            e.append(
                ErrorItem(
                    path,
                    i,
                    TAG["R1"],
                    f"meta.content_info.domain 不在允许集合 {sorted({'Cooking','Daily Life'})}",
                )
            )
        if ci.get("subdomain") not in {"Recipes", "Cleaning"}:
            e.append(
                ErrorItem(
                    path,
                    i,
                    TAG["R1"],
                    f"meta.content_info.subdomain 不在允许集合 {sorted({'Recipes','Cleaning'})}",
                )
            )

    if "id" in obj and not re.fullmatch(
        r"[0-9a-fA-F]{32}|[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", str(obj["id"] or "")
    ):
        e.append(ErrorItem(path, i, TAG["R1"], "id 需为 32/40/64 位 hex"))

    return e


def check_text_rules(path: str, i: int, text: str) -> List[ErrorItem]:
    e: List[ErrorItem] = []
    if not isinstance(text, str):
        e.append(ErrorItem(path, i, TAG["R1"], "`text` 必须为字符串"))
        return e
    if len(text) < 200:
        e.append(ErrorItem(path, i, TAG["R9"], "文本长度 < 200"))
    return e


def _check_R2(path: str, i: int, content: str) -> List[ErrorItem]:
    e: List[ErrorItem] = []
    if MD_H1_6_RE.search(content):
        e.append(
            ErrorItem(path, i, TAG["R2"], "正文内禁止 Markdown 标题（# 开头的行）")
        )
    kw = detect_template_head(content)
    if kw:
        e.append(
            ErrorItem(path, i, TAG["R2"], f"疑似模板头/多主题内容触发关键字：{kw}")
        )
    return e


def _check_R3(path: str, i: int, content: str, lang: str) -> List[ErrorItem]:
    e: List[ErrorItem] = []
    if MULTI_NL_RE.search(content):
        e.append(ErrorItem(path, i, TAG["R3"], "存在连续 >=2 个换行符"))
    if EMOJI_RE.search(content) or any(b in content for b in FANCY_BULLETS):
        e.append(ErrorItem(path, i, TAG["R3"], "含 emoji/艺术字/特殊装饰符"))
    if lang == "en" and CJK_PUNCT_RE.search(content):
        e.append(ErrorItem(path, i, TAG["R3"], "中英文标点混用或与 lang 不匹配"))
    if re.search(r"(?m)^(?: {4,}|\t+)\S", content):
        e.append(ErrorItem(path, i, TAG["R3"], "存在异常缩进行"))
    return e


def _check_R4(path: str, i: int, content: str) -> List[ErrorItem]:
    e: List[ErrorItem] = []
    if HTML_TAG_RE.search(content) or HTML_ENTITY_RE.search(content):
        e.append(ErrorItem(path, i, TAG["R4"], "存在 HTML 标签或实体残留"))
    kw = detect_noise_keyword(content)
    if kw:
        e.append(
            ErrorItem(
                path,
                i,
                TAG["R4"],
                f"检出网页噪音（广告/导航/版权/推荐/FAQ/社交/HTML 等）：{kw}",
            )
        )
    return e


def _check_R5(path: str, i: int, content: str) -> List[ErrorItem]:
    e: List[ErrorItem] = []
    if MD_IMAGE_RE.search(content):
        e.append(ErrorItem(path, i, TAG["R5"], "禁止 Markdown 图片语法 ![alt](...)"))
    if MD_TABLE_ROW_RE.search(content):
        e.append(ErrorItem(path, i, TAG["R5"], "禁止 Markdown 表格行（|...|）"))
    if contains_unprotected_math_symbols(content):
        e.append(
            ErrorItem(
                path,
                i,
                TAG["R5"],
                "检出未被 $...$ 或 \\[...\\] 包裹的数学符号（±×÷√∑ 等）",
            )
        )
    if "http" in content:
        urls = re.findall(r"https?://\S+", content)
        for u in urls:
            if re.search(r"\.(?:png|jpe?g|gif|webp)(?:\?|#|$)", u, re.I):
                line_match = re.search(rf"(?m)^.*{re.escape(u)}.*$", content)
                if line_match:
                    line_text = line_match.group(0)
                    if not IMAGE_LINE_RE.fullmatch(line_text.strip()):
                        e.append(
                            ErrorItem(
                                path,
                                i,
                                TAG["R5"],
                                f"图片需用 '[Image: URL]' 行表示：{u}",
                            )
                        )
    return e


def _check_R6(path: str, i: int, content: str) -> List[ErrorItem]:
    e: List[ErrorItem] = []
    if re.search(r"\bxxxx+\b", content) or re.search(r"\bxxx@|@xxx\b", content):
        e.append(
            ErrorItem(
                path,
                i,
                TAG["R6"],
                "PII 掩码只能为 'xxx'，不允许 'xxxx' 或 'xxx@/ @xxx' 等变体",
            )
        )
    if EMAIL_RE.search(content):
        e.append(ErrorItem(path, i, TAG["R6"], "检测到邮箱明文，应匿名为 'xxx'"))
    if PHONE_RE.search(content):
        e.append(ErrorItem(path, i, TAG["R6"], "检测到电话号码明文，应匿名为 'xxx'"))
    if CARD_RE.search(content):
        e.append(
            ErrorItem(path, i, TAG["R6"], "检测到银行卡号/信用卡号明文，应匿名为 'xxx'")
        )
    if SSN_RE.search(content):
        e.append(ErrorItem(path, i, TAG["R6"], "检测到社会安全号明文，应匿名为 'xxx'"))
    return e


def _check_R7_R8_placeholder(path: str, i: int) -> List[ErrorItem]:
    return []


def _check_text_norms(path: str, i: int, content: str) -> List[ErrorItem]:
    e: List[ErrorItem] = []
    if re.search(r"(?m)^\s*[\-\*\u25A2]\s+\S", content):  # -, *, ▢
        e.append(
            ErrorItem(
                path, i, TAG["R3"], "仍存在列表前缀（-/*/▢ 等），应在清洗阶段去除"
            )
        )
    return e


def _check_failback(path: str, i: int, content: str) -> List[ErrorItem]:
    return []


def check_content_rules(path: str, i: int, obj: dict) -> List[ErrorItem]:
    e: List[ErrorItem] = []
    di = obj.get("meta", {}).get("data_info", {})
    lang = di.get("lang", "en")
    content = di.get("content", "")
    if not isinstance(content, str):
        e.append(ErrorItem(path, i, TAG["R1"], "`meta.data_info.content` 必须为字符串"))
        return e

    e += _check_R2(path, i, content)
    e += _check_R3(path, i, content, lang)
    e += _check_R4(path, i, content)
    e += _check_R5(path, i, content)
    e += _check_R6(path, i, content)
    e += _check_R7_R8_placeholder(path, i)
    e += _check_text_norms(path, i, content)
    e += _check_failback(path, i, content)

    return e


def check_cross_file_ids(all_records: List[Tuple[str, int, dict]]) -> List[ErrorItem]:
    e: List[ErrorItem] = []
    seen: Dict[str, Tuple[str, int]] = {}
    for path, line, obj in all_records:
        idv = str(obj.get("id", ""))
        if not idv:
            continue
        key = idv.lower()
        if key in seen:
            op, ol = seen[key]
            e.append(
                ErrorItem(
                    path, line, TAG["DUP_ID"], f"跨文件重复 id（首次见于 {op}:{ol}）"
                )
            )
        else:
            seen[key] = (path, line)
    return e


def check_file_dup_urls(path: str, objs: List[Tuple[int, dict]]) -> List[ErrorItem]:
    e: List[ErrorItem] = []
    seen: Dict[str, int] = {}
    for line, obj in objs:
        url = str(obj.get("meta", {}).get("data_info", {}).get("url", "")).strip()
        if not url:
            continue
        key = url
        if key in seen:
            e.append(
                ErrorItem(
                    path,
                    line,
                    TAG["DUP_URL"],
                    f"同文件重复 URL（首次见于行 {seen[key]}）",
                )
            )
        else:
            seen[key] = line
    return e


def validate_paths(paths: List[str], strict: bool) -> List[ErrorItem]:
    all_errors: List[ErrorItem] = []
    cross_records: List[Tuple[str, int, dict]] = []

    # 通过率统计
    overall_total = 0
    overall_passed = 0

    for p in paths:
        lines, err = safe_readlines(p)
        per_file_errors: List[ErrorItem] = []
        per_file_objs: List[Tuple[int, dict]] = []

        per_file_errors += check_file_format(p, lines, err)
        if lines is None:
            write_report(p, per_file_errors, passed=0, total=0)
            all_errors += per_file_errors
            continue
        per_file_errors += check_file_linecount(p, lines, strict=strict)

        file_total = 0
        file_passed = 0

        for idx, raw in enumerate(lines, 1):
            raw = raw.rstrip("\n")
            if not raw.strip():
                per_file_errors.append(
                    ErrorItem(p, idx, TAG["R1"], "空行/非 JSON 对象")
                )
                continue
            file_total += 1
            try:
                obj = json.loads(raw)
            except Exception as ex:
                per_file_errors.append(
                    ErrorItem(p, idx, TAG["R1"], f"JSON 解析失败：{ex}")
                )
                continue

            per_file_objs.append((idx, obj))
            cross_records.append((p, idx, obj))

            errs_before = len(per_file_errors)

            per_file_errors += check_object_structure(p, idx, obj)
            text = obj.get("text", "")
            per_file_errors += check_text_rules(p, idx, text)
            per_file_errors += check_content_rules(p, idx, obj)

            # 若该对象无新增错误，计为通过
            if len(per_file_errors) == errs_before:
                file_passed += 1

        per_file_errors += check_file_dup_urls(p, per_file_objs)

        # 写单文件报告 + 汇总通过率
        write_report(p, per_file_errors, passed=file_passed, total=file_total)
        overall_total += file_total
        overall_passed += file_passed
        all_errors += per_file_errors

    all_errors += check_cross_file_ids(cross_records)

    if len(paths) > 1:
        merged = os.path.commonpath(paths)
        out = os.path.join(
            merged if os.path.isdir(merged) else os.path.dirname(paths[0]),
            "ALL.report.txt",
        )
        with open(out, "w", encoding="utf-8") as w:
            w.write(
                f"Validate Report ({datetime.utcnow().isoformat(timespec='seconds')}Z)\n"
            )
            w.write("Files:\n")
            for p in paths:
                w.write(f"  - {p}\n")
            w.write("=" * 80 + "\n")
            if not all_errors:
                w.write("[PASS] 无错误\n")
            else:
                for e in all_errors:
                    w.write(f"{e.path}:{e.line}: ERROR [{e.tag}] {e.msg}\n")
            w.write("-" * 80 + "\n")
            rate = (overall_passed / overall_total * 100.0) if overall_total else 0.0
            w.write(
                f"Summary: total={overall_total} passed={overall_passed} pass_rate={rate:.2f}%\n"
            )

    # 控制台也打印一次通过率
    if overall_total:
        print(
            f"[SUMMARY] total={overall_total} passed={overall_passed} pass_rate={overall_passed/overall_total*100:.2f}%"
        )

    return all_errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        help="输入 JSONL 文件路径（可用引号+glob）",
    )
    parser.add_argument(
        "--strict", action="store_true", help="严格模式：单文件行数须 ≥ 10000"
    )
    args = parser.parse_args()

    paths: List[str] = []
    for pat in args.inputs:
        paths.extend(glob.glob(pat))
    paths = sorted(set(paths))

    errs = validate_paths(paths, strict=args.strict)
    if not errs:
        print("[PASS] 所有检查通过")
    else:
        for e in errs:
            print(f"{e.path}:{e.line}: ERROR [{e.tag}] {e.msg}")


if __name__ == "__main__":
    main()
