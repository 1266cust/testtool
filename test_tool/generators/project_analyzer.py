from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path
from typing import Dict, List

from ..core.logging import get_logger
from ..core.models import ProjectContext, ProjectFileInfo

logger = get_logger("generators.project_analyzer")

SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "env", ".env",
    "node_modules", ".tox", ".pytest_cache", ".mypy_cache",
    ".eggs", "*.egg-info", "dist", "build",
}

CONFIG_FILES = {
    "pytest.ini", "pyproject.toml", "setup.cfg", "setup.py",
    "requirements.txt", "tox.ini", "Makefile",
}

MAX_FILE_SIZE = 100 * 1024  # 100KB
MAX_CONTENT_SIZE = 8 * 1024  # 8KB per file for LLM context
MAX_FILES = 500
MAX_PROMPT_SIZE = 12 * 1024  # 12KB total prompt context


def extract_project_zip(zip_path: Path, extract_dir: Path) -> Path:
    extract_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    with zipfile.ZipFile(str(zip_path), "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if ".." in name or os.path.isabs(name):
                continue
            parts = Path(name).parts
            if any(p in SKIP_DIRS or p.endswith(".egg-info") for p in parts):
                continue
            if name.endswith(".pyc"):
                continue
            if info.file_size > MAX_FILE_SIZE:
                continue
            if count >= MAX_FILES:
                break

            target = extract_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(str(target), "wb") as dst:
                dst.write(src.read())
            count += 1

    top_entries = list(extract_dir.iterdir())
    if len(top_entries) == 1 and top_entries[0].is_dir():
        return top_entries[0]
    return extract_dir


def analyze_project(project_root: Path) -> ProjectContext:
    project_name = project_root.name

    conftest_files: List[ProjectFileInfo] = []
    page_objects: List[ProjectFileInfo] = []
    test_files: List[ProjectFileInfo] = []
    other_files: List[ProjectFileInfo] = []

    all_paths: List[str] = []

    for dirpath, dirnames, filenames in os.walk(str(project_root)):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.endswith(".egg-info")
        ]
        for fname in sorted(filenames):
            full_path = Path(dirpath) / fname
            rel_path = str(full_path.relative_to(project_root))
            all_paths.append(rel_path)

            if full_path.suffix.lower() == ".py":
                content = _read_file_content(full_path)
                file_info = ProjectFileInfo(
                    relative_path=rel_path,
                    file_type="other",
                    content=content,
                )
                file_info.file_type = _classify_py_file(rel_path, content)

                if file_info.file_type == "conftest":
                    conftest_files.append(file_info)
                elif file_info.file_type == "page_object":
                    page_objects.append(file_info)
                elif file_info.file_type == "test_file":
                    test_files.append(file_info)
                else:
                    other_files.append(file_info)

            elif fname in CONFIG_FILES:
                content = _read_file_content(full_path)
                other_files.append(ProjectFileInfo(
                    relative_path=rel_path,
                    file_type="config",
                    content=content,
                ))

    directory_tree = _build_directory_tree(all_paths)
    detected_patterns = _detect_patterns(
        conftest_files, page_objects, test_files, other_files
    )
    analysis_summary = _build_analysis_summary(
        conftest_files, page_objects, test_files, other_files, detected_patterns
    )

    return ProjectContext(
        project_name=project_name,
        directory_tree=directory_tree,
        conftest_files=conftest_files,
        page_objects=page_objects,
        test_files=test_files,
        other_files=other_files,
        detected_patterns=detected_patterns,
        analysis_summary=analysis_summary,
    )


def build_project_context_prompt(ctx: ProjectContext) -> str:
    parts: List[str] = []
    remaining = MAX_PROMPT_SIZE

    header = f"项目名称: {ctx.project_name}\n\n"
    header += f"项目分析摘要:\n{ctx.analysis_summary}\n\n"
    header += f"目录结构:\n{ctx.directory_tree}\n"
    parts.append(header)
    remaining -= len(header.encode("utf-8"))

    if ctx.detected_patterns:
        pattern_text = "\n检测到的代码模式:\n"
        for key, val in ctx.detected_patterns.items():
            pattern_text += f"  - {key}: {val}\n"
        parts.append(pattern_text)
        remaining -= len(pattern_text.encode("utf-8"))

    for conf in ctx.conftest_files[:2]:
        if remaining <= 0:
            break
        block = f"\n--- conftest: {conf.relative_path} ---\n{conf.content[:3000]}\n"
        parts.append(block)
        remaining -= len(block.encode("utf-8"))

    for po in ctx.page_objects[:3]:
        if remaining <= 0:
            break
        block = f"\n--- Page Object: {po.relative_path} ---\n{po.content[:3000]}\n"
        parts.append(block)
        remaining -= len(block.encode("utf-8"))

    for tf in ctx.test_files[:2]:
        if remaining <= 0:
            break
        block = f"\n--- 测试文件: {tf.relative_path} ---\n{tf.content[:2000]}\n"
        parts.append(block)
        remaining -= len(block.encode("utf-8"))

    return "".join(parts)


