from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

from ..core.models import (
    UIVisionElement,
    UIInteractionStep,
    UIInteractionFlow,
    UIPageFlow,
    VisionAnalysisResult,
)
from ..core.logging import get_logger
from ..generators.test_point_analyzer import TestPoint

logger = get_logger("ocr.multimodal_vision")


SYSTEM_PROMPT_VISION_ANALYSIS = """你是一名专业的UI/UX分析专家，擅长通过视觉识别页面元素并生成完整的UI交互操作序列。

你的能力：
1. 识别原型图/UI截图中的所有页面元素（按钮、输入框、下拉框、复选框、单选框、链接、标签、图标、表格、标签页、弹窗、提示框、滑块、开关、日期选择器、文件上传、文本域等）
2. 分析元素之间的布局关系和交互逻辑
3. 推断合理的用户操作流程
4. 识别页面之间的跳转关系
5. 为每个操作提供精确的 Playwright 定位策略

分析原则：
- 不仅要识别可见元素，还要推断隐含的交互逻辑（如必填校验、表单联动等）
- 操作序列应覆盖典型用户操作流程，包括正常流程和异常流程
- 为填写类操作提供合理的测试数据
- 考虑元素之间的依赖关系（如先选择下拉框才能填写后续字段）

请严格按照以下JSON格式输出分析结果：
```json
{
  "page_description": "页面整体描述",
  "page_type": "表单页/列表页/详情页/仪表盘/登录页/其他",
  "elements": [
    {
      "element_type": "button/input/dropdown/checkbox/radio/link/label/icon/table/tab/modal/tooltip/slider/switch/date_picker/file_upload/text_area/unknown",
      "text": "元素显示文本",
      "description": "元素功能描述",
      "is_interactive": true,
      "locator_strategy": "get_by_role/get_by_label/get_by_text/get_by_placeholder/get_by_test_id",
      "locator_value": "定位值",
      "suggested_action": "click/fill/select/hover/scroll/check/uncheck",
      "suggested_input": "建议输入值（仅fill/select时）",
      "position": "顶部/中部/底部/左侧/右侧",
      "confidence": 0.95
    }
  ],
  "interaction_flows": [
    {
      "flow_name": "流程名称",
      "description": "流程描述",
      "pages": ["涉及的页面"],
      "steps": [
        {
          "step_number": 1,
          "action": "click/fill/select/hover/scroll/check/uncheck/press_key/wait/assert",
          "target": "目标元素名称",
          "target_type": "button/input/dropdown/checkbox/radio/link/tab",
          "locator_strategy": "get_by_role/get_by_label/get_by_text/get_by_placeholder/get_by_test_id",
          "locator_value": "定位值",
          "input_value": "输入值",
          "description": "操作描述"
        }
      ]
    }
  ],
  "page_flows": [
    {
      "from_page": "来源页面",
      "to_page": "目标页面",
      "trigger_element": "触发跳转的元素",
      "trigger_action": "触发动作",
      "condition": "触发条件（如有）"
    }
  ]
}
```"""


USER_PROMPT_VISION_ANALYSIS = """请分析以下UI截图，识别页面元素并生成完整的UI交互操作序列。

{additional_context}

请仔细观察截图中的所有元素，包括：
1. 顶部导航栏/菜单
2. 表单区域的所有输入项（注意必填标记、占位文本、默认值）
3. 操作按钮（提交、取消、重置等）
4. 列表/表格区域（列头、操作列、分页）
5. 弹窗/对话框
6. 侧边栏/抽屉
7. 标签页/折叠面板
8. 任何可交互的元素

请严格按照JSON格式输出。"""


