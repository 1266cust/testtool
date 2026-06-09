from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime

from ..llm.client import LLMClient
from ..llm.prompts import PromptManager
from ..core.models import TestCase, ReviewResult, ReviewIssue, MissingScenario
from ..core.logging import get_logger

logger = get_logger("review.reviewer")


@dataclass
class ReviewConfig:
    """评审配置"""
    max_cases_per_review: int = 50
    check_redundancy: bool = True
    check_completeness: bool = True
    check_executability: bool = True


class TestCaseReviewer:
    """测试用例评审器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self.prompt_manager = PromptManager()

    def review_cases(
        self,
        cases: List[TestCase],
        requirement_context: str,
        module_name: str,
    ) -> ReviewResult:
        """评审测试用例"""

        cases_to_review = cases[:50]
        cases_content = self._format_cases_for_review(cases_to_review)

        system_prompt, user_prompt = self.prompt_manager.build_prompt(
            "review_test_cases",
            module_name=module_name,
            requirement_context=requirement_context,
            cases_content=cases_content,
        )

        logger.info(f"Reviewing {len(cases_to_review)} cases for module: {module_name}")

        try:
            result = self.llm.generate_json(user_prompt, system_prompt)
            review_result = self._parse_review_result(result, cases)

            logger.info(f"Review score: {review_result.overall_score}")
            return review_result
        except Exception as e:
            logger.error(f"Failed to review cases: {e}")
            return self._fallback_review_result(cases)

    def review_all_modules(
        self,
        cases: List[TestCase],
        contexts_by_module: Dict[str, str],
    ) -> Dict[str, ReviewResult]:
        """评审所有模块"""
        results: Dict[str, ReviewResult] = {}

        cases_by_module: Dict[str, List[TestCase]] = {}
        for case in cases:
            cases_by_module.setdefault(case.module, []).append(case)

        for module_name, module_cases in cases_by_module.items():
            context = contexts_by_module.get(module_name, "")
            results[module_name] = self.review_cases(module_cases, context, module_name)

        return results

    def _format_cases_for_review(self, cases: List[TestCase]) -> str:
        """格式化用例用于评审"""
        lines = []

        for i, case in enumerate(cases):
            pre_preview = case.preconditions[:100] if case.preconditions else "无"
            process_preview = case.test_process[:200] if case.test_process else "无"
            expected_preview = case.expected_result[:100] if case.expected_result else "无"

            lines.append(f"""
【用例{i+1}】 {case.case_id}
- 名称: {case.name}
- 类型: {case.case_type}
- 预置条件: {pre_preview}
- 测试步骤: {process_preview}
- 预期结果: {expected_preview}
""")
        return "\n".join(lines)

    def _parse_review_result(
        self,
        result: Dict[str, Any],
        cases: List[TestCase]
    ) -> ReviewResult:
        """解析评审结果"""
        issues: List[ReviewIssue] = []

        for raw_issue in result.get("issues", []):
            issue = ReviewIssue(
                case_id=raw_issue.get("case_id", ""),
                issue_type=raw_issue.get("issue_type", "redundant_case"),
                description=raw_issue.get("description", ""),
                suggestion=raw_issue.get("suggestion", ""),
                severity=raw_issue.get("severity", "medium"),
            )
            issues.append(issue)

        missing_scenarios: List[MissingScenario] = []
        for raw_scenario in result.get("missing_scenarios", []):
            missing_scenario = MissingScenario(
                scenario_name=raw_scenario.get("scenario_name", ""),
                priority=raw_scenario.get("priority", "P1"),
                suggestion=raw_scenario.get("suggestion", ""),
            )
            missing_scenarios.append(missing_scenario)

        redundant_count = sum(
            1 for i in issues if i.issue_type == "redundant_case"
        )
        missing_count = len(missing_scenarios)

        return ReviewResult(
            overall_score=result.get("overall_score", 0),
            dimension_scores=result.get("dimension_scores", {}),
            issues=issues,
            missing_scenarios=missing_scenarios,
            improvement_suggestions=result.get("improvement_suggestions", []),
            reviewed_at=datetime.now().isoformat(),
            total_cases=len(cases),
            redundant_cases_count=redundant_count,
            missing_scenarios_count=missing_count,
        )

    def _fallback_review_result(self, cases: List[TestCase]) -> ReviewResult:
        """备用评审结果"""
        return ReviewResult(
            overall_score=60,
            dimension_scores={
                "completeness": 70,
                "accuracy": 60,
                "executability": 60,
                "verifiability": 60,
                "non_redundancy": 70,
            },
            issues=[],
            missing_scenarios=[],
            improvement_suggestions=["无法执行智能评审，请配置LLM API Key"],
            reviewed_at=datetime.now().isoformat(),
            total_cases=len(cases),
            redundant_cases_count=0,
            missing_scenarios_count=0,
        )