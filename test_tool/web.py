from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from zipfile import ZipFile

from flask import Flask, abort, jsonify, render_template, request, send_file

from .exporters import export_cases_to_csv, export_cases_to_excel, export_cases_to_word
from .generators import parse_requirement_path, generate_with_llm
from .core.config import GenerationConfig, LLMGenerationConfig
from .core.logging import setup_logging, get_logger
from .core.models import ReviewResult
from .utils.file_utils import SUPPORTED_EXTENSIONS, IMAGE_EXTENSIONS
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


@app.get("/download/<job_id>/<filename>")
def download(job_id: str, filename: str):
    if not job_id.isalnum():
        abort(404)
    safe_filename = _safe_name(filename)
    target = OUTPUT_ROOT / job_id / safe_filename
    if not target.exists() or not target.is_file():
        abort(404)
    return send_file(target, as_attachment=True, download_name=safe_filename)


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