from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from ..llm.client import LLMClient
from ..llm.prompts import PromptManager
from ..core.models import TestCase, ReviewResult, ReviewIssue, MissingScenario
from ..core.logging import get_logger

logger = get_logger("review.auto_fixer")


@dataclass
class FixedCasesResult:
    """修复后的用例结果"""
    cases: List[TestCase]
    removed_case_ids: List[str]
    merged_case_ids: List[str]
    added_cases: List[TestCase]
    fix_summary: str


class AutoFixer:
    """自动修复器"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client
        self.prompt_manager = PromptManager()

    def apply_fixes(
        self,
        cases: List[TestCase],
        review_result: ReviewResult,
        requirement_context: str,
        module_name: str,
    ) -> FixedCasesResult:
        """应用所有修复"""

        fixed_cases = list(cases)
        removed_ids: List[str] = []
        merged_ids: List[str] = []
        added_cases: List[TestCase] = []

        redundant_cases = review_result.issues

        redundant_ids_to_remove = [
            issue.case_id for issue in redundant_cases
            if issue.issue_type == "redundant_case" and issue.severity in ("high", "medium")
        ]

        redundant_cases_map = {
            case.case_id: case for case in fixed_cases
            if case.case_id in redundant_ids_to_remove
        }

        if redundant_cases_map:
            fixed_cases = [
                case for case in fixed_cases
                if case.case_id not in redundant_ids_to_remove
            ]
            removed_ids.extend(redundant_ids_to_remove)
            logger.info(f"Removed {len(redundant_ids_to_remove)} redundant cases")

        missing_scenarios = review_result.missing_scenarios

        if missing_scenarios and self.llm:
            supplement_cases = self._supplement_missing_scenarios(
                missing_scenarios,
                requirement_context,
                module_name,
                fixed_cases,
            )
            if supplement_cases:
                added_cases.extend(supplement_cases)
                fixed_cases.extend(supplement_cases)
                logger.info(f"Added {len(supplement_cases)} supplementary cases")

        for i, case in enumerate(fixed_cases, start=1):
            case.case_id = f"TC-{i:06d}"

        fix_summary = self._generate_fix_summary(
            len(removed_ids),
            len(merged_ids),
            len(added_cases),
        )

        return FixedCasesResult(
            cases=fixed_cases,
            removed_case_ids=removed_ids,
            merged_case_ids=merged_ids,
            added_cases=added_cases,
            fix_summary=fix_summary,
        )

    def fix_redundant_cases(
        self,
        cases: List[TestCase],
        issues: List[ReviewIssue],
    ) -> List[TestCase]:
        """修复重复用例"""

        redundant_ids = [
            issue.case_id for issue in issues
            if issue.issue_type == "redundant_case"
        ]

        return [
            case for case in cases
            if case.case_id not in redundant_ids
        ]

    def _supplement_missing_scenarios(
        self,
        missing_scenarios: List[MissingScenario],
        requirement_context: str,
        module_name: str,
        existing_cases: List[TestCase],
    ) -> List[TestCase]:
        """补充缺失场景"""

        if not self.llm:
            return []

        scenarios_text = "\n".join([
            f"- {s.scenario_name} (优先级: {s.priority}, 建议: {s.suggestion})"
            for s in missing_scenarios[:10]
        ])

        system_prompt, user_prompt = self.prompt_manager.build_prompt(
            "supplement_missing_scenarios",
            module_name=module_name,
            existing_cases_count=len(existing_cases),
            missing_scenarios=scenarios_text,
            requirement_context=requirement_context,
        )

        try:
            result = self.llm.generate_json(user_prompt, system_prompt)
            return self._parse_supplement_cases(result, module_name)
        except Exception as e:
            logger.error(f"Failed to supplement cases: {e}")
            return self._fallback_supplement_cases(missing_scenarios, module_name)

    def _parse_supplement_cases(
        self,
        result: Dict[str, Any],
        module_name: str,
    ) -> List[TestCase]:
        """解析补充用例"""
        cases: List[TestCase] = []

        raw_cases = result.get("supplement_cases", [])
        for raw in raw_cases:
            case = TestCase(
                case_id="SUPP-TEMP",
                module=module_name,
                name=raw.get("case_name", ""),
                acceptance_purpose=raw.get("acceptance_purpose", ""),
                preconditions="\n".join(raw.get("preconditions", [])),
                test_process="\n".join(
                    f"{i+1}. {step}"
                    for i, step in enumerate(raw.get("test_process", []))
                ),
                expected_result="\n".join(raw.get("expected_result", [])),
                case_type=raw.get("case_type", "功能测试"),
            )
            cases.append(case)

        return cases

    def _fallback_supplement_cases(
        self,
        missing_scenarios: List[MissingScenario],
        module_name: str,
    ) -> List[TestCase]:
        """备用补充用例生成"""
        cases: List[TestCase] = []

        for scenario in missing_scenarios[:5]:
            case = TestCase(
                case_id="SUPP-FALLBACK",
                module=module_name,
                name=f"{module_name} - {scenario.scenario_name}",
                acceptance_purpose=f"验证{scenario.scenario_name}功能正确。",
                preconditions="1. 系统功能模块已部署完成。\n2. 测试账号已准备。",
                test_process=f"1. 进入【{module_name}】页面。\n2. 执行{scenario.scenario_name}操作。\n3. 观察结果。",
                expected_result="操作成功完成。",
                case_type="功能测试",
            )
            cases.append(case)

        return cases

    def _generate_fix_summary(
        self,
        removed_count: int,
        merged_count: int,
        added_count: int,
    ) -> str:
        """生成修复摘要"""
        parts = []

        if removed_count > 0:
            parts.append(f"移除 {removed_count} 条重复用例")

        if merged_count > 0:
            parts.append(f"合并 {merged_count} 条相似用例")

        if added_count > 0:
            parts.append(f"补充 {added_count} 条缺失场景用例")

        if not parts:
            return "无需修复"

        return "自动修复：" + "、".join(parts)