from __future__ import annotations

from typing import List, Optional, Dict, Any
from pathlib import Path
import json
import os
import shutil

from .config import KnowledgeConfig, get_knowledge_config
from .models import (
    Project,
    KnowledgeDocument,
    DocumentChunk,
    RetrievedContext,
    SearchResult,
)
from .embedding import Embedder, get_embedder
from .vector_store import MilvusVectorStore, get_vector_store
from .document_parser import DocumentParser, get_document_parser
from ..core.logging import get_logger

logger = get_logger("knowledge.service")


class KnowledgeService:
    """知识库服务"""

    _instance: Optional[KnowledgeService] = None

    def __init__(self, config: Optional[KnowledgeConfig] = None):
        self.config = config or get_knowledge_config()
        self.embedder = get_embedder()
        self.vector_store = get_vector_store()
        self.document_parser = get_document_parser()

        # 确保 projects 目录存在
        self._ensure_projects_dir()

    def _ensure_projects_dir(self):
        """确保项目存储目录存在"""
        projects_dir = Path(self.config.projects_dir)
        projects_dir.mkdir(parents=True, exist_ok=True)

        # 确保 projects.json 存在
        projects_file = projects_dir / "projects.json"
        if not projects_file.exists():
            projects_file.write_text("[]", encoding="utf-8")

    @classmethod
    def get_instance(cls) -> KnowledgeService:
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = KnowledgeService()
        return cls._instance

    # ========== 项目管理 ==========

    def create_project(self, name: str, description: str = "") -> Project:
        """创建新项目"""
        project = Project.create(name, description)

        # 创建项目目录
        project_dir = Path(self.config.projects_dir) / project.project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        # 创建文档记录文件
        docs_file = project_dir / "documents.json"
        docs_file.write_text("[]", encoding="utf-8")

        # 保存项目到 projects.json
        self._save_project(project)

        logger.info(f"Created project: {project.project_id} - {name}")
        return project

    def list_projects(self) -> List[Project]:
        """获取所有项目列表"""
        projects_file = Path(self.config.projects_dir) / "projects.json"
        if not projects_file.exists():
            return []

        try:
            data = json.loads(projects_file.read_text(encoding="utf-8"))
            return [Project(**p) for p in data]
        except Exception as e:
            logger.error(f"Failed to load projects: {e}")
            return []

    def get_project(self, project_id: str) -> Optional[Project]:
        """获取指定项目"""
        projects = self.list_projects()
        for project in projects:
            if project.project_id == project_id:
                return project
        return None

    def delete_project(self, project_id: str) -> bool:
        """删除项目"""
        # 删除向量数据库中的数据
        self.vector_store.delete_by_project(project_id)

        # 删除项目目录
        project_dir = Path(self.config.projects_dir) / project_id
        if project_dir.exists():
            shutil.rmtree(project_dir)

        # 从 projects.json 中移除
        projects = self.list_projects()
        projects = [p for p in projects if p.project_id != project_id]
        self._save_all_projects(projects)

        logger.info(f"Deleted project: {project_id}")
        return True

    def _save_project(self, project: Project):
        """保存项目到 projects.json"""
        projects = self.list_projects()
        projects.append(project)
        self._save_all_projects(projects)

    def _save_all_projects(self, projects: List[Project]):
        """保存所有项目到 projects.json"""
        projects_file = Path(self.config.projects_dir) / "projects.json"
        data = [
            {
                "project_id": p.project_id,
                "name": p.name,
                "description": p.description,
                "created_at": p.created_at,
                "document_count": p.document_count,
            }
            for p in projects
        ]
        projects_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ========== 文档管理 ==========

    def add_document(
        self,
        project_id: str,
        file_path: Path,
        doc_type: str = "other",
    ) -> Optional[KnowledgeDocument]:
        """
        添加文档到项目知识库

        Args:
            project_id: 项目ID
            file_path: 文件路径
            doc_type: 文档类型（requirement/design/test_case/other）

        Returns:
            文档记录
        """
        # 检查项目是否存在
        project = self.get_project(project_id)
        if not project:
            logger.error(f"Project not found: {project_id}")
            return None

        # 检查文件是否存在
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return None

        # 创建文档记录
        filename = file_path.name
        doc = KnowledgeDocument.create(
            project_id=project_id,
            filename=filename,
            file_path=str(file_path),
            doc_type=doc_type,
        )

        # 复制文件到项目目录
        project_dir = Path(self.config.projects_dir) / project_id
        dest_path = project_dir / "files" / doc.doc_id
        dest_path.mkdir(parents=True, exist_ok=True)
        shutil.copy(file_path, dest_path / filename)
        doc.file_path = str(dest_path / filename)

        # 解析文档并分块
        chunks = self.document_parser.parse_file(
            file_path,
            project_id,
            doc,
        )

        if not chunks:
            logger.warning(f"No chunks generated from {filename}")
            # 仍然保存文档记录，但 chunk_count 为 0
            self._save_document(project_id, doc)
            return doc

        # 生成嵌入向量
        embeddings = self.embedder.get_embeddings(
            [chunk.content for chunk in chunks],
        )

        # 存入向量数据库
        success = self.vector_store.add_chunks(chunks, embeddings)

        if success:
            doc.chunk_count = len(chunks)
            # 更新项目文档数量
            project.document_count += 1
            self._update_project(project)
        else:
            logger.warning(f"Failed to store chunks in vector database")

        # 保存文档记录
        self._save_document(project_id, doc)

        logger.info(f"Added document: {doc.doc_id} to project {project_id}")
        return doc

    def list_documents(self, project_id: str) -> List[KnowledgeDocument]:
        """获取项目的文档列表"""
        project_dir = Path(self.config.projects_dir) / project_id
        docs_file = project_dir / "documents.json"

        if not docs_file.exists():
            return []

        try:
            data = json.loads(docs_file.read_text(encoding="utf-8"))
            return [KnowledgeDocument(**d) for d in data]
        except Exception as e:
            logger.error(f"Failed to load documents: {e}")
            return []

    def delete_document(self, project_id: str, doc_id: str) -> bool:
        """删除文档"""
        # 删除向量数据库中的数据
        self.vector_store.delete_by_doc_id(doc_id)

        # 从 documents.json 中移除
        docs = self.list_documents(project_id)
        docs = [d for d in docs if d.doc_id != doc_id]
        self._save_all_documents(project_id, docs)

        # 删除文件
        project_dir = Path(self.config.projects_dir) / project_id
        doc_dir = project_dir / "files" / doc_id
        if doc_dir.exists():
            shutil.rmtree(doc_dir)

        # 更新项目文档数量
        project = self.get_project(project_id)
        if project and project.document_count > 0:
            project.document_count -= 1
            self._update_project(project)

        logger.info(f"Deleted document: {doc_id}")
        return True

    def _save_document(self, project_id: str, doc: KnowledgeDocument):
        """保存文档记录"""
        docs = self.list_documents(project_id)
        docs.append(doc)
        self._save_all_documents(project_id, docs)

    def _save_all_documents(self, project_id: str, docs: List[KnowledgeDocument]):
        """保存所有文档记录"""
        project_dir = Path(self.config.projects_dir) / project_id
        docs_file = project_dir / "documents.json"
        data = [
            {
                "doc_id": d.doc_id,
                "project_id": d.project_id,
                "filename": d.filename,
                "doc_type": d.doc_type,
                "file_path": d.file_path,
                "upload_time": d.upload_time,
                "chunk_count": d.chunk_count,
                "file_size": d.file_size,
            }
            for d in docs
        ]
        docs_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _update_project(self, project: Project):
        """更新项目信息"""
        projects = self.list_projects()
        for i, p in enumerate(projects):
            if p.project_id == project.project_id:
                projects[i] = project
                break
        self._save_all_projects(projects)

    # ========== 知识检索 ==========

    def search_relevant_docs(
        self,
        project_id: str,
        query: str,
        top_k: int = 5,
    ) -> SearchResult:
        """
        检索项目中与查询相关的文档

        Args:
            project_id: 项目ID
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            检索结果
        """
        # 检查项目是否存在
        project = self.get_project(project_id)
        if not project:
            logger.warning(f"Project not found: {project_id}")
            return SearchResult(contexts=[], project_id=project_id)

        # 生成查询向量
        query_embeddings = self.embedder.get_embeddings(query)
        if not query_embeddings or not query_embeddings[0]:
            return SearchResult(contexts=[], project_id=project_id)

        query_vector = query_embeddings[0]

        # 搜索向量数据库
        contexts = self.vector_store.search(
            query_vector=query_vector,
            project_id=project_id,
            top_k=top_k,
            min_score=self.config.min_similarity_threshold,
        )

        # 关键词后处理过滤
        query_keywords = self._extract_keywords(query)
        if query_keywords:
            contexts = self._keyword_filter(contexts, query_keywords, top_k)

        return SearchResult(
            contexts=contexts,
            total_count=len(contexts),
            project_id=project_id,
        )

    def get_project_context(
        self,
        project_id: str,
        requirement_text: str,
        top_k: int = 5,
    ) -> str:
        """
        获取项目的知识库上下文（用于注入 LLM 提示词）

        Args:
            project_id: 项目ID
            requirement_text: 需求文本
            top_k: 检索结果数量

        Returns:
            知识库上下文文本
        """
        if not project_id:
            return ""

        result = self.search_relevant_docs(project_id, requirement_text, top_k)
        return result.to_knowledge_context()

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        # 简单的关键词提取：过滤停用词和短词
        stopwords = {"的", "是", "在", "有", "和", "了", "不", "这", "那", "要", "可以", "需要"}

        words = []
        # 按空格和标点拆分
        for word in text.split():
            # 清理标点
            word = word.strip("。，！？、：；""''()（）[]【】")
            if len(word) >= 2 and word not in stopwords:
                words.append(word)

        return words[:10]  # 最多取10个关键词

    def _keyword_filter(
        self,
        contexts: List[RetrievedContext],
        keywords: List[str],
        top_k: int,
    ) -> List[RetrievedContext]:
        """关键词后处理过滤"""
        if not keywords:
            return contexts[:top_k]

        # 分组：包含关键词的 vs 不包含关键词的
        with_keywords = []
        without_keywords = []

        for ctx in contexts:
            content_lower = ctx.content.lower()
            if any(kw.lower() in content_lower for kw in keywords):
                with_keywords.append(ctx)
            else:
                without_keywords.append(ctx)

        # 合并结果：优先包含关键词的，然后是高分的
        result = with_keywords[:top_k]
        remaining = top_k - len(result)
        if remaining > 0:
            result.extend(without_keywords[:remaining])

        return result


def get_knowledge_service() -> KnowledgeService:
    """获取知识库服务实例"""
    return KnowledgeService.get_instance()