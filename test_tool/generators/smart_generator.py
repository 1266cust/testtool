from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from ..llm.client import LLMClient
from ..llm.prompts import PromptManager
from ..core.models import TestCase, RequirementSection
from ..core.config import GenerationConfig
from ..core.logging import get_logger
from .test_point_analyzer import TestPoint, ModuleAnalysis

logger = get_logger("generators.smart_generator")


@dataclass
class GenerationContext:
    """生成上下文"""
    module_name: str
    test_point: TestPoint
    requirement_context: str
    system_config: GenerationConfig
    ui_context: Optional[str] = None
    knowledge_context: str = ""  # 知识库上下文


class SmartCaseGenerator:
    """智能测试用例生成器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self.prompt_manager = PromptManager()
        self._knowledge_service = None

    def _get_knowledge_service(self):
        """获取知识库服务（延迟加载）"""
        if self._knowledge_service is None:
            try:
                from ..knowledge.service import get_knowledge_service
                self._knowledge_service = get_knowledge_service()
            except ImportError:
                logger.warning("Knowledge service not available")
                self._knowledge_service = None
        return self._knowledge_service

    def generate_for_test_point(
        self,
        context: GenerationContext,
    ) -> List[TestCase]:
        """为单个测试点生成用例"""

        dimensions_str = ", ".join(context.test_point.dimensions)

        system_prompt, user_prompt = self.prompt_manager.build_prompt(
            "generate_test_cases",
            module_name=context.module_name,
            test_point=context.test_point.point_name,
            dimensions=dimensions_str,
            requirement_context=context.requirement_context,
            knowledge_context=context.knowledge_context,
            system_name=context.system_config.system_name,
            admin_user=context.system_config.admin_user,
            normal_user=context.system_config.normal_user,
        )

        logger.info(f"Generating cases for: {context.test_point.point_name}")

        try:
            result = self.llm.generate_json(user_prompt, system_prompt)
            cases = self._parse_cases(result, context)
            logger.info(f"Generated {len(cases)} cases for test point")
            return cases
        except Exception as e:
            logger.error(f"Failed to generate cases: {e}")
            return self._fallback_case(context)

    def generate_for_all_points(
        self,
        test_points: List[TestPoint],
        sections: List[RequirementSection],
        cfg: GenerationConfig,
        module_analyses: Optional[Dict[str, ModuleAnalysis]] = None,
        project_id: str = "",
    ) -> List[TestCase]:
        """为所有测试点生成用例"""
        all_cases: List[TestCase] = []
        case_index = 1

        section_map = {s.title: s for s in sections}
        module_analyses = module_analyses or {}

        # 获取知识库服务
        knowledge_service = self._get_knowledge_service()

        for point in test_points:
            related_section = self._find_related_section(point, section_map)
            requirement_context = ""
            if related_section:
                requirement_context = "\n".join(related_section.content)

            # 检索知识库上下文
            knowledge_context = ""
            if knowledge_service and project_id:
                try:
                    # 使用测试点名称和需求上下文检索相关文档
                    search_query = f"{point.point_name} {requirement_context[:200]}"
                    knowledge_context = knowledge_service.get_project_context(
                        project_id=project_id,
                        requirement_text=search_query,
                        top_k=3,
                    )
                    if knowledge_context:
                        logger.info(f"Retrieved knowledge context for: {point.point_name}")
                except Exception as e:
                    logger.warning(f"Failed to retrieve knowledge: {e}")

            context = GenerationContext(
                module_name=point.module_name,
                test_point=point,
                requirement_context=requirement_context,
                system_config=cfg,
                knowledge_context=knowledge_context,
            )

            cases = self.generate_for_test_point(context)

            for case in cases:
                case.case_id = f"TC-{case_index:06d}"
                case_index += 1
                all_cases.append(case)

        deduplicated = self._remove_duplicates(all_cases)

        logger.info(f"Total cases after deduplication: {len(deduplicated)}")
        return deduplicated

    def _parse_cases(
        self,
        result: Dict[str, Any],
        context: GenerationContext
    ) -> List[TestCase]:
        """解析LLM返回的用例"""
        cases: List[TestCase] = []

        raw_cases = result.get("cases", [])
        for raw in raw_cases:
            preconditions_list = raw.get("preconditions", [])
            steps_list = raw.get("steps", raw.get("test_process", []))
            expected_result_list = raw.get("expected_result", [])

            preconditions = "\n".join(
                f"{i+1}. {p}" for i, p in enumerate(preconditions_list)
            ) if preconditions_list else "1. 系统功能模块已部署完成。"

            steps = "\n".join(
                f"{i+1}. {step}" for i, step in enumerate(steps_list)
            ) if steps_list else "1. 进入功能页面。"

            expected_result = "\n".join(expected_result_list) if expected_result_list else "操作成功完成。"

            case = TestCase(
                case_id="TEMP",
                module=context.module_name,
                name=raw.get("case_name", f"{context.test_point.point_name}测试"),
                acceptance_purpose=raw.get("acceptance_purpose", f"验证{context.test_point.point_name}功能正确。"),
                preconditions=preconditions,
                steps=steps,
                expected_result=expected_result,
                case_type=raw.get("case_type", "功能测试"),
                priority=raw.get("priority", context.test_point.priority),
            )
            cases.append(case)

        return cases

    def _fallback_case(self, context: GenerationContext) -> List[TestCase]:
        """备用用例生成"""
        case = TestCase(
            case_id="TEMP",
            module=context.module_name,
            name=f"{context.test_point.point_name} - 正常操作",
            acceptance_purpose=f"验证{context.test_point.point_name}功能正确。",
            preconditions="1. 系统功能模块已部署完成。\n2. 测试账号已准备。",
            steps=f"1. 进入【{context.module_name}】页面。\n2. 执行{context.test_point.point_name}操作。\n3. 观察操作结果。",
            expected_result="操作成功完成，提示正确。",
            case_type="功能测试",
            priority=context.test_point.priority,
        )
        return [case]

    def _find_related_section(
        self,
        point: TestPoint,
        section_map: Dict[str, RequirementSection]
    ) -> Optional[RequirementSection]:
        """查找关联章节"""
        if point.related_requirement in section_map:
            return section_map[point.related_requirement]

        for title, section in section_map.items():
            if point.point_name in title or title in point.point_name:
                return section

        if point.module_name in section_map:
            return section_map[point.module_name]

        return None

    def _remove_duplicates(self, cases: List[TestCase]) -> List[TestCase]:
        """去除重复用例"""
        seen_signatures = set()
        unique: List[TestCase] = []

        for case in cases:
            process_preview = case.steps[:100] if case.steps else ""
            signature = f"{case.module}:{case.name}:{process_preview}"
            normalized = signature.lower().strip()

            if normalized not in seen_signatures:
                seen_signatures.add(normalized)
                unique.append(case)

        return unique