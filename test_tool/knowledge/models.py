from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
import uuid


@dataclass
class Project:
    """项目信息"""
    project_id: str
    name: str
    description: str = ""
    created_at: str = ""
    document_count: int = 0

    @classmethod
    def create(cls, name: str, description: str = "") -> Project:
        """创建新项目"""
        return cls(
            project_id=uuid.uuid4().hex[:12],
            name=name,
            description=description,
            created_at=datetime.now().isoformat(),
            document_count=0,
        )


@dataclass
class KnowledgeDocument:
    """知识库文档"""
    doc_id: str
    project_id: str
    filename: str
    doc_type: str  # requirement / design / test_case / other
    file_path: str
    upload_time: str = ""
    chunk_count: int = 0
    file_size: int = 0

    @classmethod
    def create(
        cls,
        project_id: str,
        filename: str,
        file_path: str,
        doc_type: str = "other",
    ) -> KnowledgeDocument:
        """创建文档记录"""
        return cls(
            doc_id=uuid.uuid4().hex[:12],
            project_id=project_id,
            filename=filename,
            doc_type=doc_type,
            file_path=file_path,
            upload_time=datetime.now().isoformat(),
            chunk_count=0,
            file_size=0,
        )


@dataclass
class DocumentChunk:
    """文档分块"""
    chunk_id: str
    doc_id: str
    project_id: str
    content: str
    source: str
    doc_type: str
    chunk_index: int = 0


@dataclass
class RetrievedContext:
    """检索到的上下文"""
    content: str
    source: str
    score: float
    doc_type: str
    chunk_id: str = ""

    def to_context_text(self) -> str:
        """转换为上下文文本格式"""
        doc_type_label = {
            "requirement": "需求文档",
            "design": "设计文档",
            "test_case": "历史用例",
            "other": "其他文档",
        }.get(self.doc_type, "文档")

        return f"[{doc_type_label}] {self.source}:\n{self.content}"


@dataclass
class SearchResult:
    """检索结果"""
    contexts: List[RetrievedContext]
    total_count: int = 0
    project_id: str = ""

    def to_knowledge_context(self) -> str:
        """转换为知识库上下文（用于注入 LLM 提示词）"""
        if not self.contexts:
            return ""

        lines = ["以下是知识库中与当前需求相关的历史文档内容，可作为生成测试用例的参考："]
        for ctx in self.contexts:
            lines.append("")
            lines.append(ctx.to_context_text())

        return "\n".join(lines)