
from __future__ import annotations
from typing import List, Tuple, Optional, Dict
import re
from rapidfuzz import fuzz

def extract_keywords(text: str, max_k: int = 10) -> List[str]:
    import re
    tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", text or "")
    tokens = [t.lower() for t in tokens]
    seen = set()
    kws = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            kws.append(t)
        if len(kws) >= max_k:
            break
    return kws

def score_candidate(title: str, keywords: List[str]) -> int:
    title_norm = title or ""
    base = fuzz.token_set_ratio(" ".join(keywords), title_norm)
    hits = sum(1 for kw in keywords if kw in title_norm)
    return int(min(100, base + min(10, hits)))

def pick_best_candidate(candidates: List[Tuple[str, str]], content_text: str, min_score: int = 85) -> Optional[Dict]:
    kws = extract_keywords(content_text, max_k=10)
    if not candidates or not kws:
        return None
    scored = [(score_candidate(title or "", kws), title, url) for title, url in candidates]
    scored.sort(reverse=True, key=lambda x: x[0])
    best = scored[0]
    if best[0] >= min_score:
        return {"score": best[0], "title": best[1], "url": best[2]}
    return None
