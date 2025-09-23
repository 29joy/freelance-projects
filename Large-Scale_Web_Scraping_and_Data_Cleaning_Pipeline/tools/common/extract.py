from urllib.parse import urljoin

from bs4 import BeautifulSoup


def _text_or_none(node):
    if not node:
        return None
    return node.get_text("\n", strip=True)


def _first(soup, selectors):
    for sel in selectors:
        n = soup.select_one(sel)
        if n:
            return n
    return None


def extract_article_parts(cfg, html, base_url):
    """返回统一结构：title / cover_image / ingredients / instructions / notes / step_images"""
    soup = BeautifulSoup(html, "lxml")

    # 标题
    title = None
    tnode = _first(soup, cfg["selectors"]["title"])
    if tnode:
        title = tnode.get_text(" ", strip=True)
    else:
        ogt = soup.select_one('meta[property="og:title"]')
        if ogt and ogt.get("content"):
            title = ogt["content"].strip()
    title = title or ""

    # 主图
    cover = None
    ogi = soup.select_one('meta[property="og:image"]')
    if ogi and ogi.get("content"):
        cover = ogi["content"].strip()

    # 三大块
    ing_node = _first(soup, cfg["selectors"]["ingredients"])
    ins_node = _first(soup, cfg["selectors"]["instructions"])
    note_node = _first(soup, cfg["selectors"]["notes"])

    # 步骤图片（可选）
    step_imgs = []
    if ins_node:
        for im in ins_node.select("img[src]"):
            src = im.get("src")
            if src and src.startswith(("http://", "https://")):
                step_imgs.append(src)

    return dict(
        title=title,
        cover_image=cover,
        ingredients_html=str(ing_node) if ing_node else None,
        instructions_html=str(ins_node) if ins_node else None,
        notes_html=str(note_node) if note_node else None,
        step_images=step_imgs,
        base_url=base_url,
    )
