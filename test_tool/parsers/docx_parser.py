from __future__ import annotations

from pathlib import Path
from typing import List

from docx import Document


def read_docx_file(path: Path) -> str:
    doc = Document(str(path))
    parts: List[str] = []
    for para in doc.paragraphs:
        parts.append(para.text)
    return "\n".join(parts)