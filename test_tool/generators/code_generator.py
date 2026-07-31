from __future__ import annotations

import re
import textwrap
from typing import List, Optional, Tuple

from ..core.models import UIAnalysisResult, UIElement, UIElementType, CodeGenerationResult, ProjectContext
from ..core.logging import get_logger
from ..llm.prompts import PromptManager

logger = get_logger("generators.code_generator")


def _sanitize_identifier(text: str) -> str:
    s = re.sub(r"[^\w一-鿿]+", "_", text.strip())
    s = re.sub(r"_+", "_", s).strip("_")
    if not s or s[0].isdigit():
        s = "element_" + s
    return s.lower()


def _escape_py_str(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


class AutomationCodeGenerator:

    def generate_code(
        self,
        ui_result: UIAnalysisResult,
        page_url: str = "https://example.com",
        page_name: str = "page",
        project_context: Optional[ProjectContext] = None,
    ) -> CodeGenerationResult:
        class_name = _sanitize_identifier(page_name).title().replace("_", "")
        if not class_name:
            class_name = "Page"
        test_class = "Test" + class_name

        lines: List[str] = []

        lines.append('"""')
        lines.append(f"自动生成的 Playwright 测试代码 - {page_name}")
        lines.append(f"目标页面: {page_url}")
        lines.append('"""')
        lines.append("")
        lines.append("import re")
        lines.append("from playwright.sync_api import Page, expect")
        lines.append("import pytest")
        lines.append("")
        lines.append("")

        # Page Object
        lines.append(f"class {class_name}Page:")
        lines.append(f'    """Page Object for {page_name}"""')
        lines.append("")
        lines.append("    def __init__(self, page: Page):")
        lines.append("        self.page = page")
        lines.append(f"        self.url = '{_escape_py_str(page_url)}'")
        lines.append("")

        locators = self._build_locators(ui_result)
        for attr_name, locator_code, element_text, elem_type in locators:
            lines.append(f"        self.{attr_name} = {locator_code}")

        lines.append("")
        lines.append("    def navigate(self):")
        lines.append("        self.page.goto(self.url)")
        lines.append("        self.page.wait_for_load_state('networkidle')")
        lines.append("")

        fill_fields = [
            (attr, txt) for attr, _, txt, et in locators
            if et in (UIElementType.INPUT_FIELD, UIElementType.DROPDOWN)
        ]
        button_fields = [
            (attr, txt) for attr, _, txt, et in locators
            if et == UIElementType.BUTTON
        ]

        if fill_fields:
            params = ", ".join(f"{attr}: str = ''" for attr, _ in fill_fields)
            lines.append(f"    def fill_form(self, {params}):")
            for attr, _ in fill_fields:
                lines.append(f"        if {attr}:")
                lines.append(f"            self.{attr}.fill({attr})")
            lines.append("")

        for attr, txt in button_fields:
            method = "click_" + attr
            lines.append(f"    def {method}(self):")
            lines.append(f"        self.{attr}.click()")
            lines.append("")

        # Test class
        lines.append("")
        lines.append(f"class {test_class}:")
        lines.append("")
        lines.append("    @pytest.fixture(autouse=True)")
        lines.append("    def setup(self, page: Page):")
        lines.append(f"        self.po = {class_name}Page(page)")
        lines.append("        self.po.navigate()")
        lines.append("")

        lines.append("    def test_page_loads(self, page: Page):")
        lines.append(f"        expect(page).to_have_url(re.compile(r'.*'))")
        lines.append("")

        for attr, txt in button_fields:
            safe_name = _sanitize_identifier(txt)
            lines.append(f"    def test_click_{safe_name}(self, page: Page):")
            lines.append(f"        self.po.{attr}.click()")
            lines.append("")

        if fill_fields:
            lines.append("    def test_fill_form(self, page: Page):")
            for attr, txt in fill_fields:
                lines.append(f"        self.po.{attr}.fill('测试数据')")
            lines.append("")

        for attr, txt in fill_fields:
            safe_name = _sanitize_identifier(txt)
            lines.append(f"    def test_{safe_name}_empty_validation(self, page: Page):")
            lines.append(f"        self.po.{attr}.fill('')")
            if button_fields:
                lines.append(f"        self.po.{button_fields[0][0]}.click()")
            lines.append("")

        code = "\n".join(lines)
        logger.info(
            "Generated template code: "
            + str(len(locators)) + " locators, "
            + str(len(button_fields)) + " buttons, "
            + str(len(fill_fields)) + " fields"
        )

        recommended_path = ""
        instructions: List[str] = []
        if project_context and project_context.detected_patterns:
            p = project_context.detected_patterns
            if "page_object_dir" in p:
                po_dir = p["page_object_dir"].split(",")[0].strip()
                recommended_path = f"{po_dir}/{page_name}_page.py"
            if "test_dir" in p:
                test_dir = p["test_dir"].split(",")[0].strip()
                instructions.append(f"将生成的 Page Object 类放入 {po_dir}/ 目录")
                instructions.append(f"将测试类单独提取到 {test_dir}/test_{page_name}.py")
            if "base_class" in p:
                instructions.append(f"建议继承项目基类 {p['base_class']}（模板模式未自动继承，请手动修改）")
            if "fixture_pattern" in p:
                instructions.append(f"项目已有 fixture: {p['fixture_pattern']}，可在测试中直接使用")

        return CodeGenerationResult(
            code=code,
            recommended_file_path=recommended_path,
            integration_instructions=instructions,
        )

    def generate_code_with_llm(
        self,
        ui_result: UIAnalysisResult,
        page_url: str,
        page_name: str,
        llm_client,
        project_context: Optional[ProjectContext] = None,
    ) -> CodeGenerationResult:
        pm = PromptManager()
        ui_info = pm.build_ui_elements_info(ui_result)

        locators_desc = self._describe_locators(ui_result)

        if project_context:
            from .project_analyzer import build_project_context_prompt
            project_info = build_project_context_prompt(project_context)
            system_prompt, user_prompt = pm.build_prompt(
                "generate_automation_code_with_project",
                page_url=page_url,
                page_name=page_name,
                ui_elements_info=ui_info,
                locators_description=locators_desc,
                project_context_info=project_info,
            )
        else:
            system_prompt, user_prompt = pm.build_prompt(
                "generate_automation_code",
                page_url=page_url,
                page_name=page_name,
                ui_elements_info=ui_info,
                locators_description=locators_desc,
            )

        raw = llm_client.generate(user_prompt, system_prompt=system_prompt)

        if project_context:
            result = self._parse_structured_response(raw)
        else:
            code = self._extract_code_block(raw)
            result = CodeGenerationResult(code=code)

        logger.info("Generated LLM code for page: " + page_name)
        return result

    def _build_locators(
        self, ui_result: UIAnalysisResult
    ) -> List[Tuple[str, str, str, UIElementType]]:
        locators: List[Tuple[str, str, str, UIElementType]] = []
        seen_names: set = set()

        for btn in ui_result.action_buttons:
            attr = _sanitize_identifier(btn.text) + "_btn"
            attr = self._unique_name(attr, seen_names)
            text = _escape_py_str(btn.text)
            locator = f"page.get_by_role('button', name='{text}')"
            locators.append((attr, locator, btn.text, UIElementType.BUTTON))

        for field, label in ui_result.form_fields:
            label_text = ""
            if label:
                label_text = label.text
            elif field.associated_label:
                label_text = field.associated_label
            else:
                label_text = field.text

            if not label_text.strip():
                continue

            attr = _sanitize_identifier(label_text) + "_input"
            attr = self._unique_name(attr, seen_names)
            escaped = _escape_py_str(label_text)

            if field.element_type == UIElementType.DROPDOWN:
                locator = f"page.get_by_label('{escaped}')"
                locators.append((attr, locator, label_text, UIElementType.DROPDOWN))
            else:
                locator = f"page.get_by_label('{escaped}')"
                locators.append((attr, locator, label_text, UIElementType.INPUT_FIELD))

        return locators

    def _unique_name(self, base: str, seen: set) -> str:
        name = base
        i = 2
        while name in seen:
            name = base + "_" + str(i)
            i += 1
        seen.add(name)
        return name

    def _describe_locators(self, ui_result: UIAnalysisResult) -> str:
        parts: List[str] = []

        if ui_result.action_buttons:
            parts.append("可操作按钮:")
            for b in ui_result.action_buttons[:15]:
                parts.append(f"  - 按钮 \"{b.text}\" (位置: x={b.bounding_box.x}, y={b.bounding_box.y})")

        if ui_result.form_fields:
            parts.append("表单字段:")
            for field, label in ui_result.form_fields[:15]:
                label_text = label.text if label else (field.associated_label or field.text)
                field_type = field.element_type.value
                parts.append(f"  - 字段 \"{label_text}\" (类型: {field_type})")

        if ui_result.full_text:
            parts.append("页面文本摘要:")
            parts.append("  " + ui_result.full_text[:300])

        return "\n".join(parts)

    def _extract_code_block(self, raw: str) -> str:
        pattern = r"```(?:python)?\s*\n(.*?)```"
        match = re.search(pattern, raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        return raw.strip()

    def _parse_structured_response(self, raw: str) -> CodeGenerationResult:
        code = self._extract_code_block(raw)

        recommended_path = ""
        path_match = re.search(r"RECOMMENDED_PATH:\s*(.+)", raw)
        if path_match:
            recommended_path = path_match.group(1).strip()

        instructions: List[str] = []
        instr_match = re.search(
            r"INTEGRATION_INSTRUCTIONS:\s*\n((?:\d+\.\s*.+\n?)+)", raw
        )
        if instr_match:
            for line in instr_match.group(1).strip().splitlines():
                step = re.sub(r"^\d+\.\s*", "", line.strip())
                if step:
                    instructions.append(step)

        imports_to_add: List[str] = []
        imports_match = re.search(
            r"IMPORTS_TO_ADD:\s*\n((?:-\s*.+\n?)+)", raw
        )
        if imports_match:
            for line in imports_match.group(1).strip().splitlines():
                imp = re.sub(r"^-\s*", "", line.strip())
                if imp:
                    imports_to_add.append(imp)

        return CodeGenerationResult(
            code=code,
            recommended_file_path=recommended_path,
            integration_instructions=instructions,
            imports_to_add=imports_to_add,
        )
