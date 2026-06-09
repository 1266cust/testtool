from __future__ import annotations

import re
from typing import List


def clean_feature_line(line: str) -> str:
    cleaned = line.strip()
    for prefix in ("- ", "* ", "+ ", "• ", "1. ", "2. ", "3. ", "4. ", "5. "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    return cleaned


def short_text(text: str, max_len: int = 60) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def split_points(line: str) -> List[str]:
    parts = re.split(r"[；;。.\n]|、|/|\\|，|,", line)
    out: List[str] = []
    for p in parts:
        p2 = p.strip()
        if len(p2) >= 6:
            out.append(p2)
    return out