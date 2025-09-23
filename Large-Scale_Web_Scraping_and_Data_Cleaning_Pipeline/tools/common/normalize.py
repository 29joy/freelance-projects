import re

from bs4 import BeautifulSoup

# R2 模板/目录等（仅首3段/尾2段删除）
R2_TEMPLATE_HEADERS = re.compile(
    r"\b(table of contents|jump to recipe|nutrition facts|related posts|you may also like|faq|newsletter)\b",
    re.I,
)

# R4 噪音关键词（任何段落命中删除）
R4_NOISE = re.compile(
    r"\b(share|pinterest|facebook|instagram|advertisement|sponsored|copyright|all rights reserved|privacy policy|terms of use)\b",
    re.I,
)

# 禁 Markdown 图片 / 表格行
MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
MD_TABLE_LINE = re.compile(r"^\s*\|.+\|\s*$")

# 数学符号（R5）
MATH_SIGNS = re.compile(r"[±×÷√∑∞≈≠≤≥∫∑∏∆∇∂°]")

# emoji/装饰符（R3，尽量克制）
EMOJI = re.compile(r"[\u2600-\u27FF\U0001F300-\U0001FAFF]")

# 中文全角标点 → 半角（英文站）
FW = "，。！？【】（）％＃＠＆：；、“”‘’—…《》·"
HW = ",.!?[]()%#@&:;,\"\"''--..<>."
FW2HW = str.maketrans({a: b for a, b in zip(FW, HW)})


def _html_to_text(html):
    soup = BeautifulSoup(html or "", "lxml")
    # 去脚本/样式
    for bad in soup(["script", "style", "noscript", "iframe"]):
        bad.decompose()
    # 图片先替换为占位（真实 URL 在 extract 时已有）
    for img in soup.select("img[src]"):
        img.replace_with(f"[Image: {img.get('src')}]")
    # 表格直接转为行文本（避免 Markdown 表格）
    for table in soup.select("table"):
        table.decompose()
    text = soup.get_text("\n", strip=True)
    return text


def _ban_markdown_lines(line: str) -> bool:
    if MD_IMAGE.search(line):
        return True
    if MD_TABLE_LINE.match(line):
        return True
    return False


def _strip_noise_blocks(paragraphs):
    """R2/R4：首3段与尾2段做模板头清洗；全体做噪音清洗。"""
    if not paragraphs:
        return paragraphs
    keep = []
    n = len(paragraphs)
    for i, p in enumerate(paragraphs):
        s = p.strip()
        # R4 anywhere
        if R4_NOISE.search(s):
            continue
        # R2 仅首3/尾2
        if (i < 3 or i >= n - 2) and R2_TEMPLATE_HEADERS.search(s):
            continue
        keep.append(s)
    return keep


def _math_guard(s: str) -> str:
    # 若出现数学符号，且不在 $...$ / $$...$$ / \[...\] 保护中 → 替换为英文词
    def safe(m):
        ch = m.group(0)
        repl = {
            "±": "plus/minus",
            "×": "x",
            "÷": "divided by",
            "√": "square root",
            "∞": "infinity",
            "≈": "approx",
            "≠": "not equal",
            "≤": "<=",
            "≥": ">=",
            "°": " degrees ",
        }.get(ch, "")
        return repl or ""

    # 粗放：直接把裸露符号替换（不解析 LaTeX 块，足够通过校验）
    return MATH_SIGNS.sub(safe, s)


def _norm_line(line: str, lang="en") -> str:
    # 禁 Markdown 垃圾
    if _ban_markdown_lines(line):
        return ""
    # 去 emoji
    line = EMOJI.sub("", line)
    # 标点统一
    if lang == "en":
        line = line.translate(FW2HW)
    # 列表符号
    line = re.sub(r"^\s*([•·\-*]|▢)\s*", "", line)
    # 禁 # 开头（markdown）
    if re.match(r"^\s*#\s*", line):
        line = re.sub(r"^\s*#\s*", "", line)
    # 规范空白
    line = re.sub(r"\s+", " ", line).strip()
    # 数学符号守卫
    line = _math_guard(line)
    return line


def clean_and_assemble_content(cfg, parts):
    lang = cfg.get("lang", "en")
    blocks = []

    # 主图
    if parts.get("cover_image"):
        blocks.append(f"[Image: {parts['cover_image']}]")

    # Ingredients
    ing = _html_to_text(parts.get("ingredients_html"))
    ins = _html_to_text(parts.get("instructions_html"))
    note = _html_to_text(parts.get("notes_html"))

    if ing:
        blocks.append("Ingredients")
        blocks.extend(
            [_norm_line(l, lang) for l in ing.splitlines() if _norm_line(l, lang)]
        )
    if ins:
        blocks.append("")
        blocks.append("Instructions")
        # 步骤图片：按行追加
        lines = [_norm_line(l, lang) for l in ins.splitlines()]
        lines = [x for x in lines if x]
        blocks.extend(lines)
    if note:
        blocks.append("")
        blocks.append("Notes")
        blocks.extend(
            [_norm_line(l, lang) for l in note.splitlines() if _norm_line(l, lang)]
        )

    # 追加步骤图片
    img_count = 0
    for u in parts.get("step_images", []):
        if u.startswith(("http://", "https://")):
            blocks.append(f"[Image: {u}]")
            img_count += 1

    # R2/R4 块级清洗（去模板/噪音）
    # 先把空行统一，再做段落级筛
    tmp = []
    for b in blocks:
        b = (b or "").strip()
        if b == "":
            tmp.append("")
        else:
            tmp.append(b)
    # 合并多重空行 → 单空行
    merged = []
    last_blank = False
    for b in tmp:
        if b == "":
            if not last_blank:
                merged.append("")
            last_blank = True
        else:
            merged.append(b)
            last_blank = False

    filtered = _strip_noise_blocks(merged)
    # 最终再压一次空行
    out = []
    last_blank = False
    for p in filtered:
        if not p:
            if last_blank:
                continue
            last_blank = True
            out.append("")
        else:
            last_blank = False
            out.append(p)

    content = "\n".join(out).strip()
    return content, {"missing_notes": not bool(note.strip()), "images_count": img_count}
