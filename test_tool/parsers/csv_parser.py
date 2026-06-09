from __future__ import annotations

import csv
from pathlib import Path
from typing import List


def read_csv_file(path: Path) -> str:
    parts: List[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            line = " | ".join([c.strip() for c in row if c and c.strip()])
            if line:
                parts.append(line)
    return "\n".join(parts)