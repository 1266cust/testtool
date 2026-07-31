from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from zipfile import ZipFile

from flask import Flask, abort, jsonify, render_template, request, send_file

from .exporters import export_cases_to_csv, export_cases_to_excel, export_cases_to_word
from .generators import parse_requirement_path, generate_with_llm
from .generators.code_generator import AutomationCodeGenerator
from .generators.ui_interaction_generator import UIInteractionGenerator
from .core.config import GenerationConfig, LLMGenerationConfig
from .core.logging import setup_logging, get_logger
from .core.models import ReviewResult
from .utils.file_utils import SUPPORTED_EXTENSIONS, IMAGE_EXTENSIONS
from .parsers.image_parser import analyze_ui_image
from .llm.config_loader import load_llm_config

# 知识库服务（可选导入）
try:
    from .knowledge.service import get_knowledge_service
    from .knowledge.models import Project, KnowledgeDocument
    HAS_KNOWLEDGE = True
except ImportError:
    HAS_KNOWLEDGE = False
    get_knowledge_service = None
    Project = None
    KnowledgeDocument = None

logger = get_logger("web")

BASE_DIR = Path(__file__).resolve().parents[1]
UPLOAD_ROOT = BASE_DIR / "out" / "web_uploads"
OUTPUT_ROOT = BASE_DIR / "out" / "web_outputs"

ALLOWED_EXTENSIONS_WEB = SUPPORTED_EXTENSIONS

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


def _safe_name(filename: str) -> str:
    return Path(filename).name


def validate_upload_file(file) -> tuple[bool, str]:
    """验证上传文件的安全性。"""
    if not file or not file.filename:
        return False, "未提供文件"

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS_WEB:
        return False, "文件类型 '" + ext + "' 不允许上传"

    return True, ""


@app.get("/")
def index():
    llm_config = load_llm_config()
    llm_available = llm_config.api_key is not None and len(llm_config.api_key) > 10

    # 获取项目列表
    projects = []
    if HAS_KNOWLEDGE:
        try:
            ks = get_knowledge_service()
            projects = ks.list_projects()
        except Exception as e:
            logger.warning(f"Failed to load projects: {e}")

    return render_template(
        "index.html",
        llm_available=llm_available,
        projects=projects,
        has_knowledge=HAS_KNOWLEDGE,
    )


