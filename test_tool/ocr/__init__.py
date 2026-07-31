from __future__ import annotations

import shutil

from .tesseract_client import TesseractClient
from .ui_element_detector import UIElementDetector
from .multimodal_vision import MultimodalVisionAnalyzer

HAS_TESSERACT = shutil.which("tesseract") is not None

__all__ = [
    "TesseractClient",
    "UIElementDetector",
    "MultimodalVisionAnalyzer",
    "HAS_TESSERACT",
]