SYSTEM_PROMPT_VISION_TEST_POINTS = """你是一名专业的测试分析专家，擅长通过视觉识别原型图/UI截图中的页面元素，并从中提取测试点。

你的能力：
1. 识别UI截图中的所有页面元素和交互逻辑
2. 根据页面元素和布局推断业务功能
3. 从页面功能中提取可测试的测试点
4. 为每个测试点设计覆盖维度和优先级

分析原则：
- 从页面整体出发，识别页面承载的业务功能
- 每个可交互元素至少对应一个测试点
- 表单类页面要考虑必填校验、格式校验、边界值等
- 列表类页面要考虑查询、分页、排序、操作按钮等
- 既要覆盖正常流程，也要考虑异常和边界场景
- 考虑页面之间的跳转和数据联动

请严格按照以下JSON格式输出测试点：
```json
{
  "page_description": "页面整体描述",
  "page_type": "表单页/列表页/详情页/仪表盘/登录页/其他",
  "test_points": [
    {
      "point_name": "测试点名称",
      "category": "功能类型（新增创建/编辑修改/删除禁用/查询筛选/导入导出/登录认证/权限角色/支付资金/流程审批/数据校验/界面交互/其他）",
      "dimensions": ["正常场景", "异常输入", "边界值测试"],
      "priority": "P0/P1/P2",
      "related_requirement": "关联的页面功能描述",
      "test_coverage_suggestions": ["建议覆盖的测试场景1", "建议覆盖的测试场景2"],
      "ui_elements_context": "该测试点涉及的UI元素描述"
    }
  ],
  "module_analysis": {
    "core_functions": ["核心功能列表"],
    "secondary_functions": ["辅助功能列表"],
    "risk_areas": ["风险关注点"]
  }
}
```"""


USER_PROMPT_VISION_TEST_POINTS = """请分析以下UI截图，识别页面元素并提取测试点。

{additional_context}

请仔细观察截图，从以下维度提取测试点：
1. 每个可交互元素（按钮、输入框、下拉框等）对应的测试点
2. 表单校验相关测试点（必填、格式、长度、边界值）
3. 页面交互流程测试点（操作顺序、联动效果、跳转逻辑）
4. 数据展示相关测试点（列表、表格、分页、排序）
5. 异常场景测试点（网络异常、重复提交、并发操作）
6. 安全相关测试点（XSS、注入、越权）

请严格按照JSON格式输出。"""


