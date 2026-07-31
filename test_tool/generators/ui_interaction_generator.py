from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import List, Optional

from ..core.models import (
    UIAnalysisResult,
    UIElement,
    UIElementType,
    UIInteractionStep,
    UIInteractionSequence,
    UIVisionElement,
    UIInteractionFlow,
    UIPageFlow,
    VisionAnalysisResult,
)
from ..core.logging import get_logger
from ..ocr.ui_element_detector import UIElementDetector
from ..ocr.multimodal_vision import MultimodalVisionAnalyzer
from ..llm.prompts import PromptManager

logger = get_logger("generators.ui_interaction_generator")


def _encode_image_base64(image_path: Path) -> str:
    with open(str(image_path), "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _infer_locator(element: UIElement) -> tuple[str, str]:
    text = element.text.strip()
    etype = element.element_type

    if etype == UIElementType.BUTTON:
        return ("get_by_role", f"button, name='{text}'")
    if etype == UIElementType.INPUT_FIELD:
        label = element.associated_label or text
        return ("get_by_label", label)
    if etype == UIElementType.DROPDOWN:
        label = element.associated_label or text
        return ("get_by_label", label)
    if etype == UIElementType.LINK:
        return ("get_by_role", f"link, name='{text}'")
    if etype == UIElementType.CHECKBOX:
        label = element.associated_label or text
        return ("get_by_label", label)
    return ("get_by_text", text)


def _build_cv_sequence(
    ui_result: UIAnalysisResult,
    page_url: str,
    page_name: str,
) -> UIInteractionSequence:
    steps: List[UIInteractionStep] = []
    step_num = 0

    for field, label in ui_result.form_fields:
        label_text = label.text if label else (field.associated_label or field.text)
        strategy, value = _infer_locator(field)
        step_num += 1
        input_val = "测试数据" if field.element_type != UIElementType.DROPDOWN else ""
        steps.append(UIInteractionStep(
            step_number=step_num,
            action="fill" if field.element_type != UIElementType.DROPDOWN else "select",
            target=label_text,
            target_type=field.element_type.value,
            locator_strategy=strategy,
            locator_value=value,
            input_value=input_val,
            description=f"填写{label_text}",
        ))

    for btn in ui_result.action_buttons:
        strategy, value = _infer_locator(btn)
        step_num += 1
        steps.append(UIInteractionStep(
            step_number=step_num,
            action="click",
            target=btn.text,
            target_type="button",
            locator_strategy=strategy,
            locator_value=value,
            description=f"点击{btn.text}",
        ))

    elements_summary = []
    for btn in ui_result.action_buttons:
        elements_summary.append({
            "type": "button",
            "text": btn.text,
            "position": {"x": btn.bounding_box.x, "y": btn.bounding_box.y},
        })
    for field, label in ui_result.form_fields:
        label_text = label.text if label else (field.associated_label or field.text)
        elements_summary.append({
            "type": field.element_type.value,
            "text": label_text,
            "position": {"x": field.bounding_box.x, "y": field.bounding_box.y},
        })

    return UIInteractionSequence(
        page_name=page_name,
        page_url=page_url,
        steps=steps,
        elements_summary=elements_summary,
    )


def _build_llm_sequence(
    ui_result: UIAnalysisResult,
    page_url: str,
    page_name: str,
    llm_client,
    image_path: Optional[Path] = None,
    description: str = "",
) -> UIInteractionSequence:
    pm = PromptManager()
    ui_info = pm.build_ui_elements_info(ui_result)

    cv_sequence = _build_cv_sequence(ui_result, page_url, page_name)
    cv_steps_text = ""
    for s in cv_sequence.steps:
        cv_steps_text += f"\n{s.step_number}. {s.action} -> {s.target} ({s.locator_strategy}: {s.locator_value})"

    image_b64 = ""
    if image_path and image_path.exists():
        image_b64 = _encode_image_base64(image_path)

    system_prompt, user_prompt = pm.build_prompt(
        "analyze_ui_interaction",
        page_url=page_url,
        page_name=page_name,
        ui_elements_info=ui_info,
        cv_steps=cv_steps_text,
        user_description=description,
    )

    raw = llm_client.generate(user_prompt, system_prompt=system_prompt)
    steps = _parse_interaction_steps(raw)

    elements_summary = []
    for btn in ui_result.action_buttons:
        elements_summary.append({
            "type": "button",
            "text": btn.text,
            "position": {"x": btn.bounding_box.x, "y": btn.bounding_box.y},
        })
    for field, label in ui_result.form_fields:
        label_text = label.text if label else (field.associated_label or field.text)
        elements_summary.append({
            "type": field.element_type.value,
            "text": label_text,
            "position": {"x": field.bounding_box.x, "y": field.bounding_box.y},
        })

    return UIInteractionSequence(
        page_name=page_name,
        page_url=page_url,
        steps=steps,
        elements_summary=elements_summary,
        raw_code=_extract_code_block(raw),
    )


def _parse_interaction_steps(raw: str) -> List[UIInteractionStep]:
    json_match = re.search(r"```json\s*\n(.*?)```", raw, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1).strip())
            steps_data = data.get("steps", [])
            result: List[UIInteractionStep] = []
            for i, s in enumerate(steps_data):
                result.append(UIInteractionStep(
                    step_number=i + 1,
                    action=s.get("action", ""),
                    target=s.get("target", ""),
                    target_type=s.get("target_type", ""),
                    locator_strategy=s.get("locator_strategy", ""),
                    locator_value=s.get("locator_value", ""),
                    input_value=s.get("input_value", ""),
                    description=s.get("description", ""),
                ))
            return result
        except (json.JSONDecodeError, KeyError):
            pass

    return _fallback_parse_steps(raw)


