from __future__ import annotations

from pathlib import Path
from typing import List, Callable, Optional

import pdfplumber
import pytesseract
from pdf2image import convert_from_path

from ..core.logging import get_logger

logger = get_logger("parsers.pdf")


class PDFParseProgress:
    def __init__(
        self,
        total_pages: int,
        processed_pages: int,
        current_stage: str,
        error: Optional[str] = None,
    ):
        self.total_pages = total_pages
        self.processed_pages = processed_pages
        self.current_stage = current_stage
        self.error = error


def read_pdf_file(
    path: Path,
    ocr_lang: str = "chi_sim+eng",
    progress_callback: Optional[Callable[[PDFParseProgress], None]] = None,
) -> str:
    text_parts: List[str] = []

    with pdfplumber.open(str(path)) as pdf:
        total_pages = len(pdf.pages)
        if progress_callback:
            progress_callback(PDFParseProgress(
                total_pages=total_pages,
                processed_pages=0,
                current_stage="text_extraction",
            ))

        for i, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_parts.append(page_text)
            if progress_callback:
                progress_callback(PDFParseProgress(
                    total_pages=total_pages,
                    processed_pages=i + 1,
                    current_stage="text_extraction",
                ))

    text = "\n".join(text_parts).strip()
    if text:
        if progress_callback:
            progress_callback(PDFParseProgress(
                total_pages=total_pages,
                processed_pages=total_pages,
                current_stage="complete",
            ))
        return text

    logger.info(f"No text extracted from {path}, falling back to OCR")
    return _ocr_pdf(path, ocr_lang, progress_callback)


def _ocr_pdf(
    path: Path,
    ocr_lang: str,
    progress_callback: Optional[Callable[[PDFParseProgress], None]] = None,
) -> str:
    images = convert_from_path(str(path))
    total_pages = len(images)

    if progress_callback:
        progress_callback(PDFParseProgress(
            total_pages=total_pages,
            processed_pages=0,
            current_stage="ocr",
        ))

    ocr_parts: List[str] = []
    for i, img in enumerate(images):
        ocr_text = pytesseract.image_to_string(img, lang=ocr_lang)
        if ocr_text.strip():
            ocr_parts.append(ocr_text)
        if progress_callback:
            progress_callback(PDFParseProgress(
                total_pages=total_pages,
                processed_pages=i + 1,
                current_stage="ocr",
            ))

    if progress_callback:
        progress_callback(PDFParseProgress(
            total_pages=total_pages,
            processed_pages=total_pages,
            current_stage="complete",
        ))

    return "\n".join(ocr_parts)