from __future__ import annotations

from pathlib import Path
from typing import List

import pytesseract
from PIL import Image

from ..core.models import OCRResult, BoundingBox


class TesseractClient:
    def __init__(
        self,
        lang: str = "chi_sim+eng",
        min_confidence: float = 30.0,
    ):
        self.lang = lang
        self.min_confidence = min_confidence

    def extract_text(self, image_path: Path) -> str:
        img = Image.open(str(image_path))
        return pytesseract.image_to_string(img, lang=self.lang) or ""

    def extract_with_boxes(self, image_path: Path) -> List[OCRResult]:
        img = Image.open(str(image_path))
        data = pytesseract.image_to_data(
            img,
            lang=self.lang,
            output_type=pytesseract.Output.DICT,
        )

        results: List[OCRResult] = []
        n_boxes = len(data["text"])

        for i in range(n_boxes):
            text = data["text"][i].strip()
            if not text:
                continue

            conf = float(data["conf"][i])
            if conf < self.min_confidence:
                continue

            bbox = BoundingBox(
                x=data["left"][i],
                y=data["top"][i],
                width=data["width"][i],
                height=data["height"][i],
            )

            results.append(OCRResult(
                text=text,
                confidence=conf,
                bounding_box=bbox,
                block_num=data["block_num"][i],
                line_num=data["line_num"][i],
                word_num=data["word_num"][i],
            ))

        return results