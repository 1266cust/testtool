from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from ..core.models import RequirementSection, UIAnalysisResult, VisionAnalysisResult


@dataclass
class PromptTemplate:
    """Prompt模板"""
    name: str
    system_prompt: str
    user_prompt_template: str
    expected_output_format: str = "json"


SYSTEM_PROMPT_TEST_POINT_ANALYSIS = """你是一名专业的测试分析专家，擅长从需求文档中提取和拆分测试点。

分析原则：
1. 按功能维度拆分，而非简单复制需求描述
2. 识别隐含的测试场景（性能、安全、兼容性等）
3. 考虑用户交互路径和数据流转
4. 区分核心功能和辅助功能

输出要求：
- 测试点列表，每个包含：功能名称、测试维度、优先级、关联需求
- 严格遵循JSON格式输出，确保结构正确"""


SYSTEM_PROMPT_TEST_CASE_GENERATION = """你是一名专业的软件测试工程师，擅长分析需求文档并设计高质量的测试用例。

你的目标是生成针对性强、覆盖全面的测试用例，避免重复和冗余。

测试用例设计原则：
1. 每个测试点应覆盖正常场景、异常场景和边界场景
2. 预置条件应根据具体功能定制，而非通用模板
3. 测试步骤应具体明确，可执行性强
4. 预期结果应可验证，有明确的检查点

输出格式：严格遵循JSON格式输出，确保结构正确。"""


SYSTEM_PROMPT_CASE_REVIEW = """你是一名资深测试评审专家，负责评估测试用例的质量。

评审维度：
1. 完整性：是否覆盖所有必要场景
2. 准确性：是否准确反映需求意图
3. 可执行性：步骤是否清晰可操作
4. 可验证性：预期结果是否可验证
5. 无冗余性：是否存在重复或无价值用例

输出格式：评审结果JSON，包含评分和改进建议"""


SYSTEM_PROMPT_CASE_FIX = """你是一名专业的测试用例修复专家，负责根据评审意见改进测试用例。

修复原则：
1. 保持用例的核心测试目的不变
2. 根据评审建议针对性地修改问题内容
3. 修改后的内容应具体、明确、可执行、可验证
4. 遵循测试用例编写规范

输出格式：严格遵循JSON格式输出，确保结构正确。"""


SYSTEM_PROMPT_AUTOMATION_CODE = """你是一名专业的自动化测试工程师，擅长使用 Playwright (Python) 编写高质量的 UI 自动化测试脚本。

编码原则：
1. 使用 Page Object 模式组织代码
2. 优先使用 get_by_role、get_by_label、get_by_text 等语义化定位器
3. 合理使用 expect 断言验证操作结果
4. 添加适当的等待策略（wait_for_load_state、wait_for_selector）
5. 生成的代码应可直接运行，基于 pytest-playwright

输出格式：直接输出 Python 代码，不要添加额外说明。代码用 ```python ... ``` 包裹。"""


SYSTEM_PROMPT_AUTOMATION_CODE_WITH_PROJECT = """你是一名专业的自动化测试工程师，擅长使用 Playwright (Python) 编写高质量的 UI 自动化测试脚本，并能将新代码无缝集成到已有项目中。

编码原则：
1. 使用 Page Object 模式组织代码
2. 优先使用 get_by_role、get_by_label、get_by_text 等语义化定位器
3. 合理使用 expect 断言验证操作结果
4. 添加适当的等待策略（wait_for_load_state、wait_for_selector）
5. 生成的代码应可直接运行，基于 pytest-playwright

项目集成原则：
1. 严格遵循项目现有的命名规范（类名、方法名、文件名）
2. 使用与项目一致的 import 风格（相对导入或绝对导入）
3. 如果项目有 Page Object 基类，必须继承该基类
4. 使用项目 conftest.py 中已定义的 fixture
5. 匹配项目现有的代码风格（注释语言、缩进、docstring 格式）
6. 将文件放置在项目已有的目录结构中

输出格式要求：
1. 先输出代码，用 ```python ... ``` 包裹
2. 然后输出 RECOMMENDED_PATH: <建议的文件路径，相对于项目根目录>
3. 然后输出集成步骤：
   INTEGRATION_INSTRUCTIONS:
   1. 步骤说明
   2. 步骤说明
4. 如果需要在已有文件中添加 import，输出：
   IMPORTS_TO_ADD:
    - <文件路径>: <import 语句>"""