class MultimodalVisionAnalyzer:
    """多模态大模型UI截图分析器"""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def analyze_screenshot(
        self,
        image_path: Path,
        additional_context: str = "",
    ) -> VisionAnalysisResult:
        """分析UI截图，识别页面元素和交互流程"""
        if not self.llm_client:
            logger.warning("No LLM client provided, returning empty result")
            return VisionAnalysisResult(
                page_description="",
                page_type="",
                elements=[],
                interaction_sequences=[],
                page_flows=[],
            )

        if not image_path.exists():
            logger.error("Image file not found: " + str(image_path))
            return VisionAnalysisResult(
                page_description="",
                page_type="",
                elements=[],
                interaction_sequences=[],
                page_flows=[],
            )

        context_section = ""
        if additional_context:
            context_section = f"【补充说明】:\n{additional_context}\n"

        user_prompt = USER_PROMPT_VISION_ANALYSIS.format(
            additional_context=context_section
        )

        logger.info("Sending image to vision LLM for analysis: " + str(image_path))

        try:
            raw_response = self.llm_client.generate_with_images(
                prompt=user_prompt,
                image_paths=[str(image_path)],
                system_prompt=SYSTEM_PROMPT_VISION_ANALYSIS,
            )
        except Exception as exc:
            logger.error("Vision LLM call failed: " + str(exc))
            return VisionAnalysisResult(
                page_description="",
                page_type="",
                elements=[],
                interaction_sequences=[],
                page_flows=[],
            )

        result = self._parse_vision_response(raw_response)
        result.raw_response = raw_response

        logger.info(
            "Vision analysis complete: "
            + str(len(result.elements)) + " elements, "
            + str(len(result.interaction_sequences)) + " flows, "
            + str(len(result.page_flows)) + " page transitions"
        )

        return result

    def analyze_multiple_screenshots(
        self,
        image_paths: List[Path],
        additional_context: str = "",
    ) -> VisionAnalysisResult:
        """分析多张UI截图（如多页面原型图），生成跨页面交互流程"""
        if not self.llm_client:
            return VisionAnalysisResult(
                page_description="",
                page_type="",
                elements=[],
                interaction_sequences=[],
                page_flows=[],
            )

        valid_paths = [p for p in image_paths if p.exists()]
        if not valid_paths:
            return VisionAnalysisResult(
                page_description="",
                page_type="",
                elements=[],
                interaction_sequences=[],
                page_flows=[],
            )

        context_section = ""
        if additional_context:
            context_section = f"【补充说明】:\n{additional_context}\n"
        context_section += f"共提供了 {len(valid_paths)} 张截图，请分析它们之间的页面流转关系。\n"

        user_prompt = USER_PROMPT_VISION_ANALYSIS.format(
            additional_context=context_section
        )

        logger.info(
            "Sending " + str(len(valid_paths)) + " images to vision LLM"
        )

        try:
            raw_response = self.llm_client.generate_with_images(
                prompt=user_prompt,
                image_paths=[str(p) for p in valid_paths],
                system_prompt=SYSTEM_PROMPT_VISION_ANALYSIS,
            )
        except Exception as exc:
            logger.error("Vision LLM call failed: " + str(exc))
            return VisionAnalysisResult(
                page_description="",
                page_type="",
                elements=[],
                interaction_sequences=[],
                page_flows=[],
            )

        result = self._parse_vision_response(raw_response)
        result.raw_response = raw_response

        return result

    def extract_test_points(
        self,
        image_path: Path,
        module_name: str = "",
        additional_context: str = "",
    ) -> List[TestPoint]:
        """从UI截图中提取测试点，直接用于用例生成"""
        if not self.llm_client:
            logger.warning("No LLM client provided for test point extraction")
            return []

        if not image_path.exists():
            logger.error("Image file not found: " + str(image_path))
            return []

        context_section = ""
        if module_name:
            context_section += f"【页面/模块名称】: {module_name}\n"
        if additional_context:
            context_section += f"【补充说明】:\n{additional_context}\n"

        user_prompt = USER_PROMPT_VISION_TEST_POINTS.format(
            additional_context=context_section
        )

        logger.info("Sending image to vision LLM for test point extraction: " + str(image_path))

        try:
            raw_response = self.llm_client.generate_with_images(
                prompt=user_prompt,
                image_paths=[str(image_path)],
                system_prompt=SYSTEM_PROMPT_VISION_TEST_POINTS,
            )
        except Exception as exc:
            logger.error("Vision test point extraction failed: " + str(exc))
            return []

        test_points = self._parse_test_points_response(raw_response, module_name)

        logger.info(f"Extracted {len(test_points)} test points from vision analysis")

        return test_points

    def extract_test_points_from_multiple(
        self,
        image_paths: List[Path],
        module_name: str = "",
        additional_context: str = "",
    ) -> List[TestPoint]:
        """从多张UI截图中提取测试点"""
        if not self.llm_client:
            return []

        valid_paths = [p for p in image_paths if p.exists()]
        if not valid_paths:
            return []

        if len(valid_paths) == 1:
            return self.extract_test_points(valid_paths[0], module_name, additional_context)

        context_section = ""
        if module_name:
            context_section += f"【页面/模块名称】: {module_name}\n"
        if additional_context:
            context_section += f"【补充说明】:\n{additional_context}\n"
        context_section += f"共提供了 {len(valid_paths)} 张截图，请综合分析所有截图中的测试点。\n"

        user_prompt = USER_PROMPT_VISION_TEST_POINTS.format(
            additional_context=context_section
        )

        logger.info(f"Sending {len(valid_paths)} images to vision LLM for test point extraction")

        try:
            raw_response = self.llm_client.generate_with_images(
                prompt=user_prompt,
                image_paths=[str(p) for p in valid_paths],
                system_prompt=SYSTEM_PROMPT_VISION_TEST_POINTS,
            )
        except Exception as exc:
            logger.error("Vision test point extraction failed: " + str(exc))
            return []

        return self._parse_test_points_response(raw_response, module_name)

    def _parse_vision_response(self, raw: str) -> VisionAnalysisResult:
        """解析多模态大模型返回的JSON结果"""
        json_data = self._extract_json(raw)

        if json_data is None:
            logger.warning("Failed to parse vision response as JSON")
            return VisionAnalysisResult(
                page_description=raw[:200],
                page_type="unknown",
                elements=[],
                interaction_sequences=[],
                page_flows=[],
            )

        page_description = json_data.get("page_description", "")
        page_type = json_data.get("page_type", "unknown")

        elements = []
        for elem_data in json_data.get("elements", []):
            elements.append(UIVisionElement(
                element_type=elem_data.get("element_type", "unknown"),
                text=elem_data.get("text", ""),
                description=elem_data.get("description", ""),
                is_interactive=elem_data.get("is_interactive", False),
                locator_strategy=elem_data.get("locator_strategy", ""),
                locator_value=elem_data.get("locator_value", ""),
                suggested_action=elem_data.get("suggested_action", ""),
                suggested_input=elem_data.get("suggested_input", ""),
                position=elem_data.get("position"),
                confidence=elem_data.get("confidence", 0.0),
            ))

        interaction_flows = []
        for flow_data in json_data.get("interaction_flows", []):
            steps = []
            for step_data in flow_data.get("steps", []):
                steps.append(UIInteractionStep(
                    step_number=step_data.get("step_number", 0),
                    action=step_data.get("action", ""),
                    target=step_data.get("target", ""),
                    target_type=step_data.get("target_type", ""),
                    locator_strategy=step_data.get("locator_strategy", ""),
                    locator_value=step_data.get("locator_value", ""),
                    input_value=step_data.get("input_value", ""),
                    description=step_data.get("description", ""),
                ))
            interaction_flows.append(UIInteractionFlow(
                flow_name=flow_data.get("flow_name", ""),
                description=flow_data.get("description", ""),
                pages=flow_data.get("pages", []),
                elements=[],
                steps=steps,
                page_flows=[],
            ))

        page_flows = []
        for flow_data in json_data.get("page_flows", []):
            page_flows.append(UIPageFlow(
                from_page=flow_data.get("from_page", ""),
                to_page=flow_data.get("to_page", ""),
                trigger_element=flow_data.get("trigger_element", ""),
                trigger_action=flow_data.get("trigger_action", ""),
                condition=flow_data.get("condition", ""),
            ))

        return VisionAnalysisResult(
            page_description=page_description,
            page_type=page_type,
            elements=elements,
            interaction_sequences=interaction_flows,
            page_flows=page_flows,
        )

    def _parse_test_points_response(
        self,
        raw: str,
        module_name: str = "",
    ) -> List[TestPoint]:
        """解析多模态大模型返回的测试点"""
        json_data = self._extract_json(raw)

        if json_data is None:
            logger.warning("Failed to parse test points response as JSON")
            return self._fallback_test_points_from_vision(raw, module_name)

        test_points: List[TestPoint] = []

        for i, raw_point in enumerate(json_data.get("test_points", [])):
            point = TestPoint(
                point_id=f"TP-VISION-{i+1:04d}",
                point_name=raw_point.get("point_name", ""),
                category=raw_point.get("category", "功能测试"),
                dimensions=raw_point.get("dimensions", ["正常场景"]),
                priority=raw_point.get("priority", "P1"),
                related_requirement=raw_point.get("related_requirement", ""),
                test_coverage_suggestions=raw_point.get("test_coverage_suggestions", []),
                ui_elements_context=raw_point.get("ui_elements_context", ""),
                module_name=module_name,
            )
            test_points.append(point)

        return test_points

    def _fallback_test_points_from_vision(
        self,
        raw: str,
        module_name: str = "",
    ) -> List[TestPoint]:
        """从视觉分析原始响应中提取基本测试点（降级方案）"""
        points: List[TestPoint] = []

        lines = raw.strip().split("\n")
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            cleaned = re.sub(r"^[\d\.\-\*]+\s*", "", line)
            if len(cleaned) < 4:
                continue
            points.append(TestPoint(
                point_id=f"TP-VISION-FALLBACK-{i+1:04d}",
                point_name=cleaned[:80],
                category="功能测试",
                dimensions=["正常场景", "异常输入"],
                priority="P1",
                related_requirement=module_name,
                module_name=module_name,
            ))

        return points[:30]

    def _extract_json(self, raw: str) -> Optional[dict]:
        """从响应中提取JSON"""
        json_match = re.search(r"```json\s*\n(.*?)```", raw, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            pass

        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end])
            except json.JSONDecodeError:
                pass

        return None