@app.post("/generate")
def generate():
    requirement_text = request.form.get("requirement_text", "").strip()
    project_id = request.form.get("project_id", "").strip()

    uploaded_docs = request.files.getlist("requirement_files")
    uploaded_images = request.files.getlist("image_files")
    output_format = request.form.get("output_format", "both")
    min_cases_raw = request.form.get("min_cases", "300").strip()

    generation_mode = request.form.get("generation_mode", "smart")
    enable_review = request.form.get("enable_review") == "on"
    enable_auto_fix = request.form.get("enable_auto_fix") == "on"

    # 提前加载LLM配置，用于所有render_template
    llm_env_config = load_llm_config()
    llm_available = llm_env_config.api_key is not None and len(llm_env_config.api_key) > 10

    if output_format not in {"excel", "csv", "word", "excel+word"}:
        return render_template(
            "index.html",
            error="输出格式参数无效。",
            requirement_text=requirement_text,
            llm_available=llm_available,
        )

    try:
        min_cases = max(1, int(min_cases_raw))
    except ValueError:
        return render_template(
            "index.html",
            error="最少用例条数必须是整数。",
            requirement_text=requirement_text,
            llm_available=llm_available,
        )

    job_id = uuid.uuid4().hex[:12]
    upload_dir = UPLOAD_ROOT / job_id
    output_dir = OUTPUT_ROOT / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_files: list[str] = []
    validation_errors: list[str] = []

    for f in uploaded_docs:
        if not f or not f.filename:
            continue

        is_valid, error_msg = validate_upload_file(f)
        if not is_valid:
            validation_errors.append(f.filename + ": " + error_msg)
            continue

        safe_filename = _safe_name(f.filename)
        if not safe_filename:
            continue
        target = upload_dir / safe_filename
        f.save(str(target))
        saved_files.append(safe_filename)
        logger.info("Saved doc file: " + safe_filename)

    for f in uploaded_images:
        if not f or not f.filename:
            continue

        is_valid, error_msg = validate_upload_file(f)
        if not is_valid:
            validation_errors.append(f.filename + ": " + error_msg)
            continue

        safe_filename = _safe_name(f.filename)
        if not safe_filename:
            continue
        target = upload_dir / safe_filename
        f.save(str(target))
        saved_files.append(safe_filename)
        logger.info("Saved image file: " + safe_filename)

    if requirement_text and not saved_files:
        text_file = upload_dir / "user_input.txt"
        text_file.write_text(requirement_text, encoding="utf-8")
        saved_files.append("user_input.txt")
        logger.info("Saved user text input")

    if validation_errors:
        logger.warning("Validation errors: " + "; ".join(validation_errors))

    if not saved_files:
        shutil.rmtree(upload_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
        error_msg = "请输入需求描述或上传文件。"
        if validation_errors:
            error_msg += " 原因：" + "; ".join(validation_errors)
        return render_template(
            "index.html",
            error=error_msg,
            requirement_text=requirement_text,
            llm_available=llm_available,
        )

    llm_config = LLMGenerationConfig(
        enabled=generation_mode == "smart",
        api_key=llm_env_config.api_key,
        base_url=llm_env_config.base_url,
        provider=llm_env_config.provider,
        model_name=llm_env_config.model_name,
    )

    cfg = GenerationConfig(
        llm_config=llm_config,
        review_enabled=enable_review,
        auto_fix_enabled=enable_auto_fix,
    )

    try:
        use_llm = generation_mode == "smart" and llm_config.api_key is not None
        cases = parse_requirement_path(
            upload_dir,
            min_cases=min_cases,
            cfg=cfg,
            use_llm=use_llm,
            project_id=project_id,
        )
        logger.info("Generated " + str(len(cases)) + " test cases for job " + job_id)
    except Exception as exc:
        logger.error("Failed to parse requirements: " + str(exc))
        return render_template(
            "index.html",
            error="解析失败：" + str(exc),
            requirement_text=requirement_text,
            llm_available=llm_available,
        )

    if not cases:
        return render_template(
            "index.html",
            error="未从输入内容中解析出测试用例。",
            requirement_text=requirement_text,
            llm_available=llm_available,
        )

    review_result = None
    fix_summary = None
    modified_cases = []

    if enable_review and len(cases) > 0:
        review_result = _perform_review(cases, requirement_text, cfg, llm_env_config)

        if enable_auto_fix and review_result:
            cases, fix_summary, modified_cases = _perform_auto_fix(
                cases, review_result, requirement_text, cfg, llm_env_config
            )

    generated_files: list[Path] = []
    if output_format in {"excel", "excel+word"}:
        generated_files.append(export_cases_to_excel(cases, output_dir / "test_cases.xlsx"))
    if output_format == "csv":
        generated_files.append(export_cases_to_csv(cases, output_dir / "test_cases.csv"))
    if output_format in {"word", "excel+word"}:
        generated_files.append(export_cases_to_word(cases, output_dir / "test_cases.docx"))

    download_items: list[dict[str, str]] = []
    if output_format == "excel+word":
        zip_path = output_dir / "test_cases_bundle.zip"
        with ZipFile(zip_path, "w") as zip_file:
            for one in generated_files:
                zip_file.write(one, arcname=one.name)
        download_items.append(
            {
                "name": zip_path.name,
                "url": "/download/" + job_id + "/" + zip_path.name,
            }
        )
    else:
        for one in generated_files:
            download_items.append(
                {
                    "name": one.name,
                    "url": "/download/" + job_id + "/" + one.name,
                }
            )

    success_msg = "已生成 " + str(len(cases)) + " 条测试用例。"
    if generation_mode == "smart":
        success_msg += "（智能生成模式）"
    has_images = any(
        Path(f.filename).suffix.lower() in IMAGE_EXTENSIONS
        for f in uploaded_images if f and f.filename
    )
    if has_images:
        success_msg += "（含UI截图识别）"
    if project_id:
        success_msg += f"（参考项目知识库）"
    if fix_summary:
        success_msg += " " + fix_summary

    # 获取项目列表用于渲染
    projects = []
    if HAS_KNOWLEDGE:
        try:
            ks = get_knowledge_service()
            projects = ks.list_projects()
        except Exception:
            pass

    return render_template(
        "index.html",
        success=success_msg,
        downloads=download_items,
        requirement_text=requirement_text,
        review_result=review_result,
        modified_cases=modified_cases,
        generation_mode=generation_mode,
        llm_available=llm_available,
        projects=projects,
        has_knowledge=HAS_KNOWLEDGE,
        selected_project_id=project_id,
    )


def _perform_review(
    cases: list,
    requirement_context: str,
    cfg: GenerationConfig,
    llm_env_config,
) -> ReviewResult:
    """执行用例评审"""
    from .llm.client import LLMClient, LLMConfig
    from .review.reviewer import TestCaseReviewer

    if not llm_env_config.api_key:
        logger.warning("LLM API key not available for review")
        return None

    llm_config = LLMConfig(
        provider=llm_env_config.provider,
        model_name=llm_env_config.model_name,
        api_key=llm_env_config.api_key,
        base_url=llm_env_config.base_url,
    )
    llm_client = LLMClient(llm_config)

    reviewer = TestCaseReviewer(llm_client)

    module_name = ""
    if cases:
        module_name = cases[0].module

    try:
        result = reviewer.review_cases(cases, requirement_context, module_name)
        logger.info(f"Review completed with score: {result.overall_score}")
        return result
    except Exception as e:
        logger.error(f"Review failed: {e}")
        return None


def _perform_auto_fix(
    cases: list,
    review_result: ReviewResult,
    requirement_context: str,
    cfg: GenerationConfig,
    llm_env_config,
) -> tuple[list, str, list]:
    """执行自动修复"""
    from .llm.client import LLMClient, LLMConfig
    from .review.auto_fixer import AutoFixer

    llm_client = None
    if llm_env_config.api_key:
        llm_config = LLMConfig(
            provider=llm_env_config.provider,
            model_name=llm_env_config.model_name,
            api_key=llm_env_config.api_key,
            base_url=llm_env_config.base_url,
        )
        llm_client = LLMClient(llm_config)

    fixer = AutoFixer(llm_client)

    module_name = ""
    if cases:
        module_name = cases[0].module

    try:
        fixed_result = fixer.apply_fixes(cases, review_result, requirement_context, module_name)
        logger.info(f"Auto-fix completed: {fixed_result.fix_summary}")
        return fixed_result.cases, fixed_result.fix_summary, fixed_result.modified_cases
    except Exception as e:
        logger.error(f"Auto-fix failed: {e}")
        return cases, "", []


@app.post("/generate-code")
def generate_code():
    page_url = request.form.get("page_url", "https://example.com").strip()
    page_name = request.form.get("page_name", "page").strip() or "page"
    generation_mode = request.form.get("code_generation_mode", "template")
    code_description = request.form.get("code_description", "").strip()

    uploaded_images = request.files.getlist("code_image_files")
    project_zip = request.files.get("project_zip_file")
    project_path = request.form.get("project_path", "").strip()

    llm_env_config = load_llm_config()
    llm_available = llm_env_config.api_key is not None and len(llm_env_config.api_key) > 10

    projects = []
    if HAS_KNOWLEDGE:
        try:
            ks = get_knowledge_service()
            projects = ks.list_projects()
        except Exception:
            pass

    job_id = uuid.uuid4().hex[:12]
    upload_dir = UPLOAD_ROOT / job_id
    output_dir = OUTPUT_ROOT / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_images: list[Path] = []

    # handle pasted images from clipboard
    pasted_images = request.files.getlist("code_pasted_images")
    for f in pasted_images:
        if not f or not f.filename:
            continue
        safe_filename = _safe_name(f.filename)
        if not safe_filename:
            continue
        ext = Path(safe_filename).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue
        target = upload_dir / safe_filename
        f.save(str(target))
        saved_images.append(target)

    for f in uploaded_images:
        if not f or not f.filename:
            continue
        safe_filename = _safe_name(f.filename)
        if not safe_filename:
            continue
        ext = Path(safe_filename).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue
        target = upload_dir / safe_filename
        f.save(str(target))
        saved_images.append(target)

    if not saved_images and not code_description:
        shutil.rmtree(upload_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
        return render_template(
            "index.html",
            code_error="请输入页面描述或上传至少一张网页截图。",
            llm_available=llm_available,
            projects=projects,
            has_knowledge=HAS_KNOWLEDGE,
            active_tab="code",
        )

    # --- Project import handling ---
    project_context = None
    project_dir = upload_dir / "project"

    if project_zip and project_zip.filename:
        zip_safe_name = _safe_name(project_zip.filename)
        if zip_safe_name and Path(zip_safe_name).suffix.lower() == ".zip":
            zip_path = upload_dir / zip_safe_name
            project_zip.save(str(zip_path))
            project_dir.mkdir(parents=True, exist_ok=True)
            try:
                from .generators.project_analyzer import extract_project_zip, analyze_project
                project_root = extract_project_zip(zip_path, project_dir)
                project_context = analyze_project(project_root)
                logger.info("Project analyzed: " + project_context.analysis_summary)
            except Exception as exc:
                logger.warning("Project analysis failed: " + str(exc))

    elif project_path:
        project_root = Path(project_path)
        if project_root.is_dir():
            try:
                from .generators.project_analyzer import analyze_project
                project_context = analyze_project(project_root)
                logger.info("Project analyzed: " + project_context.analysis_summary)
            except Exception as exc:
                logger.warning("Project analysis failed: " + str(exc))
        else:
            logger.warning("Project path not found: " + project_path)

    try:
        from .core.models import UIAnalysisResult

        combined_ui = None
        for img_path in saved_images:
            ui_result = analyze_ui_image(img_path)
            if combined_ui is None:
                combined_ui = ui_result
            else:
                combined_ui.elements.extend(ui_result.elements)
                combined_ui.action_buttons.extend(ui_result.action_buttons)
                combined_ui.form_fields.extend(ui_result.form_fields)
                combined_ui.ocr_results.extend(ui_result.ocr_results)
                if ui_result.full_text:
                    combined_ui.full_text += "\n" + ui_result.full_text

        if combined_ui is None:
            combined_ui = UIAnalysisResult(
                elements=[], action_buttons=[], form_fields=[],
                ocr_results=[], full_text="", detected_shapes=[],
            )

        if code_description:
            combined_ui.full_text = (
                (combined_ui.full_text + "\n" if combined_ui.full_text else "")
                + "用户补充描述：" + code_description
            )

        if (
            not combined_ui.action_buttons
            and not combined_ui.form_fields
            and not code_description
        ):
            return render_template(
                "index.html",
                code_error="未从截图中检测到可交互的UI元素，请上传包含按钮、输入框等元素的网页截图，或输入页面描述。",
                llm_available=llm_available,
                projects=projects,
                has_knowledge=HAS_KNOWLEDGE,
                active_tab="code",
            )

        generator = AutomationCodeGenerator()

        if generation_mode == "smart" and llm_available:
            from .llm.client import LLMClient, LLMConfig
            llm_config = LLMConfig(
                provider=llm_env_config.provider,
                model_name=llm_env_config.model_name,
                api_key=llm_env_config.api_key,
                base_url=llm_env_config.base_url,
            )
            llm_client = LLMClient(llm_config)
            result = generator.generate_code_with_llm(
                combined_ui, page_url, page_name, llm_client,
                project_context=project_context,
            )
        else:
            result = generator.generate_code(
                combined_ui, page_url, page_name,
                project_context=project_context,
            )

        code_file = output_dir / f"test_{page_name}.py"
        code_file.write_text(result.code, encoding="utf-8")

        elem_count = len(combined_ui.action_buttons) + len(combined_ui.form_fields)
        success_msg = (
            "已生成自动化测试代码，检测到 "
            + str(elem_count) + " 个UI元素（"
            + str(len(combined_ui.action_buttons)) + " 个按钮、"
            + str(len(combined_ui.form_fields)) + " 个表单字段）。"
        )

        return render_template(
            "index.html",
            code_success=success_msg,
            generated_code=result.code,
            recommended_path=result.recommended_file_path,
            integration_instructions=result.integration_instructions,
            imports_to_add=result.imports_to_add,
            files_to_modify=result.files_to_modify,
            has_project_context=project_context is not None,
            code_download_url="/download/" + job_id + "/" + code_file.name,
            code_download_name=code_file.name,
            llm_available=llm_available,
            projects=projects,
            has_knowledge=HAS_KNOWLEDGE,
            active_tab="code",
        )

    except Exception as exc:
        logger.error("Code generation failed: " + str(exc))
        return render_template(
            "index.html",
            code_error="代码生成失败：" + str(exc),
            llm_available=llm_available,
            projects=projects,
            has_knowledge=HAS_KNOWLEDGE,
            active_tab="code",
        )


@app.get("/download/<job_id>/<filename>")
def download(job_id: str, filename: str):
    if not job_id.isalnum():
        abort(404)
    safe_filename = _safe_name(filename)
    target = OUTPUT_ROOT / job_id / safe_filename
    if not target.exists() or not target.is_file():
        abort(404)
    return send_file(target, as_attachment=True, download_name=safe_filename)


@app.post("/analyze-ui-vision")
def analyze_ui_vision():
    """多模态大模型分析UI截图，识别页面元素和交互流程"""
    uploaded_images = request.files.getlist("vision_image_files")
    pasted_images = request.files.getlist("vision_pasted_images")
    analysis_mode = request.form.get("vision_analysis_mode", "vision")
    additional_context = request.form.get("vision_context", "").strip()

    llm_env_config = load_llm_config()
    llm_available = llm_env_config.api_key is not None and len(llm_env_config.api_key) > 10

    projects = []
    if HAS_KNOWLEDGE:
        try:
            ks = get_knowledge_service()
            projects = ks.list_projects()
        except Exception:
            pass

    job_id = uuid.uuid4().hex[:12]
    upload_dir = UPLOAD_ROOT / job_id
    output_dir = OUTPUT_ROOT / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_images: list[Path] = []

    for f in pasted_images:
        if not f or not f.filename:
            continue
        safe_filename = _safe_name(f.filename)
        if not safe_filename:
            continue
        ext = Path(safe_filename).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue
        target = upload_dir / safe_filename
        f.save(str(target))
        saved_images.append(target)

    for f in uploaded_images:
        if not f or not f.filename:
            continue
        safe_filename = _safe_name(f.filename)
        if not safe_filename:
            continue
        ext = Path(safe_filename).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue
        target = upload_dir / safe_filename
        f.save(str(target))
        saved_images.append(target)

    if not saved_images:
        shutil.rmtree(upload_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
        return render_template(
            "index.html",
            vision_error="请上传至少一张UI截图或原型图。",
            llm_available=llm_available,
            projects=projects,
            has_knowledge=HAS_KNOWLEDGE,
            active_tab="vision",
        )

    try:
        if analysis_mode == "vision" and llm_available:
            from .llm.client import LLMClient, LLMConfig
            llm_config = LLMConfig(
                provider=llm_env_config.provider,
                model_name=llm_env_config.model_name,
                api_key=llm_env_config.api_key,
                base_url=llm_env_config.base_url,
            )
            llm_client = LLMClient(llm_config)

            generator = UIInteractionGenerator()
            if len(saved_images) == 1:
                vision_result = generator.analyze_with_vision(
                    saved_images[0],
                    llm_client=llm_client,
                    additional_context=additional_context,
                )
            else:
                vision_result = generator.analyze_multiple_with_vision(
                    saved_images,
                    llm_client=llm_client,
                    additional_context=additional_context,
                )

            interaction_json = json.dumps(
                vision_result.to_dict(), ensure_ascii=False, indent=2
            )

            interaction_file = output_dir / "vision_analysis.json"
            interaction_file.write_text(interaction_json, encoding="utf-8")

            interactive_count = len([e for e in vision_result.elements if e.is_interactive])
            flow_count = len(vision_result.interaction_sequences)
            page_flow_count = len(vision_result.page_flows)

            success_msg = (
                f"多模态分析完成，识别到 {len(vision_result.elements)} 个UI元素"
                f"（{interactive_count} 个可交互），"
                f"{flow_count} 个交互流程，"
                f"{page_flow_count} 个页面跳转。"
            )

            return render_template(
                "index.html",
                vision_success=success_msg,
                vision_result=vision_result,
                vision_download_url="/download/" + job_id + "/vision_analysis.json",
                llm_available=llm_available,
                projects=projects,
                has_knowledge=HAS_KNOWLEDGE,
                active_tab="vision",
            )

        elif analysis_mode == "hybrid" and llm_available:
            from .llm.client import LLMClient, LLMConfig
            llm_config = LLMConfig(
                provider=llm_env_config.provider,
                model_name=llm_env_config.model_name,
                api_key=llm_env_config.api_key,
                base_url=llm_env_config.base_url,
            )
            llm_client = LLMClient(llm_config)

            generator = UIInteractionGenerator()
            cv_result = generator.analyze(saved_images[0])

            vision_result = generator.analyze_with_vision(
                saved_images[0],
                llm_client=llm_client,
                additional_context=additional_context,
            )

            merged = _merge_vision_with_cv(vision_result, cv_result)

            interaction_json = json.dumps(
                merged.to_dict(), ensure_ascii=False, indent=2
            )
            interaction_file = output_dir / "hybrid_analysis.json"
            interaction_file.write_text(interaction_json, encoding="utf-8")

            interactive_count = len([e for e in merged.elements if e.is_interactive])
            success_msg = (
                f"混合分析完成（CV+多模态），识别到 {len(merged.elements)} 个UI元素"
                f"（{interactive_count} 个可交互），"
                f"{len(merged.interaction_sequences)} 个交互流程。"
            )

            return render_template(
                "index.html",
                vision_success=success_msg,
                vision_result=merged,
                vision_download_url="/download/" + job_id + "/hybrid_analysis.json",
                llm_available=llm_available,
                projects=projects,
                has_knowledge=HAS_KNOWLEDGE,
                active_tab="vision",
            )

        else:
            generator = UIInteractionGenerator()
            cv_result = generator.analyze(saved_images[0])

            cv_elements = []
            for btn in cv_result.action_buttons:
                cv_elements.append({
                    "element_type": "button",
                    "text": btn.text,
                    "is_interactive": True,
                })
            for field, label in cv_result.form_fields:
                label_text = label.text if label else (field.associated_label or field.text)
                cv_elements.append({
                    "element_type": field.element_type.value,
                    "text": label_text,
                    "is_interactive": True,
                })

            vision_result = VisionAnalysisResult(
                page_description=cv_result.full_text[:200] if cv_result.full_text else "",
                page_type="unknown",
                elements=[],
                interaction_sequences=[],
                page_flows=[],
            )

            for elem_data in cv_elements:
                vision_result.elements.append(
                    __import__("test_tool.core.models", fromlist=["UIVisionElement"]).UIVisionElement(
                        element_type=elem_data["element_type"],
                        text=elem_data["text"],
                        description="",
                        is_interactive=elem_data["is_interactive"],
                        locator_strategy="get_by_role",
                        locator_value=elem_data["text"],
                        suggested_action="click" if elem_data["element_type"] == "button" else "fill",
                    )
                )

            interaction_json = json.dumps(
                vision_result.to_dict(), ensure_ascii=False, indent=2
            )
            interaction_file = output_dir / "cv_analysis.json"
            interaction_file.write_text(interaction_json, encoding="utf-8")

            success_msg = (
                f"CV分析完成，识别到 {len(cv_result.action_buttons)} 个按钮，"
                f"{len(cv_result.form_fields)} 个表单字段。"
            )

            return render_template(
                "index.html",
                vision_success=success_msg,
                vision_result=vision_result,
                vision_download_url="/download/" + job_id + "/cv_analysis.json",
                llm_available=llm_available,
                projects=projects,
                has_knowledge=HAS_KNOWLEDGE,
                active_tab="vision",
            )

    except Exception as exc:
        logger.error("Vision analysis failed: " + str(exc))
        return render_template(
            "index.html",
            vision_error="分析失败：" + str(exc),
            llm_available=llm_available,
            projects=projects,
            has_knowledge=HAS_KNOWLEDGE,
            active_tab="vision",
        )


def _merge_vision_with_cv(
    vision_result: VisionAnalysisResult,
    cv_result,
) -> VisionAnalysisResult:
    """合并多模态分析结果和CV分析结果"""
    from .core.models import UIVisionElement

    cv_elements = []
    for btn in cv_result.action_buttons:
        cv_elements.append(UIVisionElement(
            element_type="button",
            text=btn.text,
            description="CV检测到按钮",
            is_interactive=True,
            locator_strategy="get_by_role",
            locator_value=f"button, name='{btn.text}'",
            suggested_action="click",
        ))
    for field, label in cv_result.form_fields:
        label_text = label.text if label else (field.associated_label or field.text)
        cv_elements.append(UIVisionElement(
            element_type=field.element_type.value,
            text=label_text,
            description="CV检测到表单字段",
            is_interactive=True,
            locator_strategy="get_by_label",
            locator_value=label_text,
            suggested_action="fill" if field.element_type.value != "dropdown" else "select",
        ))

    seen_texts = {e.text for e in vision_result.elements if e.is_interactive}
    for elem in cv_elements:
        if elem.text not in seen_texts:
            vision_result.elements.append(elem)
            seen_texts.add(elem.text)

    return vision_result


# ========== 文件浏览 API ==========

BROWSE_BLOCKED_NAMES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".env", ".tox", ".pytest_cache", ".mypy_cache",
    ".eggs", "dist", "build",
}
BROWSE_BLOCKED_PREFIXES = (
    "/etc", "/proc", "/sys", "/dev", "/boot", "/root",
    "/var/run", "/var/log",
)


@app.get("/api/browse")
def api_browse():
    raw_path = request.args.get("path", "").strip()
    if not raw_path:
        target = Path.home()
    else:
        target = Path(raw_path).resolve()

    target_str = str(target)
    for blocked in BROWSE_BLOCKED_PREFIXES:
        if target_str.startswith(blocked):
            return jsonify({"error": "禁止访问此路径"}), 403

    allowed_roots = [Path.home(), Path("/home")]
    if not any(target == r or target.is_relative_to(r) for r in allowed_roots):
        return jsonify({"error": "路径不在允许范围内"}), 403

    if not target.exists() or not target.is_dir():
        return jsonify({"error": "目录不存在"}), 404

    directories = []
    try:
        for entry in sorted(target.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in BROWSE_BLOCKED_NAMES:
                continue
            if entry.name.startswith("."):
                continue
            directories.append({
                "name": entry.name,
                "path": str(entry),
            })
    except PermissionError:
        return jsonify({"error": "没有访问权限"}), 403

    parent = str(target.parent) if target != target.parent else None

    return jsonify({
        "current_path": str(target),
        "parent_path": parent,
        "directories": directories,
        "is_root": target == target.parent,
    })


# ========== 知识库 API ==========

@app.get("/api/projects")
def api_list_projects():
    """获取项目列表"""
    if not HAS_KNOWLEDGE:
        return jsonify({"error": "知识库功能未启用"}), 400

    try:
        ks = get_knowledge_service()
        projects = ks.list_projects()
        return jsonify({
            "projects": [
                {
                    "project_id": p.project_id,
                    "name": p.name,
                    "description": p.description,
                    "created_at": p.created_at,
                    "document_count": p.document_count,
                }
                for p in projects
            ]
        })
    except Exception as e:
        logger.error(f"Failed to list projects: {e}")
        return jsonify({"error": str(e)}), 500


@app.post("/api/projects")
def api_create_project():
    """创建项目"""
    if not HAS_KNOWLEDGE:
        return jsonify({"error": "知识库功能未启用"}), 400

    data = request.get_json() or {}
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()

    if not name:
        return jsonify({"error": "项目名称不能为空"}), 400

    try:
        ks = get_knowledge_service()
        project = ks.create_project(name, description)
        return jsonify({
            "project": {
                "project_id": project.project_id,
                "name": project.name,
                "description": project.description,
                "created_at": project.created_at,
                "document_count": project.document_count,
            }
        })
    except Exception as e:
        logger.error(f"Failed to create project: {e}")
        return jsonify({"error": str(e)}), 500


@app.get("/api/projects/<project_id>/documents")
def api_list_documents(project_id: str):
    """获取项目文档列表"""
    if not HAS_KNOWLEDGE:
        return jsonify({"error": "知识库功能未启用"}), 400

    try:
        ks = get_knowledge_service()
        docs = ks.list_documents(project_id)
        return jsonify({
            "documents": [
                {
                    "doc_id": d.doc_id,
                    "filename": d.filename,
                    "doc_type": d.doc_type,
                    "upload_time": d.upload_time,
                    "chunk_count": d.chunk_count,
                }
                for d in docs
            ]
        })
    except Exception as e:
        logger.error(f"Failed to list documents: {e}")
        return jsonify({"error": str(e)}), 500


@app.post("/api/projects/<project_id>/documents")
def api_add_document(project_id: str):
    """上传文档到项目"""
    if not HAS_KNOWLEDGE:
        return jsonify({"error": "知识库功能未启用"}), 400

    if "file" not in request.files:
        return jsonify({"error": "未上传文件"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "文件名无效"}), 400

    doc_type = request.form.get("doc_type", "other")

    # 保存临时文件
    temp_dir = UPLOAD_ROOT / "knowledge_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / _safe_name(file.filename)
    file.save(str(temp_file))

    try:
        ks = get_knowledge_service()
        doc = ks.add_document(project_id, temp_file, doc_type)
        if doc:
            return jsonify({
                "document": {
                    "doc_id": doc.doc_id,
                    "filename": doc.filename,
                    "doc_type": doc.doc_type,
                    "chunk_count": doc.chunk_count,
                }
            })
        else:
            return jsonify({"error": "添加文档失败"}), 500
    except Exception as e:
        logger.error(f"Failed to add document: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        # 清理临时文件
        if temp_file.exists():
            temp_file.unlink()


@app.delete("/api/projects/<project_id>/documents/<doc_id>")
def api_delete_document(project_id: str, doc_id: str):
    """删除文档"""
    if not HAS_KNOWLEDGE:
        return jsonify({"error": "知识库功能未启用"}), 400

    try:
        ks = get_knowledge_service()
        success = ks.delete_document(project_id, doc_id)
        return jsonify({"success": success})
    except Exception as e:
        logger.error(f"Failed to delete document: {e}")
        return jsonify({"error": str(e)}), 500


@app.delete("/api/projects/<project_id>")
def api_delete_project(project_id: str):
    """删除项目"""
    if not HAS_KNOWLEDGE:
        return jsonify({"error": "知识库功能未启用"}), 400

    try:
        ks = get_knowledge_service()
        success = ks.delete_project(project_id)
        return jsonify({"success": success})
    except Exception as e:
        logger.error(f"Failed to delete project: {e}")
        return jsonify({"error": str(e)}), 500


def main() -> None:
    setup_logging()
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    logger.info("Starting web server on http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()