from __future__ import annotations

import shutil

from .tesseract_client import TesseractClient
from .ui_element_detector import UIElementDetector

# 检测系统是否安装了 Tesseract OCR 二进制程序
HAS_TESSERACT = shutil.which("tesseract") is not None

__all__ = [
    "TesseractClient",
    "UIElementDetector",
    "HAS_TESSERACT",
]
