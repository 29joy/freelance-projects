import re

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE = re.compile(
    r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b"
)
CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


def mask_pii(s: str, lang="en") -> str:
    s = EMAIL.sub("xxx", s)
    # 注意：食谱数字很多，电话/卡号才强替换；尽量避免误杀 1/2 cup, 10-12 minutes
    s = CARD.sub("xxx", s)
    s = PHONE.sub("xxx", s)
    return s
