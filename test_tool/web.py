from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from zipfile import ZipFile

from flask import Flask, abort, render_template, request, send_file

from .exporters import export_cases_to_csv, export_cases_to_excel, export_cases_to_word
from .generators import parse_requirement_path, generate_with_llm
from .core.config import GenerationConfig, LLMGenerationConfig
from .core.logging import setup_logging, get_logger
from .core.models import ReviewResult
from .utils.file_utils import SUPPORTED_EXTENSIONS, IMAGE_EXTENSIONS
from .llm.config_loader import load_llm_config

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
    return render_template("index.html", llm_available=llm_available)


@app.post("/generate")
def generate():
    requirement_text = request.form.get("requirement_text", "").strip()

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
        cases = parse_requirement_path(upload_dir, min_cases=min_cases, cfg=cfg, use_llm=use_llm)
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

    if enable_review and len(cases) > 0:
        review_result = _perform_review(cases, requirement_text, cfg, llm_env_config)

        if enable_auto_fix and review_result:
            cases, fix_summary = _perform_auto_fix(
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
    if fix_summary:
        success_msg += " " + fix_summary

    return render_template(
        "index.html",
        success=success_msg,
        downloads=download_items,
        requirement_text=requirement_text,
        review_result=review_result,
        generation_mode=generation_mode,
        llm_available=llm_available,
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
) -> tuple[list, str]:
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
        return fixed_result.cases, fixed_result.fix_summary
    except Exception as e:
        logger.error(f"Auto-fix failed: {e}")
        return cases, ""


@app.get("/download/<job_id>/<filename>")
def download(job_id: str, filename: str):
    if not job_id.isalnum():
        abort(404)
    safe_filename = _safe_name(filename)
    target = OUTPUT_ROOT / job_id / safe_filename
    if not target.exists() or not target.is_file():
        abort(404)
    return send_file(target, as_attachment=True, download_name=safe_filename)


def main() -> None:
    setup_logging()
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    logger.info("Starting web server on http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()