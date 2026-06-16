from __future__ import annotations

from pathlib import Path
from typing import List

import pytesseract
from PIL import Image

from ..core.logging import get_logger
from ..core.models import UIAnalysisResult
from ..ocr.ui_element_detector import UIElementDetector

logger = get_logger("parsers.image")


def read_image_file(path: Path, ocr_lang: str = "chi_sim+eng") -> str:
    img = Image.open(str(path))
    try:
        text = pytesseract.image_to_string(img, lang=ocr_lang)
        return text or ""
    except pytesseract.TesseractNotFoundError:
        logger.warning(
            "Tesseract OCR 未安装或不在 PATH 中，无法提取图片文字。"
            "图片文件将跳过 OCR 处理。"
            "请安装: sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim"
        )
        return "[OCR 不可用：Tesseract 未安装，图片文字提取已跳过]"


def analyze_ui_image(
    path: Path,
    ocr_lang: str = "chi_sim+eng",
    min_confidence: float = 30.0,
) -> UIAnalysisResult:
    detector = UIElementDetector(ocr_lang=ocr_lang, min_confidence=min_confidence)
    return detector.analyze_screenshot(path)


def extract_text_from_file(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md", ".markdown"}:
        from .text_parser import read_text_file
        return read_text_file(path)
    if suffix == ".docx":
        from .docx_parser import read_docx_file
        return read_docx_file(path)
    if suffix == ".pdf":
        from .pdf_parser import read_pdf_file
        return read_pdf_file(path)
    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff"}:
        return read_image_file(path)
    if suffix == ".csv":
        from .csv_parser import read_csv_file
        return read_csv_file(path)
    if suffix in {".xlsx", ".xlsm"}:
        from .excel_parser import read_excel_file
        return read_excel_file(path)
    if suffix == ".json":
        from .json_parser import read_json_file
        return read_json_file(path)

    return path.read_text(encoding="utf-8")
