from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict

from ..core.models import TestCase


@dataclass
class QualityMetrics:
    """质量指标"""
    coverage_ratio: float
    redundancy_ratio: float
    average_steps_count: float
    preconditions_quality: float
    cases_count: int
    modules_count: int


class QualityMetricsCalculator:
    """质量指标计算器"""

    def calculate(self, cases: List[TestCase]) -> QualityMetrics:
        """计算质量指标"""
        if not cases:
            return QualityMetrics(
                coverage_ratio=0,
                redundancy_ratio=0,
                average_steps_count=0,
                preconditions_quality=0,
                cases_count=0,
                modules_count=0,
            )

        signatures = set()
        duplicates = 0

        for case in cases:
            sig = f"{case.module}:{case.name}"
            if sig in signatures:
                duplicates += 1
            signatures.add(sig)

        redundancy_ratio = duplicates / len(cases) if cases else 0

        total_steps = sum(
            len(case.test_process.split("\n"))
            for case in cases
        )
        avg_steps = total_steps / len(cases) if cases else 0

        generic_precondition_phrases = [
            "系统功能模块已部署完成",
            "测试账号已准备",
            "可正常访问",
        ]

        non_generic = sum(
            1 for case in cases
            if not any(
                phrase in case.preconditions
                for phrase in generic_precondition_phrases
            )
        )
        preconditions_quality = non_generic / len(cases) if cases else 0

        modules = set(case.module for case in cases)

        return QualityMetrics(
            coverage_ratio=len(cases) / max(len(cases), 100),
            redundancy_ratio=redundancy_ratio,
            average_steps_count=avg_steps,
            preconditions_quality=preconditions_quality,
            cases_count=len(cases),
            modules_count=len(modules),
        )

    def calculate_by_module(
        self,
        cases: List[TestCase]
    ) -> Dict[str, QualityMetrics]:
        """按模块计算指标"""
        by_module: Dict[str, List[TestCase]] = {}

        for case in cases:
            by_module.setdefault(case.module, []).append(case)

        return {
            module: self.calculate(module_cases)
            for module, module_cases in by_module.items()
        }

    def compare_metrics(
        self,
        before: QualityMetrics,
        after: QualityMetrics,
    ) -> Dict[str, float]:
        """对比前后指标变化"""
        return {
            "redundancy_reduction": before.redundancy_ratio - after.redundancy_ratio,
            "preconditions_improvement": after.preconditions_quality - before.preconditions_quality,
            "steps_improvement": after.average_steps_count - before.average_steps_count,
        }