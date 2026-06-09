from __future__ import annotations

import re
from typing import List, Optional

from ..core.models import RequirementSection


def parse_headings(text: str) -> List[RequirementSection]:
    sections: List[RequirementSection] = []
    current: Optional[RequirementSection] = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            if current is not None:
                current.content.append("")
            continue

        stripped = line.lstrip()

        # markdown 标题
        if stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[hashes:].strip()
            current = RequirementSection(level=hashes, title=title)
            sections.append(current)
            continue

        # 编号标题，如 "1. 功能概述" / "2) 登录模块"
        # 修复原 bug: 原代码 any(stripped[:1].isdigit() for _ in [0]) 是无意义的
        if stripped[:1].isdigit() and (
            stripped[1:3].startswith(".") or stripped[1:3].startswith(")")
        ):
            title = stripped[2:].strip()
            current = RequirementSection(level=1, title=title)
            sections.append(current)
            continue

        if current is None:
            current = RequirementSection(level=1, title="整体需求")
            sections.append(current)
        current.content.append(line)

    return sections