from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from ..llm.client import LLMClient
from ..llm.prompts import PromptManager
from ..core.models import RequirementSection, UIAnalysisResult
from ..core.logging import get_logger

logger = get_logger("generators.test_point_analyzer")


@dataclass
class TestPoint:
    """智能拆分的测试点"""
    point_id: str
    point_name: str
    category: str
    dimensions: List[str]
    priority: str
    related_requirement: str
    test_coverage_suggestions: List[str] = field(default_factory=list)

    ui_elements_context: Optional[str] = None
    data_requirements: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)

    module_name: str = ""


@dataclass
class ModuleAnalysis:
    """模块分析结果"""
    module_name: str
    core_functions: List[str] = field(default_factory=list)
    secondary_functions: List[str] = field(default_factory=list)
    risk_areas: List[str] = field(default_factory=list)


class TestPointAnalyzer:
    """测试点智能分析器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self.prompt_manager = PromptManager()

    def analyze_section(
        self,
        section: RequirementSection,
        ui_result: Optional[UIAnalysisResult] = None,
    ) -> tuple[List[TestPoint], ModuleAnalysis]:
        """分析单个需求章节，拆分测试点"""

        ui_elements_info = self.prompt_manager.build_ui_elements_info(ui_result)

        system_prompt, user_prompt = self.prompt_manager.build_prompt(
            "analyze_test_points",
            module_name=section.title,
            requirement_content="\n".join(section.content),
            ui_elements_info=ui_elements_info,
        )

        logger.info(f"Analyzing test points for module: {section.title}")

        try:
            result = self.llm.generate_json(user_prompt, system_prompt)
            test_points, module_analysis = self._parse_result(result, section.title)
            logger.info(f"Generated {len(test_points)} test points")
            return test_points, module_analysis
        except Exception as e:
            logger.error(f"Failed to analyze test points: {e}")
            return self._fallback_analysis(section), ModuleAnalysis(module_name=section.title)

    def analyze_all_sections(
        self,
        sections: List[RequirementSection],
        ui_results: Optional[Dict[str, UIAnalysisResult]] = None,
    ) -> tuple[List[TestPoint], Dict[str, ModuleAnalysis]]:
        """分析所有章节"""
        all_points: List[TestPoint] = []
        module_analyses: Dict[str, ModuleAnalysis] = {}
        point_index = 1

        ui_results = ui_results or {}

        for section in sections:
            if section.level > 3:
                continue

            ui_result = ui_results.get(section.title)
            points, analysis = self.analyze_section(section, ui_result)

            for point in points:
                point.point_id = f"TP-{point_index:04d}"
                point.module_name = section.title
                point_index += 1
                all_points.append(point)

            module_analyses[section.title] = analysis

        deduplicated = self._deduplicate_points(all_points)

        logger.info(f"Total test points after deduplication: {len(deduplicated)}")
        return deduplicated, module_analyses

    def _parse_result(
        self,
        result: Dict[str, Any],
        module_name: str
    ) -> tuple[List[TestPoint], ModuleAnalysis]:
        """解析LLM返回的结果"""
        points: List[TestPoint] = []

        raw_points = result.get("test_points", [])
        for i, raw in enumerate(raw_points):
            point = TestPoint(
                point_id=f"TP-TEMP-{i}",
                point_name=raw.get("point_name", ""),
                category=raw.get("category", "功能测试"),
                dimensions=raw.get("dimensions", ["正常场景"]),
                priority=raw.get("priority", "P1"),
                related_requirement=raw.get("related_requirement", ""),
                test_coverage_suggestions=raw.get("test_coverage_suggestions", []),
                module_name=module_name,
            )
            points.append(point)

        raw_analysis = result.get("module_analysis", {})
        module_analysis = ModuleAnalysis(
            module_name=module_name,
            core_functions=raw_analysis.get("core_functions", []),
            secondary_functions=raw_analysis.get("secondary_functions", []),
            risk_areas=raw_analysis.get("risk_areas", []),
        )

        return points, module_analysis

    def _fallback_analysis(
        self,
        section: RequirementSection
    ) -> List[TestPoint]:
        """备用分析：当LLM不可用时使用简单拆分"""
        content_text = "\n".join(section.content)

        points: List[TestPoint] = []
        point_index = 1

        keywords = [
            ("新增", "新增创建"),
            ("编辑", "编辑修改"),
            ("删除", "删除禁用"),
            ("查询", "查询筛选"),
            ("导入", "导入导出"),
            ("导出", "导入导出"),
            ("登录", "登录认证"),
            ("权限", "权限角色"),
            ("审批", "流程审批"),
        ]

        for kw, category in keywords:
            if kw in content_text or kw in section.title:
                point = TestPoint(
                    point_id=f"TP-FALLBACK-{point_index}",
                    point_name=f"{section.title} - {kw}功能",
                    category=category,
                    dimensions=["正常场景", "异常输入", "边界值测试"],
                    priority="P1",
                    related_requirement=section.title,
                    test_coverage_suggestions=[],
                    module_name=section.title,
                )
                points.append(point)
                point_index += 1

        if not points:
            point = TestPoint(
                point_id="TP-FALLBACK-001",
                point_name=f"{section.title} 功能",
                category="功能测试",
                dimensions=["正常场景", "异常输入"],
                priority="P1",
                related_requirement=section.title,
                test_coverage_suggestions=[],
                module_name=section.title,
            )
            points.append(point)

        return points

    def _deduplicate_points(self, points: List[TestPoint]) -> List[TestPoint]:
        """去除重复的测试点"""
        seen_signatures = set()
        unique: List[TestPoint] = []

        for point in points:
            signature = f"{point.module_name}:{point.point_name}:{point.category}"
            normalized = signature.lower().strip()

            if normalized not in seen_signatures:
                seen_signatures.add(normalized)
                unique.append(point)

        return unique