def _read_file_content(path: Path) -> str:
    try:
        raw = path.read_bytes()[:MAX_CONTENT_SIZE]
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _classify_py_file(rel_path: str, content: str) -> str:
    name = Path(rel_path).name
    parts = Path(rel_path).parts

    if name == "conftest.py":
        return "conftest"

    page_dirs = {"pages", "page_objects", "po", "page"}
    if any(p.lower() in page_dirs for p in parts[:-1]):
        return "page_object"
    if name.endswith("_page.py") or name.endswith("_po.py"):
        return "page_object"
    if re.search(r"class\s+\w+Page\s*\(", content):
        return "page_object"

    if name.startswith("test_") or name.endswith("_test.py"):
        return "test_file"
    test_dirs = {"tests", "test"}
    if any(p.lower() in test_dirs for p in parts[:-1]):
        if "def test_" in content or "class Test" in content:
            return "test_file"

    return "other"


def _build_directory_tree(paths: List[str], max_lines: int = 80) -> str:
    tree: Dict = {}
    for p in paths:
        parts = Path(p).parts
        node = tree
        for part in parts:
            if part not in node:
                node[part] = {}
            node = node[part]

    lines: List[str] = []

    def _render(node: Dict, prefix: str, depth: int):
        if len(lines) >= max_lines:
            return
        items = sorted(node.keys())
        for i, key in enumerate(items):
            if len(lines) >= max_lines:
                lines.append(prefix + "... (更多文件省略)")
                return
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            lines.append(prefix + connector + key)
            child_prefix = prefix + ("    " if is_last else "│   ")
            if node[key]:
                _render(node[key], child_prefix, depth + 1)

    _render(tree, "", 0)
    return "\n".join(lines)


def _detect_patterns(
    conftest_files: List[ProjectFileInfo],
    page_objects: List[ProjectFileInfo],
    test_files: List[ProjectFileInfo],
    other_files: List[ProjectFileInfo],
) -> Dict[str, str]:
    patterns: Dict[str, str] = {}

    base_classes = set()
    for po in page_objects:
        for m in re.finditer(r"class\s+\w+\s*\((\w+)\)", po.content):
            parent = m.group(1)
            if parent not in ("object", "type"):
                base_classes.add(parent)
    if base_classes:
        patterns["base_class"] = ", ".join(sorted(base_classes))

    import_styles = {"relative": 0, "absolute": 0}
    for f in page_objects + test_files:
        if re.search(r"from\s+\.", f.content):
            import_styles["relative"] += 1
        if re.search(r"from\s+[a-zA-Z_]\w*(\.\w+)+\s+import", f.content):
            import_styles["absolute"] += 1
    if import_styles["relative"] > import_styles["absolute"]:
        patterns["import_style"] = "相对导入 (from .xxx import)"
    elif import_styles["absolute"] > 0:
        patterns["import_style"] = "绝对导入 (from package.module import)"

    fixtures = set()
    for conf in conftest_files:
        for m in re.finditer(r"@pytest\.fixture[^)]*\)\s*\ndef\s+(\w+)", conf.content):
            fixtures.add(m.group(1))
        for m in re.finditer(r"@pytest\.fixture\s*\ndef\s+(\w+)", conf.content):
            fixtures.add(m.group(1))
    if fixtures:
        patterns["fixture_pattern"] = ", ".join(sorted(fixtures))

    dirs_with_pages = set()
    for po in page_objects:
        parent = str(Path(po.relative_path).parent)
        if parent != ".":
            dirs_with_pages.add(parent)
    dirs_with_tests = set()
    for tf in test_files:
        parent = str(Path(tf.relative_path).parent)
        if parent != ".":
            dirs_with_tests.add(parent)
    if dirs_with_pages:
        patterns["page_object_dir"] = ", ".join(sorted(dirs_with_pages))
    if dirs_with_tests:
        patterns["test_dir"] = ", ".join(sorted(dirs_with_tests))

    has_conftest_at_root = any(
        Path(c.relative_path).parent == Path(".") for c in conftest_files
    )
    if has_conftest_at_root:
        patterns["has_root_conftest"] = "是"

    return patterns


def _build_analysis_summary(
    conftest_files: List[ProjectFileInfo],
    page_objects: List[ProjectFileInfo],
    test_files: List[ProjectFileInfo],
    other_files: List[ProjectFileInfo],
    patterns: Dict[str, str],
) -> str:
    parts = [
        f"项目包含 {len(conftest_files)} 个 conftest 文件、"
        f"{len(page_objects)} 个 Page Object 文件、"
        f"{len(test_files)} 个测试文件、"
        f"{len(other_files)} 个其他文件。",
    ]

    if "base_class" in patterns:
        parts.append(f"Page Object 基类: {patterns['base_class']}。")
    if "fixture_pattern" in patterns:
        parts.append(f"已定义的 fixture: {patterns['fixture_pattern']}。")
    if "import_style" in patterns:
        parts.append(f"导入风格: {patterns['import_style']}。")
    if "page_object_dir" in patterns:
        parts.append(f"Page Object 目录: {patterns['page_object_dir']}。")
    if "test_dir" in patterns:
        parts.append(f"测试文件目录: {patterns['test_dir']}。")

    return " ".join(parts)
