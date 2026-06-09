from __future__ import annotations

import json
from pathlib import Path


def read_json_file(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    return json.dumps(data, ensure_ascii=False, indent=2)