from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from test_tool.core.models import (
    UIVisionElement,
    UIInteractionStep,
    UIInteractionFlow,
    UIPageFlow,
    VisionAnalysisResult,
)
from test_tool.ocr.multimodal_vision import MultimodalVisionAnalyzer


class TestUIVisionElement:
    def test_to_dict(self):
        elem = UIVisionElement(
            element_type="button",
            text="提交",
            description="提交按钮",
            is_interactive=True,
            locator_strategy="get_by_role",
            locator_value="button, name='提交'",
            suggested_action="click",
            confidence=0.95,
        )
        d = elem.to_dict()
        assert d["element_type"] == "button"
        assert d["text"] == "提交"
        assert d["is_interactive"] is True
        assert d["confidence"] == 0.95

    def test_to_dict_with_children(self):
        child = UIVisionElement(
            element_type="input",
            text="用户名",
            description="",
            is_interactive=True,
        )
        parent = UIVisionElement(
            element_type="form",
            text="登录表单",
            description="",
            is_interactive=False,
            children=[child],
        )
        d = parent.to_dict()
        assert len(d["children"]) == 1
        assert d["children"][0]["text"] == "用户名"


class TestUIPageFlow:
    def test_to_dict(self):
        flow = UIPageFlow(
            from_page="登录页",
            to_page="首页",
            trigger_element="登录按钮",
            trigger_action="click",
            condition="账号密码正确",
        )
        d = flow.to_dict()
        assert d["from_page"] == "登录页"
        assert d["to_page"] == "首页"
        assert d["condition"] == "账号密码正确"


class TestVisionAnalysisResult:
    def test_to_dict(self):
        elem = UIVisionElement(
            element_type="button",
            text="提交",
            description="",
            is_interactive=True,
        )
        step = UIInteractionStep(
            step_number=1,
            action="click",
            target="提交",
            target_type="button",
            locator_strategy="get_by_role",
            locator_value="button, name='提交'",
        )
        flow = UIInteractionFlow(
            flow_name="提交表单",
            description="填写并提交表单",
            pages=["表单页"],
            elements=[],
            steps=[step],
            page_flows=[],
        )
        page_flow = UIPageFlow(
            from_page="表单页",
            to_page="成功页",
            trigger_element="提交",
            trigger_action="click",
        )
        result = VisionAnalysisResult(
            page_description="测试页面",
            page_type="表单页",
            elements=[elem],
            interaction_sequences=[flow],
            page_flows=[page_flow],
        )
        d = result.to_dict()
        assert d["page_description"] == "测试页面"
        assert len(d["elements"]) == 1
        assert len(d["interaction_sequences"]) == 1
        assert len(d["page_flows"]) == 1


class TestMultimodalVisionAnalyzer:
    def test_analyze_screenshot_no_llm_client(self):
        analyzer = MultimodalVisionAnalyzer(llm_client=None)
        result = analyzer.analyze_screenshot(Path("/nonexistent.png"))
        assert result.page_description == ""
        assert result.elements == []

    def test_analyze_screenshot_file_not_found(self):
        mock_client = MagicMock()
        analyzer = MultimodalVisionAnalyzer(llm_client=mock_client)
        result = analyzer.analyze_screenshot(Path("/nonexistent.png"))
        assert result.elements == []

    def test_analyze_screenshot_success(self, tmp_path):
        mock_client = MagicMock()
        mock_client.generate_with_images.return_value = json.dumps({
            "page_description": "登录页面",
            "page_type": "登录页",
            "elements": [
                {
                    "element_type": "input",
                    "text": "用户名",
                    "description": "用户名输入框",
                    "is_interactive": True,
                    "locator_strategy": "get_by_label",
                    "locator_value": "用户名",
                    "suggested_action": "fill",
                    "suggested_input": "admin",
                    "confidence": 0.95,
                },
                {
                    "element_type": "button",
                    "text": "登录",
                    "description": "登录按钮",
                    "is_interactive": True,
                    "locator_strategy": "get_by_role",
                    "locator_value": "button, name='登录'",
                    "suggested_action": "click",
                    "confidence": 0.99,
                },
            ],
            "interaction_flows": [
                {
                    "flow_name": "用户登录",
                    "description": "输入用户名密码并登录",
                    "pages": ["登录页"],
                    "steps": [
                        {
                            "step_number": 1,
                            "action": "fill",
                            "target": "用户名",
                            "target_type": "input",
                            "locator_strategy": "get_by_label",
                            "locator_value": "用户名",
                            "input_value": "admin",
                            "description": "输入用户名",
                        },
                        {
                            "step_number": 2,
                            "action": "click",
                            "target": "登录",
                            "target_type": "button",
                            "locator_strategy": "get_by_role",
                            "locator_value": "button, name='登录'",
                            "description": "点击登录",
                        },
                    ],
                },
            ],
            "page_flows": [
                {
                    "from_page": "登录页",
                    "to_page": "首页",
                    "trigger_element": "登录",
                    "trigger_action": "click",
                    "condition": "登录成功",
                },
            ],
        })

        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        analyzer = MultimodalVisionAnalyzer(llm_client=mock_client)
        result = analyzer.analyze_screenshot(img_file)

        assert result.page_description == "登录页面"
        assert result.page_type == "登录页"
        assert len(result.elements) == 2
        assert result.elements[0].text == "用户名"
        assert result.elements[1].text == "登录"
        assert len(result.interaction_sequences) == 1
        assert result.interaction_sequences[0].flow_name == "用户登录"
        assert len(result.interaction_sequences[0].steps) == 2
        assert len(result.page_flows) == 1
        assert result.page_flows[0].from_page == "登录页"

    def test_analyze_screenshot_json_in_code_block(self, tmp_path):
        mock_client = MagicMock()
        json_data = {
            "page_description": "测试页",
            "page_type": "表单页",
            "elements": [],
            "interaction_flows": [],
            "page_flows": [],
        }
        mock_client.generate_with_images.return_value = (
            "```json\n" + json.dumps(json_data) + "\n```"
        )

        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        analyzer = MultimodalVisionAnalyzer(llm_client=mock_client)
        result = analyzer.analyze_screenshot(img_file)

        assert result.page_description == "测试页"

    def test_analyze_screenshot_llm_failure(self, tmp_path):
        mock_client = MagicMock()
        mock_client.generate_with_images.side_effect = Exception("API error")

        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        analyzer = MultimodalVisionAnalyzer(llm_client=mock_client)
        result = analyzer.analyze_screenshot(img_file)

        assert result.elements == []

    def test_analyze_multiple_screenshots_no_llm(self):
        analyzer = MultimodalVisionAnalyzer(llm_client=None)
        result = analyzer.analyze_multiple_screenshots([Path("/a.png"), Path("/b.png")])
        assert result.elements == []

    def test_analyze_multiple_screenshots_success(self, tmp_path):
        mock_client = MagicMock()
        mock_client.generate_with_images.return_value = json.dumps({
            "page_description": "多页面流程",
            "page_type": "流程",
            "elements": [
                {
                    "element_type": "button",
                    "text": "下一步",
                    "description": "",
                    "is_interactive": True,
                },
            ],
            "interaction_flows": [],
            "page_flows": [
                {
                    "from_page": "页面1",
                    "to_page": "页面2",
                    "trigger_element": "下一步",
                    "trigger_action": "click",
                },
            ],
        })

        img1 = tmp_path / "page1.png"
        img2 = tmp_path / "page2.png"
        img1.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        img2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        analyzer = MultimodalVisionAnalyzer(llm_client=mock_client)
        result = analyzer.analyze_multiple_screenshots([img1, img2])

        assert result.page_description == "多页面流程"
        assert len(result.page_flows) == 1


