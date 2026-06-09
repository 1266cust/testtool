from __future__ import annotations

from pathlib import Path

from .text_parser import read_text_file
from .docx_parser import read_docx_file
from .csv_parser import read_csv_file
from .excel_parser import read_excel_file
from .json_parser import read_json_file
from .pdf_parser import read_pdf_file
from .image_parser import read_image_file, extract_text_from_file

__all__ = [
    "read_text_file",
    "read_docx_file",
    "read_csv_file",
    "read_excel_file",
    "read_json_file",
    "read_pdf_file",
    "read_image_file",
    "extract_text_from_file",
]