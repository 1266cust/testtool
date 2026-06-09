from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple, Dict


class UIElementType(Enum):
    BUTTON = "button"
    INPUT_FIELD = "input_field"
    DROPDOWN = "dropdown"
    CHECKBOX = "checkbox"
    LABEL = "label"
    LINK = "link"
    ICON = "icon"
    TABLE = "table"
    UNKNOWN = "unknown"


class ReviewDimension(Enum):
    """评审维度"""
    COMPLETENESS = "completeness"
    ACCURACY = "accuracy"
    EXECUTABILITY = "executability"
    VERIFIABILITY = "verifiability"
    NON_REDUNDANCY = "non_redundancy"


class IssueType(Enum):
    """问题类型"""
    REDUNDANT_CASE = "redundant_case"
    MISSING_SCENARIO = "missing_scenario"
    VAGUE_STEP = "vague_step"
    UNVERIFIABLE_RESULT = "unverifiable_result"
    INCORRECT_PRECONDITION = "incorrect_precondition"


@dataclass
class RequirementSection:
    level: int
    title: str
    content: List[str] = field(default_factory=list)


@dataclass
class TestCase:
    case_id: str
    module: str
    name: str
    acceptance_purpose: str
    preconditions: str
    test_process: str
    expected_result: str
    case_type: str


@dataclass
class ReviewIssue:
    """评审发现的问题"""
    case_id: str
    issue_type: str
    description: str
    suggestion: str
    severity: str = "medium"


@dataclass
class MissingScenario:
    """缺失的测试场景"""
    scenario_name: str
    priority: str = "P1"
    suggestion: str = ""
    module_name: str = ""


@dataclass
class ReviewResult:
    """评审结果"""
    overall_score: float
    dimension_scores: Dict[str, float]
    issues: List[ReviewIssue]
    missing_scenarios: List[MissingScenario]
    improvement_suggestions: List[str]
    reviewed_at: str

    total_cases: int = 0
    redundant_cases_count: int = 0
    missing_scenarios_count: int = 0


@dataclass
class BoundingBox:
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass
class UIElement:
    element_type: UIElementType
    bounding_box: BoundingBox
    text: str
    confidence: float
    is_interactive: bool
    is_required: bool = False
    associated_label: Optional[str] = None
    keywords: List[str] = field(default_factory=list)


@dataclass
class OCRResult:
    text: str
    confidence: float
    bounding_box: BoundingBox
    block_num: int
    line_num: int
    word_num: int


@dataclass
class UIAnalysisResult:
    elements: List[UIElement]
    full_text: str
    ocr_results: List[OCRResult]
    detected_shapes: List[BoundingBox]
    form_fields: List[Tuple[UIElement, Optional[UIElement]]]
    action_buttons: List[UIElement]