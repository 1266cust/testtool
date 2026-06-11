from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import copy

from ..llm.client import LLMClient
from ..llm.prompts import PromptManager
from ..core.models import TestCase, ReviewResult, ReviewIssue, MissingScenario, ModifiedCaseRecord
from ..core.logging import get_logger

logger = get_logger("review.auto_fixer")


@dataclass
class FixedCasesResult:
    """修复后的用例结果"""
    cases: List[TestCase]
    removed_case_ids: List[str]
    merged_case_ids: List[str]
    added_cases: List[TestCase]
    modified_cases: List[ModifiedCaseRecord] = field(default_factory=list)
    fix_summary: str = ""


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
        modified_records: List[ModifiedCaseRecord] = []

        # 1. 处理重复用例（删除）
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

        # 2. 处理需要修改的用例（vague_step, unverifiable_result, incorrect_precondition）
        case_map = {case.case_id: case for case in fixed_cases}
        modified_count = 0

        for issue in review_result.issues:
            if issue.issue_type not in ("vague_step", "unverifiable_result", "incorrect_precondition"):
                continue

            original_case = case_map.get(issue.case_id)
            if not original_case:
                logger.warning(f"Case {issue.case_id} not found for modification")
                continue

            # 根据问题类型调用对应的修复方法
            if issue.issue_type == "vague_step":
                modified_case = self._fix_vague_step(original_case, issue, requirement_context, module_name)
            elif issue.issue_type == "unverifiable_result":
                modified_case = self._fix_unverifiable_result(original_case, issue, requirement_context, module_name)
            elif issue.issue_type == "incorrect_precondition":
                modified_case = self._fix_incorrect_precondition(original_case, issue, requirement_context, module_name)
            else:
                continue

            if modified_case:
                # 保存原始用例的副本用于对比
                original_copy = copy.deepcopy(original_case)
                case_map[issue.case_id] = modified_case
                modified_records.append(ModifiedCaseRecord(
                    case_id=issue.case_id,
                    original_case=original_copy,
                    modified_case=modified_case,
                    modification_type=issue.issue_type,
                    modification_summary=f"根据评审建议修复：{issue.description[:50]}",
                ))
                modified_count += 1
                logger.info(f"Modified case {issue.case_id} for {issue.issue_type}")

        # 更新 fixed_cases 为修改后的版本
        fixed_cases = list(case_map.values())

        # 3. 处理缺失场景（补充新用例）
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

        # 重新分配用例ID
        for i, case in enumerate(fixed_cases, start=1):
            case.case_id = f"TC-{i:06d}"

        fix_summary = self._generate_fix_summary(
            len(removed_ids),
            len(merged_ids),
            len(added_cases),
            modified_count,
        )

        return FixedCasesResult(
            cases=fixed_cases,
            removed_case_ids=removed_ids,
            merged_case_ids=merged_ids,
            added_cases=added_cases,
            modified_cases=modified_records,
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
                steps="\n".join(
                    f"{i+1}. {step}"
                    for i, step in enumerate(raw.get("steps", raw.get("test_process", [])))
                ),
                expected_result="\n".join(raw.get("expected_result", [])),
                case_type=raw.get("case_type", "功能测试"),
                priority=raw.get("priority", "P1"),
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
                steps=f"1. 进入【{module_name}】页面。\n2. 执行{scenario.scenario_name}操作。\n3. 观察结果。",
                expected_result="操作成功完成。",
                case_type="功能测试",
                priority=scenario.priority,
            )
            cases.append(case)

        return cases

    def _generate_fix_summary(
        self,
        removed_count: int,
        merged_count: int,
        added_count: int,
        modified_count: int = 0,
    ) -> str:
        """生成修复摘要"""
        parts = []

        if removed_count > 0:
            parts.append(f"移除 {removed_count} 条重复用例")

        if merged_count > 0:
            parts.append(f"合并 {merged_count} 条相似用例")

        if modified_count > 0:
            parts.append(f"修改 {modified_count} 条问题用例")

        if added_count > 0:
            parts.append(f"补充 {added_count} 条缺失场景用例")

        if not parts:
            return "无需修复"

        return "自动修复：" + "、".join(parts)

    def _fix_vague_step(
        self,
        case: TestCase,
        issue: ReviewIssue,
        requirement_context: str,
        module_name: str,
    ) -> Optional[TestCase]:
        """修复模糊步骤"""
        if not self.llm:
            return self._fallback_fix_vague_step(case, issue)

        system_prompt, user_prompt = self.prompt_manager.build_prompt(
            "fix_vague_step",
            case_id=case.case_id,
            case_name=case.name,
            module_name=module_name,
            original_process=case.steps,
            description=issue.description,
            suggestion=issue.suggestion,
            requirement_context=requirement_context,
        )

        try:
            result = self.llm.generate_json(user_prompt, system_prompt)
            modified_case = copy.deepcopy(case)
            steps = result.get("steps", result.get("test_process", []))
            if steps:
                modified_case.steps = "\n".join(
                    f"{i+1}. {step}" for i, step in enumerate(steps)
                )
            return modified_case
        except Exception as e:
            logger.error(f"Failed to fix vague step for {case.case_id}: {e}")
            return self._fallback_fix_vague_step(case, issue)

    def _fix_unverifiable_result(
        self,
        case: TestCase,
        issue: ReviewIssue,
        requirement_context: str,
        module_name: str,
    ) -> Optional[TestCase]:
        """修复不可验证的预期结果"""
        if not self.llm:
            return self._fallback_fix_unverifiable_result(case, issue)

        system_prompt, user_prompt = self.prompt_manager.build_prompt(
            "fix_unverifiable_result",
            case_id=case.case_id,
            case_name=case.name,
            module_name=module_name,
            original_result=case.expected_result,
            test_process=case.steps[:200] if case.steps else "",
            description=issue.description,
            suggestion=issue.suggestion,
            requirement_context=requirement_context,
        )

        try:
            result = self.llm.generate_json(user_prompt, system_prompt)
            modified_case = copy.deepcopy(case)
            expected_result = result.get("expected_result", [])
            if expected_result:
                modified_case.expected_result = "\n".join(expected_result)
            return modified_case
        except Exception as e:
            logger.error(f"Failed to fix unverifiable result for {case.case_id}: {e}")
            return self._fallback_fix_unverifiable_result(case, issue)

    def _fix_incorrect_precondition(
        self,
        case: TestCase,
        issue: ReviewIssue,
        requirement_context: str,
        module_name: str,
    ) -> Optional[TestCase]:
        """修复不正确的预置条件"""
        if not self.llm:
            return self._fallback_fix_incorrect_precondition(case, issue)

        system_prompt, user_prompt = self.prompt_manager.build_prompt(
            "fix_incorrect_precondition",
            case_id=case.case_id,
            case_name=case.name,
            module_name=module_name,
            original_preconditions=case.preconditions,
            test_process=case.steps[:200] if case.steps else "",
            description=issue.description,
            suggestion=issue.suggestion,
            requirement_context=requirement_context,
        )

        try:
            result = self.llm.generate_json(user_prompt, system_prompt)
            modified_case = copy.deepcopy(case)
            preconditions = result.get("preconditions", [])
            if preconditions:
                modified_case.preconditions = "\n".join(
                    f"{i+1}. {cond}" for i, cond in enumerate(preconditions)
                )
            return modified_case
        except Exception as e:
            logger.error(f"Failed to fix incorrect precondition for {case.case_id}: {e}")
            return self._fallback_fix_incorrect_precondition(case, issue)

    def _fallback_fix_vague_step(self, case: TestCase, issue: ReviewIssue) -> TestCase:
        """备用修复模糊步骤"""
        modified_case = copy.deepcopy(case)
        # 简单地在步骤前添加更具体的描述
        modified_case.steps = f"1. 进入测试模块。\n2. 按照需求执行具体操作。\n3. {issue.suggestion[:100] if issue.suggestion else '验证功能正确性。'}"
        return modified_case

    def _fallback_fix_unverifiable_result(self, case: TestCase, issue: ReviewIssue) -> TestCase:
        """备用修复不可验证的预期结果"""
        modified_case = copy.deepcopy(case)
        modified_case.expected_result = f"1. 操作执行成功，无错误提示。\n2. 界面显示预期结果。\n3. {issue.suggestion[:100] if issue.suggestion else '数据正确保存。'}"
        return modified_case

    def _fallback_fix_incorrect_precondition(self, case: TestCase, issue: ReviewIssue) -> TestCase:
        """备用修复不正确的预置条件"""
        modified_case = copy.deepcopy(case)
        modified_case.preconditions = f"1. 系统功能模块已部署完成。\n2. 测试账号已准备并具有相应权限。\n3. {issue.suggestion[:100] if issue.suggestion else '测试数据已准备。'}"
        return modified_case