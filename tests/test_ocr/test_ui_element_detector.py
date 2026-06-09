import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import numpy as np

from test_tool.ocr.ui_element_detector import UIElementDetector, BUTTON_KEYWORDS, LABEL_KEYWORDS
from test_tool.core.models import UIElementType, BoundingBox, UIElement


class TestUIElementDetector:
    @pytest.fixture
    def detector(self):
        return UIElementDetector(min_confidence=30.0)

    def test_button_keyword_detection_chinese(self, detector):
        assert detector._determine_element_type("提交") == UIElementType.BUTTON
        assert detector._determine_element_type("保存") == UIElementType.BUTTON
        assert detector._determine_element_type("取消") == UIElementType.BUTTON
        assert detector._determine_element_type("新增") == UIElementType.BUTTON
        assert detector._determine_element_type("删除") == UIElementType.BUTTON

    def test_button_keyword_detection_english(self, detector):
        assert detector._determine_element_type("Submit") == UIElementType.BUTTON
        assert detector._determine_element_type("Save") == UIElementType.BUTTON
        assert detector._determine_element_type("Cancel") == UIElementType.BUTTON

    def test_label_detection_chinese(self, detector):
        assert detector._determine_element_type("名称") == UIElementType.LABEL
        assert detector._determine_element_type("日期") == UIElementType.LABEL
        assert detector._determine_element_type("金额") == UIElementType.LABEL

    def test_label_detection_english(self, detector):
        assert detector._determine_element_type("name") == UIElementType.LABEL
        assert detector._determine_element_type("date") == UIElementType.LABEL

    def test_input_hint_detection(self, detector):
        assert detector._determine_element_type("请输入") == UIElementType.INPUT_FIELD
        assert detector._determine_element_type("请选择") == UIElementType.INPUT_FIELD
        assert detector._determine_element_type("Enter") == UIElementType.INPUT_FIELD

    def test_keyword_extraction(self, detector):
        keywords = detector._extract_keywords("点击提交按钮")
        assert "提交" in keywords

        keywords = detector._extract_keywords("Save and Continue")
        assert "save" in keywords

    def test_is_inside_bbox(self, detector):
        inner = BoundingBox(x=10, y=10, width=20, height=20)
        outer = BoundingBox(x=5, y=5, width=30, height=30)
        assert detector._is_inside(inner, outer) is True

        inner = BoundingBox(x=40, y=40, width=20, height=20)
        assert detector._is_inside(inner, outer) is False

    def test_is_action_button(self, detector):
        button_element = UIElement(
            element_type=UIElementType.BUTTON,
            bounding_box=BoundingBox(x=0, y=0, width=100, height=30),
            text="提交",
            confidence=90.0,
            is_interactive=True,
            keywords=["提交"],
        )
        assert detector._is_action_button(button_element) is True

        label_element = UIElement(
            element_type=UIElementType.LABEL,
            bounding_box=BoundingBox(x=0, y=0, width=100, height=30),
            text="名称",
            confidence=90.0,
            is_interactive=False,
            keywords=[],
        )
        assert detector._is_action_button(label_element) is False

    @patch('test_tool.ocr.ui_element_detector.cv2.imread')
    @patch('test_tool.ocr.tesseract_client.pytesseract.image_to_data')
    @patch('test_tool.ocr.ui_element_detector.Image.open')
    def test_analyze_screenshot_mock(
        self, mock_image_open, mock_ocr, mock_imread, detector, tmp_path
    ):
        mock_imread.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
        mock_image_open.return_value = MagicMock()

        mock_ocr.return_value = {
            'text': ['Submit', '', 'Name', '', 'Save'],
            'conf': [90, -1, 85, -1, 88],
            'left': [100, 0, 50, 0, 200],
            'top': [50, 0, 100, 0, 150],
            'width': [80, 0, 60, 0, 80],
            'height': [30, 0, 25, 0, 30],
            'block_num': [1, 0, 2, 0, 3],
            'line_num': [1, 0, 1, 0, 1],
            'word_num': [1, 0, 1, 0, 1],
        }

        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake image")

        result = detector.analyze_screenshot(img_path)

        assert len(result.elements) >= 1
        assert result.full_text != ""
        button_elements = [e for e in result.elements if e.element_type == UIElementType.BUTTON]
        assert len(button_elements) >= 1


class TestButtonKeywords:
    def test_chinese_keywords_present(self):
        chinese_buttons = ["提交", "保存", "取消", "确认", "删除", "新增", "编辑", "查询"]
        for kw in chinese_buttons:
            assert kw in BUTTON_KEYWORDS

    def test_english_keywords_present(self):
        english_buttons = ["submit", "save", "cancel", "confirm", "delete", "add", "edit"]
        for kw in english_buttons:
            assert kw in BUTTON_KEYWORDS


class TestLabelKeywords:
    def test_chinese_keywords_present(self):
        chinese_labels = ["名称", "编码", "类型", "状态", "日期", "金额"]
        for kw in chinese_labels:
            assert kw in LABEL_KEYWORDS

    def test_english_keywords_present(self):
        english_labels = ["name", "code", "type", "status", "date", "amount"]
        for kw in english_labels:
            assert kw in LABEL_KEYWORDS