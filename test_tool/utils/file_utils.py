from __future__ import annotations

from pathlib import Path
from typing import Set

SUPPORTED_EXTENSIONS: Set[str] = {
    ".txt", ".md", ".markdown",
    ".docx", ".pdf",
    ".csv", ".xlsx", ".xlsm",
    ".json",
    ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff",
}

IMAGE_EXTENSIONS: Set[str] = {
    ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff",
}


def is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def get_file_category(path: Path) -> str:
    ext = path.suffix.lower()

    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in {".txt", ".md", ".markdown"}:
        return "text"
    if ext == ".docx":
        return "docx"
    if ext == ".csv":
        return "csv"
    if ext in {".xlsx", ".xlsm"}:
        return "excel"
    if ext == ".json":
        return "json"

    return "unknown"