class TestMultimodalVisionTestPointExtraction:
    def test_extract_test_points_no_llm(self, tmp_path):
        analyzer = MultimodalVisionAnalyzer(llm_client=None)
        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        result = analyzer.extract_test_points(img)
        assert result == []

    def test_extract_test_points_success(self, tmp_path):
        mock_client = MagicMock()
        mock_client.generate_with_images.return_value = json.dumps({
            "page_description": "登录页面",
            "page_type": "登录页",
            "test_points": [
                {
                    "point_name": "用户名输入校验",
                    "category": "数据校验",
                    "dimensions": ["正常场景", "异常输入", "边界值测试"],
                    "priority": "P0",
                    "related_requirement": "用户名输入框",
                    "test_coverage_suggestions": ["空值校验", "特殊字符校验", "长度限制"],
                    "ui_elements_context": "用户名输入框、密码输入框、登录按钮",
                },
                {
                    "point_name": "登录按钮点击",
                    "category": "登录认证",
                    "dimensions": ["正常场景", "异常场景"],
                    "priority": "P0",
                    "related_requirement": "登录功能",
                    "test_coverage_suggestions": ["正确登录", "错误密码"],
                    "ui_elements_context": "登录按钮",
                },
            ],
            "module_analysis": {
                "core_functions": ["登录认证"],
                "secondary_functions": ["记住密码"],
                "risk_areas": ["暴力破解"],
            },
        })

        img = tmp_path / "login.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        analyzer = MultimodalVisionAnalyzer(llm_client=mock_client)
        result = analyzer.extract_test_points(img, module_name="登录页")

        assert len(result) == 2
        assert result[0].point_name == "用户名输入校验"
        assert result[0].category == "数据校验"
        assert result[0].priority == "P0"
        assert result[0].module_name == "登录页"
        assert result[1].point_name == "登录按钮点击"
        assert result[1].ui_elements_context == "登录按钮"

    def test_extract_test_points_from_multiple(self, tmp_path):
        mock_client = MagicMock()
        mock_client.generate_with_images.return_value = json.dumps({
            "page_description": "多页面流程",
            "page_type": "流程",
            "test_points": [
                {
                    "point_name": "页面跳转测试",
                    "category": "界面交互",
                    "dimensions": ["正常场景"],
                    "priority": "P1",
                    "related_requirement": "页面间跳转",
                },
            ],
            "module_analysis": {
                "core_functions": [],
                "secondary_functions": [],
                "risk_areas": [],
            },
        })

        img1 = tmp_path / "page1.png"
        img2 = tmp_path / "page2.png"
        img1.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        img2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        analyzer = MultimodalVisionAnalyzer(llm_client=mock_client)
        result = analyzer.extract_test_points_from_multiple(
            [img1, img2], module_name="流程"
        )

        assert len(result) == 1
        assert result[0].point_name == "页面跳转测试"

    def test_extract_test_points_llm_failure(self, tmp_path):
        mock_client = MagicMock()
        mock_client.generate_with_images.side_effect = Exception("API error")

        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        analyzer = MultimodalVisionAnalyzer(llm_client=mock_client)
        result = analyzer.extract_test_points(img)

        assert result == []

    def test_extract_test_points_fallback_parse(self, tmp_path):
        mock_client = MagicMock()
        mock_client.generate_with_images.return_value = """
1. 用户名输入校验
2. 密码输入校验
3. 登录按钮点击
4. 验证码校验
"""

        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        analyzer = MultimodalVisionAnalyzer(llm_client=mock_client)
        result = analyzer.extract_test_points(img, module_name="登录页")

        assert len(result) == 4
        assert result[0].point_name == "用户名输入校验"
        assert result[0].module_name == "登录页"