def _fallback_parse_steps(raw: str) -> List[UIInteractionStep]:
    steps: List[UIInteractionStep] = []
    patterns = [
        r"\d+\.\s*(.+?)(?:\n|$)",
        r"-\s*(.+?)(?:\n|$)",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, raw)
        if matches:
            for i, m in enumerate(matches):
                steps.append(UIInteractionStep(
                    step_number=i + 1,
                    action="interact",
                    target=m.strip(),
                    target_type="unknown",
                    locator_strategy="get_by_text",
                    locator_value=m.strip(),
                    description=m.strip(),
                ))
            return steps
    return steps


def _extract_code_block(raw: str) -> str:
    pattern = r"```(?:python|typescript|javascript)?\s*\n(.*?)```"
    match = re.search(pattern, raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _merge_cv_and_vision(
    cv_result: UIAnalysisResult,
    vision_result: VisionAnalysisResult,
    page_url: str,
    page_name: str,
) -> UIInteractionSequence:
    """合并CV检测结果和多模态大模型分析结果"""
    cv_sequence = _build_cv_sequence(cv_result, page_url, page_name)

    if not vision_result.interaction_sequences:
        return cv_sequence

    best_flow = vision_result.interaction_sequences[0]
    if best_flow.steps:
        merged_steps = []
        seen_targets = set()
        for step in best_flow.steps:
            key = f"{step.action}:{step.target}"
            if key not in seen_targets:
                seen_targets.add(key)
                merged_steps.append(step)

        for cv_step in cv_sequence.steps:
            key = f"{cv_step.action}:{cv_step.target}"
            if key not in seen_targets:
                seen_targets.add(key)
                merged_steps.append(cv_step)

        for i, step in enumerate(merged_steps):
            step.step_number = i + 1

        cv_sequence.steps = merged_steps

    if vision_result.elements:
        vision_elements = []
        for elem in vision_result.elements:
            if elem.is_interactive:
                vision_elements.append({
                    "type": elem.element_type,
                    "text": elem.text,
                    "position": elem.position or "",
                    "source": "vision",
                })

        for btn in cv_result.action_buttons:
            vision_elements.append({
                "type": "button",
                "text": btn.text,
                "position": {"x": btn.bounding_box.x, "y": btn.bounding_box.y},
                "source": "cv",
            })
        for field, label in cv_result.form_fields:
            label_text = label.text if label else (field.associated_label or field.text)
            vision_elements.append({
                "type": field.element_type.value,
                "text": label_text,
                "position": {"x": field.bounding_box.x, "y": field.bounding_box.y},
                "source": "cv",
            })

        cv_sequence.elements_summary = vision_elements

    return cv_sequence


class UIInteractionGenerator:
    def analyze(
        self,
        image_path: Path,
        page_url: str = "https://example.com",
        page_name: str = "page",
        ocr_lang: str = "chi_sim+eng",
    ) -> UIAnalysisResult:
        detector = UIElementDetector(ocr_lang=ocr_lang)
        return detector.analyze_screenshot(image_path)

    def generate_interaction_sequence(
        self,
        image_path: Path,
        page_url: str = "https://example.com",
        page_name: str = "page",
        llm_client=None,
        description: str = "",
        ocr_lang: str = "chi_sim+eng",
    ) -> UIInteractionSequence:
        ui_result = self.analyze(image_path, page_url, page_name, ocr_lang)

        if llm_client:
            return _build_llm_sequence(
                ui_result, page_url, page_name, llm_client,
                image_path=image_path,
                description=description,
            )

        return _build_cv_sequence(ui_result, page_url, page_name)

    def analyze_with_vision(
        self,
        image_path: Path,
        llm_client=None,
        additional_context: str = "",
    ) -> VisionAnalysisResult:
        """使用多模态大模型分析UI截图"""
        analyzer = MultimodalVisionAnalyzer(llm_client=llm_client)
        return analyzer.analyze_screenshot(image_path, additional_context=additional_context)

    def analyze_multiple_with_vision(
        self,
        image_paths: List[Path],
        llm_client=None,
        additional_context: str = "",
    ) -> VisionAnalysisResult:
        """使用多模态大模型分析多张UI截图"""
        analyzer = MultimodalVisionAnalyzer(llm_client=llm_client)
        return analyzer.analyze_multiple_screenshots(image_paths, additional_context=additional_context)

    def generate_interaction_sequence_vision(
        self,
        image_path: Path,
        page_url: str = "https://example.com",
        page_name: str = "page",
        llm_client=None,
        description: str = "",
        ocr_lang: str = "chi_sim+eng",
    ) -> UIInteractionSequence:
        """使用CV+多模态大模型混合模式生成交互序列"""
        cv_result = self.analyze(image_path, page_url, page_name, ocr_lang)

        if llm_client:
            vision_result = self.analyze_with_vision(
                image_path, llm_client=llm_client,
                additional_context=description,
            )
            return _merge_cv_and_vision(cv_result, vision_result, page_url, page_name)

        return _build_cv_sequence(cv_result, page_url, page_name)

    def generate_multi_page_interaction_vision(
        self,
        image_paths: List[Path],
        page_url: str = "https://example.com",
        page_name: str = "page",
        llm_client=None,
        description: str = "",
    ) -> VisionAnalysisResult:
        """多张截图的多模态分析，生成跨页面交互流程"""
        analyzer = MultimodalVisionAnalyzer(llm_client=llm_client)
        return analyzer.analyze_multiple_screenshots(
            image_paths, additional_context=description,
        )
