from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple, Dict


class UIElementType(Enum):
    BUTTON = "button"
    INPUT_FIELD = "input_field"
    DROPDOWN = "dropdown"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    LABEL = "label"
    LINK = "link"
    ICON = "icon"
    TABLE = "table"
    TAB = "tab"
    MODAL = "modal"
    TOOLTIP = "tooltip"
    SLIDER = "slider"
    SWITCH = "switch"
    DATE_PICKER = "date_picker"
    FILE_UPLOAD = "file_upload"
    TEXT_AREA = "text_area"
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
    steps: str
    expected_result: str
    case_type: str
    priority: str = "P1"


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
class ModifiedCaseRecord:
    """记录被修改的用例"""
    case_id: str
    original_case: TestCase
    modified_case: TestCase
    modification_type: str  # vague_step / unverifiable_result / incorrect_precondition
    modification_summary: str


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


@dataclass
class ProjectFileInfo:
    relative_path: str
    file_type: str
    content: str


@dataclass
class ProjectContext:
    project_name: str
    directory_tree: str
    conftest_files: List[ProjectFileInfo]
    page_objects: List[ProjectFileInfo]
    test_files: List[ProjectFileInfo]
    other_files: List[ProjectFileInfo]
    detected_patterns: Dict[str, str]
    analysis_summary: str


@dataclass
class CodeGenerationResult:
    code: str
    recommended_file_path: str = ""
    integration_instructions: List[str] = field(default_factory=list)
    imports_to_add: List[str] = field(default_factory=list)
    files_to_modify: List[str] = field(default_factory=list)


@dataclass
class UIInteractionStep:
    step_number: int
    action: str
    target: str
    target_type: str
    locator_strategy: str
    locator_value: str
    input_value: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "step_number": self.step_number,
            "action": self.action,
            "target": self.target,
            "target_type": self.target_type,
            "locator_strategy": self.locator_strategy,
            "locator_value": self.locator_value,
            "input_value": self.input_value,
            "description": self.description,
        }


@dataclass
class UIInteractionSequence:
    page_name: str
    page_url: str
    steps: List[UIInteractionStep]
    elements_summary: List[dict]
    raw_code: str = ""

    def to_dict(self) -> dict:
        return {
            "page_name": self.page_name,
            "page_url": self.page_url,
            "steps": [s.to_dict() for s in self.steps],
            "elements_summary": self.elements_summary,
            "raw_code": self.raw_code,
        }


@dataclass
class UIVisionElement:
    """通过多模态大模型识别的UI元素"""
    element_type: str
    text: str
    description: str
    is_interactive: bool
    locator_strategy: str = ""
    locator_value: str = ""
    suggested_action: str = ""
    suggested_input: str = ""
    position: Optional[str] = None
    confidence: float = 0.0
    children: List['UIVisionElement'] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "element_type": self.element_type,
            "text": self.text,
            "description": self.description,
            "is_interactive": self.is_interactive,
            "locator_strategy": self.locator_strategy,
            "locator_value": self.locator_value,
            "suggested_action": self.suggested_action,
            "suggested_input": self.suggested_input,
            "position": self.position,
            "confidence": self.confidence,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class UIPageFlow:
    """页面流转关系"""
    from_page: str
    to_page: str
    trigger_element: str
    trigger_action: str
    condition: str = ""

    def to_dict(self) -> dict:
        return {
            "from_page": self.from_page,
            "to_page": self.to_page,
            "trigger_element": self.trigger_element,
            "trigger_action": self.trigger_action,
            "condition": self.condition,
        }


@dataclass
class UIInteractionFlow:
    """完整的UI交互操作流程（多模态大模型生成）"""
    flow_name: str
    description: str
    pages: List[str]
    elements: List[UIVisionElement]
    steps: List[UIInteractionStep]
    page_flows: List[UIPageFlow]
    raw_response: str = ""

    def to_dict(self) -> dict:
        return {
            "flow_name": self.flow_name,
            "description": self.description,
            "pages": self.pages,
            "elements": [e.to_dict() for e in self.elements],
            "steps": [s.to_dict() for s in self.steps],
            "page_flows": [f.to_dict() for f in self.page_flows],
        }


@dataclass
class VisionAnalysisResult:
    """多模态大模型UI分析结果"""
    page_description: str
    page_type: str
    elements: List[UIVisionElement]
    interaction_sequences: List[UIInteractionFlow]
    page_flows: List[UIPageFlow]
    raw_response: str = ""

    def to_dict(self) -> dict:
        return {
            "page_description": self.page_description,
            "page_type": self.page_type,
            "elements": [e.to_dict() for e in self.elements],
            "interaction_sequences": [f.to_dict() for f in self.interaction_sequences],
            "page_flows": [f.to_dict() for f in self.page_flows],
        }