SYSTEM_PROMPT_UI_INTERACTION = """你是一名专业的UI自动化测试工程师，擅长分析原型图/UI截图，识别页面元素并生成完整的UI交互操作序列。

分析原则：
1. 识别页面中所有可交互元素（按钮、输入框、下拉框、复选框、链接等）
2. 根据元素类型和位置关系，推断合理的操作顺序
3. 为每个操作步骤提供精确的 Playwright 定位策略
4. 填写类操作应提供合理的测试数据
5. 操作序列应覆盖典型用户操作流程

输出格式：严格遵循JSON格式，结构如下：
```json
{
  "steps": [
    {
      "step_number": 1,
      "action": "click/fill/select/hover/scroll/check",
      "target": "元素名称",
      "target_type": "button/input/dropdown/checkbox/link/tab",
      "locator_strategy": "get_by_role/get_by_label/get_by_text/get_by_placeholder/get_by_test_id",
      "locator_value": "定位值",
      "input_value": "输入值（仅fill/select时需要）",
      "description": "操作描述"
    }
  ]
}
```"""


class PromptManager:
    """Prompt模板管理器"""

    ANALYZE_TEST_POINTS = PromptTemplate(
        name="analyze_test_points",
        system_prompt=SYSTEM_PROMPT_TEST_POINT_ANALYSIS,
        user_prompt_template="""
请分析以下需求内容，拆分出测试点：

【需求模块】: {module_name}
【需求内容】:
{requirement_content}

【UI元素信息】(如有):
{ui_elements_info}

请输出JSON格式的测试点列表：
{{
  "test_points": [
    {{
      "point_name": "测试点名称",
      "category": "功能类型（如：新增/编辑/删除/查询/权限/数据导入等）",
      "dimensions": ["正常场景", "异常场景", "边界场景"],
      "priority": "P0/P1/P2",
      "related_requirement": "关联的需求描述",
      "test_coverage_suggestions": ["建议覆盖的测试场景"]
    }}
  ],
  "module_analysis": {{
    "core_functions": ["核心功能列表"],
    "secondary_functions": ["辅助功能列表"],
    "risk_areas": ["风险关注点"]
  }}
}}
""",
        expected_output_format="json"
    )

    GENERATE_TEST_CASES = PromptTemplate(
        name="generate_test_cases",
        system_prompt=SYSTEM_PROMPT_TEST_CASE_GENERATION,
        user_prompt_template="""
请为以下测试点生成测试用例：

【模块名称】: {module_name}
【测试点】: {test_point}
【测试维度】: {dimensions}
【需求上下文】: {requirement_context}
{knowledge_context}
【系统配置】:
- 系统名称: {system_name}
- 管理员账号: {admin_user}
- 普通用户账号: {normal_user}

请生成覆盖该测试点的测试用例，输出JSON格式：
{{
  "cases": [
    {{
      "case_name": "用例名称（应包含测试点+场景描述）",
      "scene_name": "测试场景（如：正常操作、异常输入、边界值测试等）",
      "case_type": "用例类型（功能测试/异常测试/边界值测试/安全测试等）",
      "priority": "优先级（P0/P1/P2）",
      "acceptance_purpose": "验收目的",
      "preconditions": [
        "前置条件1（根据具体功能定制）",
        "前置条件2"
      ],
      "steps": [
        "步骤1",
        "步骤2"
      ],
      "expected_result": [
        "预期结果1",
        "预期结果2"
      ],
      "verify_points": ["校验点列表"]
    }}
  ]
}}

注意：
- preconditions应根据实际功能定制，不要使用通用模板
- steps步骤应具体明确，避免过于笼统
- 每个测试点生成2-5个用例，覆盖不同维度
- 避免生成重复或相似的用例
- 如果有知识库参考内容，请参考历史文档的风格和模式生成用例
""",
        expected_output_format="json"
    )

    REVIEW_TEST_CASES = PromptTemplate(
        name="review_test_cases",
        system_prompt=SYSTEM_PROMPT_CASE_REVIEW,
        user_prompt_template="""
请评审以下测试用例：

【模块名称】: {module_name}
【需求背景】: {requirement_context}
【测试用例列表】:
{cases_content}

请输出评审结果JSON：
{{
  "overall_score": 85,
  "dimension_scores": {{
    "completeness": 90,
    "accuracy": 85,
    "executability": 80,
    "verifiability": 90,
    "non_redundancy": 80
  }},
  "issues": [
    {{
      "case_id": "TC-000001",
      "issue_type": "redundant_case",
      "description": "与TC-000003测试场景重复",
      "suggestion": "合并或删除其中一个",
      "severity": "medium"
    }}
  ],
  "missing_scenarios": [
    {{
      "scenario_name": "缺失场景名称",
      "priority": "P0/P1/P2",
      "suggestion": "应补充的测试点"
    }}
  ],
  "improvement_suggestions": [
    "建议增加XX场景的测试用例",
    "预置条件建议细化"
  ]
}}

issue_type可选值：redundant_case, missing_scenario, vague_step, unverifiable_result, incorrect_precondition
""",
        expected_output_format="json"
    )

    SUPPLEMENT_MISSING_SCENARIOS = PromptTemplate(
        name="supplement_missing_scenarios",
        system_prompt=SYSTEM_PROMPT_TEST_CASE_GENERATION,
        user_prompt_template="""
请根据评审结果补充缺失的测试场景：

【模块名称】: {module_name}
【现有用例】: {existing_cases_count}条
【缺失场景】:
{missing_scenarios}

【需求上下文】: {requirement_context}

请为缺失场景生成补充用例，输出JSON格式：
{{
  "supplement_cases": [
    {{
      "case_name": "用例名称",
      "scene_name": "测试场景",
      "case_type": "用例类型",
      "priority": "优先级（P0/P1/P2）",
      "acceptance_purpose": "验收目的",
      "preconditions": ["前置条件"],
      "steps": ["操作步骤"],
      "expected_result": ["预期结果"]
    }}
  ]
}}
""",
        expected_output_format="json"
    )

    FIX_VAGUE_STEP = PromptTemplate(
        name="fix_vague_step",
        system_prompt=SYSTEM_PROMPT_CASE_FIX,
        user_prompt_template="""
请根据评审意见修改以下测试用例的步骤描述，使其更具体、更可执行：

【用例ID】: {case_id}
【用例名称】: {case_name}
【模块名称】: {module_name}
【原测试步骤】:
{original_process}

【问题描述】: {description}
【修改建议】: {suggestion}

【需求上下文】: {requirement_context}

请输出修改后的测试步骤（JSON格式）：
{{
  "steps": [
    "步骤1：具体的操作描述",
    "步骤2：具体的操作描述"
  ],
  "modification_summary": "简要描述修改内容"
}}
""",
        expected_output_format="json"
    )

    FIX_UNVERIFIABLE_RESULT = PromptTemplate(
        name="fix_unverifiable_result",
        system_prompt=SYSTEM_PROMPT_CASE_FIX,
        user_prompt_template="""
请根据评审意见修改以下测试用例的预期结果，使其可验证、有明确的检查点：

【用例ID】: {case_id}
【用例名称】: {case_name}
【模块名称】: {module_name}
【原预期结果】:
{original_result}

【测试步骤】: {test_process}
【问题描述】: {description}
【修改建议】: {suggestion}

【需求上下文】: {requirement_context}

请输出修改后的预期结果（JSON格式）：
{{
  "expected_result": [
    "预期结果1：具体的验证点",
    "预期结果2：具体的验证点"
  ],
  "modification_summary": "简要描述修改内容"
}}
""",
        expected_output_format="json"
    )

    FIX_INCORRECT_PRECONDITION = PromptTemplate(
        name="fix_incorrect_precondition",
        system_prompt=SYSTEM_PROMPT_CASE_FIX,
        user_prompt_template="""
请根据评审意见修改以下测试用例的预置条件，使其正确、完整：

【用例ID】: {case_id}
【用例名称】: {case_name}
【模块名称】: {module_name}
【原预置条件】:
{original_preconditions}

【测试步骤】: {test_process}
【问题描述】: {description}
【修改建议】: {suggestion}

【需求上下文】: {requirement_context}

请输出修改后的预置条件（JSON格式）：
{{
  "preconditions": [
    "前置条件1：具体的环境或数据准备要求",
    "前置条件2：具体的账号或权限要求"
  ],
  "modification_summary": "简要描述修改内容"
}}
""",
        expected_output_format="json"
    )

    GENERATE_AUTOMATION_CODE = PromptTemplate(
        name="generate_automation_code",
        system_prompt=SYSTEM_PROMPT_AUTOMATION_CODE,
        user_prompt_template="""
请根据以下网页UI元素信息，生成 Playwright (Python) 自动化测试代码：

【页面名称】: {page_name}
【页面URL】: {page_url}

【UI元素信息】:
{ui_elements_info}

【元素定位详情】:
{locators_description}

请生成完整的测试代码，要求：
1. 使用 Page Object 模式，创建页面对象类
2. 使用 pytest-playwright 框架
3. 为每个可交互元素生成定位器属性
4. 为按钮生成点击测试方法
5. 为表单字段生成填写和验证测试方法
6. 包含页面导航方法
7. 添加合理的 expect 断言
8. 使用 get_by_role、get_by_label、get_by_text 等语义化定位器

直接输出 Python 代码：
```python
# 在这里生成代码
```
""",
        expected_output_format="text"
    )

    GENERATE_AUTOMATION_CODE_WITH_PROJECT = PromptTemplate(
        name="generate_automation_code_with_project",
        system_prompt=SYSTEM_PROMPT_AUTOMATION_CODE_WITH_PROJECT,
        user_prompt_template="""
请根据以下网页UI元素信息和现有项目结构，生成能直接集成到项目中的 Playwright (Python) 自动化测试代码：

【页面名称】: {page_name}
【页面URL】: {page_url}

【UI元素信息】:
{ui_elements_info}

【元素定位详情】:
{locators_description}

【现有项目结构】:
{project_context_info}

请生成能无缝集成到上述项目的测试代码，要求：
1. 遵循项目现有的命名规范和代码风格
2. 使用项目中已有的基类、fixture和工具函数
3. 导入路径与现有文件保持一致
4. 如果项目使用了特定的断言模式或等待策略，请沿用
5. 为每个可交互元素生成定位器属性
6. 为按钮生成点击测试方法
7. 为表单字段生成填写和验证测试方法
8. 添加合理的 expect 断言

输出格式：
```python
# 在这里生成代码
```

RECOMMENDED_PATH: <建议的文件路径，相对于项目根目录>

INTEGRATION_INSTRUCTIONS:
1. <集成步骤1>
2. <集成步骤2>

IMPORTS_TO_ADD:
- <需要在已有文件中添加的import语句，格式: 文件路径: import语句>
""",
        expected_output_format="text"
    )

    GENERATE_VISION_INTERACTION = PromptTemplate(
        name="generate_vision_interaction",
        system_prompt=SYSTEM_PROMPT_UI_INTERACTION,
        user_prompt_template="""
请根据以下多模态大模型识别的UI元素信息，生成完整的UI交互操作序列：

【页面名称】: {page_name}
【页面URL】: {page_url}

【页面描述】: {page_description}
【页面类型】: {page_type}

【识别到的UI元素】:
{vision_elements_info}

【页面流转关系】:
{page_flows_info}

【用户补充描述】: {user_description}

请生成完整的交互操作序列，要求：
1. 覆盖页面的主要操作流程
2. 为填写类操作提供合理的测试数据
3. 为每个操作提供精确的 Playwright 定位策略
4. 考虑元素之间的依赖关系和操作顺序
5. 包含必要的断言验证步骤

输出格式：严格遵循JSON格式，结构如下：
```json
{{
  "steps": [
    {{
      "step_number": 1,
      "action": "click/fill/select/hover/scroll/check/uncheck/press_key/wait/assert",
      "target": "元素名称",
      "target_type": "button/input/dropdown/checkbox/radio/link/tab",
      "locator_strategy": "get_by_role/get_by_label/get_by_text/get_by_placeholder/get_by_test_id",
      "locator_value": "定位值",
      "input_value": "输入值（仅fill/select时需要）",
      "description": "操作描述"
    }}
  ]
}}
```
""",
        expected_output_format="json"
    )

    def get_template(self, name: str) -> PromptTemplate:
        """获取模板"""
        templates = {
            "analyze_test_points": self.ANALYZE_TEST_POINTS,
            "generate_test_cases": self.GENERATE_TEST_CASES,
            "review_test_cases": self.REVIEW_TEST_CASES,
            "supplement_missing_scenarios": self.SUPPLEMENT_MISSING_SCENARIOS,
            "fix_vague_step": self.FIX_VAGUE_STEP,
            "fix_unverifiable_result": self.FIX_UNVERIFIABLE_RESULT,
            "fix_incorrect_precondition": self.FIX_INCORRECT_PRECONDITION,
            "generate_automation_code": self.GENERATE_AUTOMATION_CODE,
            "generate_automation_code_with_project": self.GENERATE_AUTOMATION_CODE_WITH_PROJECT,
            "generate_vision_interaction": self.GENERATE_VISION_INTERACTION,
        }
        return templates[name]

    def build_prompt(
        self,
        template_name: str,
        **kwargs
    ) -> tuple[str, str]:
        """构建完整Prompt"""
        template = self.get_template(template_name)

        defaults = {
            "ui_elements_info": "无UI元素信息",
            "system_name": "目标系统",
            "admin_user": "admin",
            "normal_user": "user",
            "requirement_context": "",
            "cases_content": "",
            "existing_cases_count": 0,
            "missing_scenarios": "",
            "knowledge_context": "",
            "case_id": "",
            "case_name": "",
            "module_name": "",
            "original_process": "",
            "original_result": "",
            "original_preconditions": "",
            "test_process": "",
            "description": "",
            "suggestion": "",
            "page_url": "https://example.com",
            "page_name": "page",
            "locators_description": "",
            "project_context_info": "",
            "page_description": "",
            "page_type": "",
            "vision_elements_info": "",
            "page_flows_info": "",
            "user_description": "",
        }

        full_kwargs = {**defaults, **kwargs}
        user_prompt = template.user_prompt_template.format(**full_kwargs)

        return template.system_prompt, user_prompt

    def build_ui_elements_info(
        self,
        ui_result: Optional[UIAnalysisResult]
    ) -> str:
        """构建UI元素信息描述"""
        if not ui_result:
            return "无UI元素信息"

        info_parts = []

        if ui_result.action_buttons:
            buttons = [f"按钮[{b.text}]" for b in ui_result.action_buttons[:10]]
            info_parts.append(f"操作按钮: {', '.join(buttons)}")

        if ui_result.form_fields:
            fields = []
            for field, label in ui_result.form_fields[:10]:
                label_text = label.text if label else field.associated_label or "未知"
                fields.append(f"字段[{label_text}]")
            info_parts.append(f"表单字段: {', '.join(fields)}")

        if ui_result.full_text:
            text_preview = ui_result.full_text[:200]
            info_parts.append(f"界面文本摘要: {text_preview}")

        return "\n".join(info_parts) if info_parts else "无UI元素信息"

    def build_vision_elements_info(
        self,
        vision_result: Optional[VisionAnalysisResult]
    ) -> str:
        """构建多模态大模型识别的UI元素信息描述"""
        if not vision_result or not vision_result.elements:
            return "无多模态识别结果"

        info_parts = []

        if vision_result.page_description:
            info_parts.append(f"页面描述: {vision_result.page_description}")

        if vision_result.page_type:
            info_parts.append(f"页面类型: {vision_result.page_type}")

        interactive = [e for e in vision_result.elements if e.is_interactive]
        if interactive:
            parts = []
            for elem in interactive[:20]:
                desc = f"  - {elem.element_type}[{elem.text}]"
                if elem.suggested_action:
                    desc += f" -> {elem.suggested_action}"
                if elem.locator_strategy and elem.locator_value:
                    desc += f" ({elem.locator_strategy}: {elem.locator_value})"
                parts.append(desc)
            info_parts.append("可交互元素:\n" + "\n".join(parts))

        non_interactive = [e for e in vision_result.elements if not e.is_interactive]
        if non_interactive:
            parts = []
            for elem in non_interactive[:10]:
                parts.append(f"  - {elem.element_type}[{elem.text}]: {elem.description}")
            info_parts.append("其他元素:\n" + "\n".join(parts))

        return "\n".join(info_parts) if info_parts else "无多模态识别结果"

    def build_page_flows_info(
        self,
        vision_result: Optional[VisionAnalysisResult]
    ) -> str:
        """构建页面流转关系描述"""
        if not vision_result or not vision_result.page_flows:
            return "无页面流转信息"

        parts = []
        for flow in vision_result.page_flows:
            desc = f"  {flow.from_page} -> {flow.to_page}"
            desc += f" (触发: {flow.trigger_element} / {flow.trigger_action})"
            if flow.condition:
                desc += f" [条件: {flow.condition}]"
            parts.append(desc)

        return "\n".join(parts)