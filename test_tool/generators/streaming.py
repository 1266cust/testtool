from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Generator, Tuple, Any

from ..core.models import TestCase
from ..core.logging import get_logger

logger = get_logger("generators.streaming")

_generation_states: Dict[str, "GenerationState"] = {}
_lock = threading.Lock()


@dataclass
class GenerationProgress:
    pct: float = 0.0
    message: str = ""
    phase: str = "init"
    cases_count: int = 0
    total_estimate: int = 0
    partial_cases: List[dict] = field(default_factory=list)
    error: str = ""
    job_id: str = ""


@dataclass
class GenerationState:
    job_id: str
    cancelled: bool = False
    progress: GenerationProgress = field(default_factory=GenerationProgress)
    output_dir: Optional[Path] = None
    _start_time: float = field(default_factory=time.time)

    CHECKPOINT_FILE = "partial_cases.jsonl"
    CANCEL_FILE = ".cancelled"

    def cancel(self):
        self.cancelled = True
        if self.output_dir:
            try:
                (self.output_dir / self.CANCEL_FILE).touch()
            except Exception:
                pass
        logger.info(f"Generation cancelled: {self.job_id}")

    def is_cancelled(self) -> bool:
        if self.cancelled:
            return True
        if self.output_dir and (self.output_dir / self.CANCEL_FILE).exists():
            self.cancelled = True
            return True
        return False

    @property
    def elapsed(self) -> float:
        return time.time() - self._start_time

    def save_checkpoint(self, cases: List[TestCase]):
        if not self.output_dir:
            return
        try:
            cp = self.output_dir / self.CHECKPOINT_FILE
            with open(str(cp), "w", encoding="utf-8") as f:
                for c in cases:
                    f.write(json.dumps(case_to_dict(c), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Checkpoint save failed: {e}")

    def load_checkpoint(self) -> List[TestCase]:
        if not self.output_dir:
            return []
        try:
            cp = self.output_dir / self.CHECKPOINT_FILE
            if not cp.exists():
                return []
            cases = []
            with open(str(cp), "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        d = json.loads(line)
                        cases.append(dict_to_case(d))
            return cases
        except Exception as e:
            logger.warning(f"Checkpoint load failed: {e}")
            return []

    def clear_checkpoint(self):
        if not self.output_dir:
            return
        try:
            cp = self.output_dir / self.CHECKPOINT_FILE
            if cp.exists():
                cp.unlink()
        except Exception as e:
            logger.warning(f"Checkpoint clear failed: {e}")


def case_to_dict(c: TestCase) -> dict:
    return {
        "case_id": c.case_id,
        "module": c.module,
        "name": c.name,
        "acceptance_purpose": c.acceptance_purpose,
        "preconditions": c.preconditions,
        "steps": c.steps,
        "expected_result": c.expected_result,
        "case_type": c.case_type,
        "priority": c.priority,
    }


def dict_to_case(d: dict) -> TestCase:
    return TestCase(
        case_id=d.get("case_id", ""),
        module=d.get("module", ""),
        name=d.get("name", ""),
        acceptance_purpose=d.get("acceptance_purpose", ""),
        preconditions=d.get("preconditions", ""),
        steps=d.get("steps", ""),
        expected_result=d.get("expected_result", ""),
        case_type=d.get("case_type", "功能测试"),
        priority=d.get("priority", "P1"),
    )


def create_state(job_id: str, output_dir: Optional[Path] = None) -> GenerationState:
    state = GenerationState(job_id=job_id, output_dir=output_dir)
    state.progress.job_id = job_id
    with _lock:
        _generation_states[job_id] = state
    return state


def get_state(job_id: str) -> Optional[GenerationState]:
    with _lock:
        return _generation_states.get(job_id)


def remove_state(job_id: str):
    with _lock:
        _generation_states.pop(job_id, None)


def format_sse(event: str, data: Any) -> str:
    """Format data as SSE event"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def streaming_generate_template(
    path: Path,
    cfg: Any,
    min_cases: int,
    state: GenerationState,
    case_index_offset: int = 0,
) -> Generator[str, None, List[TestCase]]:
    from ..parsers.image_parser import extract_text_from_file, analyze_ui_image
    from ..utils.file_utils import is_image_file
    from .heading_parser import parse_headings
    from .case_generator import (
        _iter_supported_files, sections_to_test_cases,
        generate_ui_element_test_cases, expand_to_min_cases,
    )

    all_cases: List[TestCase] = []
    processed_files = 0
    total_files = sum(1 for _ in _iter_supported_files(path)) or 1

    for one_file in _iter_supported_files(path):
        if state.is_cancelled():
            yield format_sse("cancelled", {"job_id": state.job_id, "cases_count": len(all_cases)})
            return all_cases

        processed_files += 1
        pct = round(processed_files / total_files * 60, 1)
        logger.info("Streaming template processing: " + str(one_file))

        if is_image_file(one_file):
            ui_result = analyze_ui_image(one_file)
            ui_cases = generate_ui_element_test_cases(ui_result, cfg)
            for c in ui_cases:
                c.case_id = f"TEMP-{case_index_offset + len(all_cases) + 1:05d}"
                all_cases.append(c)
            if ui_cases:
                yield format_sse("progress", {
                    "job_id": state.job_id,
                    "pct": pct,
                    "message": f"已处理图片 {one_file.name}，生成 {len(ui_cases)} 条UI用例",
                    "cases_count": len(all_cases),
                    "phase": "template",
                })

        text = extract_text_from_file(one_file)
        if text.strip():
            sections = parse_headings(text)
            file_cases = sections_to_test_cases(sections, cfg)
            for c in file_cases:
                c.case_id = f"TEMP-{case_index_offset + len(all_cases) + 1:05d}"
                all_cases.append(c)
            if file_cases:
                yield format_sse("progress", {
                    "job_id": state.job_id,
                    "pct": pct,
                    "message": f"已处理文档 {one_file.name}，生成 {len(file_cases)} 条用例",
                    "cases_count": len(all_cases),
                    "phase": "template",
                })

    if state.is_cancelled():
        yield format_sse("cancelled", {"job_id": state.job_id, "cases_count": len(all_cases)})
        return all_cases

    expanded = expand_to_min_cases(all_cases, min_cases=min_cases)
    for i, c in enumerate(expanded, start=1):
        c.case_id = f"TC-{case_index_offset + i:06d}"

    yield format_sse("progress", {
        "job_id": state.job_id,
        "pct": 90,
        "message": f"已扩展至 {len(expanded)} 条用例",
        "cases_count": len(expanded),
        "phase": "expand",
    })

    state.save_checkpoint(expanded)
    return expanded


def streaming_generate_llm(
    path: Path,
    cfg: Any,
    min_cases: int,
    state: GenerationState,
    case_index_offset: int = 0,
) -> Generator[str, None, List[TestCase]]:
    from ..llm.client import LLMClient, LLMConfig
    from ..llm.config_loader import load_llm_config_from_env
    from ..parsers.image_parser import extract_text_from_file, analyze_ui_image
    from ..utils.file_utils import is_image_file
    from .heading_parser import parse_headings
    from .test_point_analyzer import TestPointAnalyzer
    from .smart_generator import SmartCaseGenerator, GenerationContext
    from .case_generator import _iter_supported_files, _merge_test_points, _generate_with_template, expand_to_min_cases

    llm_config = LLMConfig(
        provider=cfg.llm_config.provider,
        model_name=cfg.llm_config.model_name,
        api_key=cfg.llm_config.api_key,
        base_url=cfg.llm_config.base_url,
        max_tokens=cfg.llm_config.max_tokens,
        temperature=cfg.llm_config.temperature,
        vision_provider=getattr(cfg.llm_config, 'vision_provider', None),
        vision_model_name=getattr(cfg.llm_config, 'vision_model_name', None),
        vision_api_key=getattr(cfg.llm_config, 'vision_api_key', None),
        vision_base_url=getattr(cfg.llm_config, 'vision_base_url', None),
    )

    if not llm_config.api_key:
        env_config = load_llm_config_from_env()
        llm_config.api_key = env_config.api_key
        llm_config.base_url = llm_config.base_url or env_config.base_url
        llm_config.provider = llm_config.provider or env_config.provider

    if not llm_config.api_key:
        yield format_sse("error", {"job_id": state.job_id, "error": "LLM API Key 未配置"})
        return []

    llm_client = LLMClient(llm_config)

    yield format_sse("progress", {
        "job_id": state.job_id,
        "pct": 5,
        "message": "正在解析需求文档和截图...",
        "cases_count": 0,
        "phase": "parsing",
    })

    all_sections = []
    ui_results = {}
    image_paths = []
    for one_file in _iter_supported_files(path):
        if state.is_cancelled():
            yield format_sse("cancelled", {"job_id": state.job_id, "cases_count": 0})
            return []
        if is_image_file(one_file):
            ui_result = analyze_ui_image(one_file)
            ui_results[one_file.stem] = ui_result
            image_paths.append(one_file)
        text = extract_text_from_file(one_file)
        if text.strip():
            sections = parse_headings(text)
            all_sections.extend(sections)

    if state.is_cancelled():
        yield format_sse("cancelled", {"job_id": state.job_id, "cases_count": 0})
        return []

    vision_test_points = []
    if image_paths and llm_config.has_vision_model:
        if state.is_cancelled():
            yield format_sse("cancelled", {"job_id": state.job_id, "cases_count": 0})
            return []
        from ..ocr.multimodal_vision import MultimodalVisionAnalyzer
        vision_llm_client = LLMClient(llm_config.get_vision_config())
        vision_analyzer = MultimodalVisionAnalyzer(llm_client=vision_llm_client)
        for img_path in image_paths:
            if state.is_cancelled():
                yield format_sse("cancelled", {"job_id": state.job_id, "cases_count": 0})
                return []
            yield format_sse("progress", {
                "job_id": state.job_id,
                "pct": 10,
                "message": f"正在用多模态识别图片 {img_path.name}...",
                "cases_count": 0,
                "phase": "vision",
            })
            try:
                v_points = vision_analyzer.extract_test_points(img_path, module_name=img_path.stem)
                vision_test_points.extend(v_points)
            except Exception as exc:
                logger.warning(f"Vision extraction failed: {exc}")

    yield format_sse("progress", {
        "job_id": state.job_id,
        "pct": 15,
        "message": "正在分析测试点...",
        "cases_count": 0,
        "phase": "analyze",
    })

    text_test_points = []
    module_analyses = {}
    if all_sections:
        analyzer = TestPointAnalyzer(llm_client)
        text_test_points, module_analyses = analyzer.analyze_all_sections(all_sections, ui_results)

    all_test_points = _merge_test_points(text_test_points, vision_test_points)
    total_points = len(all_test_points) or 1

    yield format_sse("progress", {
        "job_id": state.job_id,
        "pct": 20,
        "message": f"已识别 {len(all_test_points)} 个测试点，开始生成用例...",
        "cases_count": 0,
        "phase": "generating",
    })

    generator = SmartCaseGenerator(llm_client)
    all_cases: List[TestCase] = []
    case_index = 1

    for idx, point in enumerate(all_test_points):
        if state.is_cancelled():
            yield format_sse("cancelled", {"job_id": state.job_id, "cases_count": len(all_cases)})
            return all_cases

        related_section = None
        for title, sec in {s.title: s for s in all_sections}.items():
            if point.related_requirement == title or point.point_name in title or title in point.point_name:
                related_section = sec
                break

        requirement_context = "\n".join(related_section.content) if related_section else ""
        context = GenerationContext(
            module_name=point.module_name,
            test_point=point,
            requirement_context=requirement_context,
            system_config=cfg,
            knowledge_context="",
        )

        try:
            cases = generator.generate_for_test_point(context)
        except Exception as exc:
            logger.warning(f"Failed to generate cases for point {point.point_name}: {exc}")
            cases = []

        for c in cases:
            c.case_id = f"TC-{case_index:06d}"
            case_index += 1
            all_cases.append(c)

        pct = round(20 + (idx + 1) / total_points * 60, 1)
        yield format_sse("progress", {
            "job_id": state.job_id,
            "pct": pct,
            "message": f"测试点 [{idx+1}/{total_points}] {point.point_name} 完成，生成 {len(cases)} 条用例",
            "cases_count": len(all_cases),
            "partial_cases": [case_to_dict(c) for c in cases],
            "phase": "generating",
        })

        state.save_checkpoint(all_cases)

    if state.is_cancelled():
        yield format_sse("cancelled", {"job_id": state.job_id, "cases_count": len(all_cases)})
        return all_cases

    if len(all_cases) < min_cases:
        yield format_sse("progress", {
            "job_id": state.job_id,
            "pct": 85,
            "message": f"当前 {len(all_cases)} 条，不足 {min_cases} 条，补充模板用例...",
            "cases_count": len(all_cases),
            "phase": "supplement",
        })
        try:
            template_cases = _generate_with_template(path, 0, cfg)
            for c in template_cases:
                c.case_id = f"TC-{case_index:06d}"
                case_index += 1
                all_cases.append(c)
        except Exception as exc:
            logger.warning(f"Template supplement failed: {exc}")

    all_cases = expand_to_min_cases(all_cases, min_cases=min_cases)
    for i, c in enumerate(all_cases, start=1):
        c.case_id = f"TC-{i:06d}"

    state.save_checkpoint(all_cases)

    return all_cases