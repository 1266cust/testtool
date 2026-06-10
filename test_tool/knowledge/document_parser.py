from __future__ import annotations

from typing import List, Optional
from pathlib import Path
import re
import uuid

from .config import KnowledgeConfig, get_knowledge_config
from .models import DocumentChunk, KnowledgeDocument
from ..parsers import (
    read_text_file,
    read_docx_file,
    read_pdf_file,
    read_excel_file,
    read_csv_file,
    read_json_file,
)
from ..core.logging import get_logger

logger = get_logger("knowledge.document_parser")


class DocumentParser:
    """文档解析器"""

    SUPPORTED_EXTENSIONS = {
        ".txt", ".md", ".markdown",
        ".docx", ".doc",
        ".pdf",
        ".xlsx", ".xls",
        ".csv",
        ".json",
    }

    def __init__(self, config: Optional[KnowledgeConfig] = None):
        self.config = config or get_knowledge_config()

    def parse_file(
        self,
        file_path: Path,
        project_id: str,
        doc: KnowledgeDocument,
    ) -> List[DocumentChunk]:
        """
        解析文件并生成文档分块

        Args:
            file_path: 文件路径
            project_id: 项目ID
            doc: 文档记录

        Returns:
            文档分块列表
        """
        ext = file_path.suffix.lower()

        if ext not in self.SUPPORTED_EXTENSIONS:
            logger.warning(f"Unsupported file type: {ext}")
            return []

        # 提取文本内容
        text = self._extract_text(file_path)
        if not text.strip():
            logger.warning(f"No text extracted from {file_path}")
            return []

        # 分块
        chunks = self._chunk_text(text)

        # 创建 DocumentChunk 对象
        doc_chunks = []
        for i, chunk_content in enumerate(chunks):
            chunk = DocumentChunk(
                chunk_id=uuid.uuid4().hex[:16],
                doc_id=doc.doc_id,
                project_id=project_id,
                content=chunk_content,
                source=doc.filename,
                doc_type=doc.doc_type,
                chunk_index=i,
            )
            doc_chunks.append(chunk)

        logger.info(f"Parsed {file_path} into {len(doc_chunks)} chunks")
        return doc_chunks

    def _extract_text(self, file_path: Path) -> str:
        """提取文件文本内容"""
        ext = file_path.suffix.lower()

        try:
            if ext in {".txt", ".md", ".markdown"}:
                return read_text_file(file_path)
            elif ext in {".docx", ".doc"}:
                return read_docx_file(file_path)
            elif ext == ".pdf":
                return read_pdf_file(file_path)
            elif ext in {".xlsx", ".xls"}:
                return read_excel_file(file_path)
            elif ext == ".csv":
                return read_csv_file(file_path)
            elif ext == ".json":
                return read_json_file(file_path)
            else:
                return ""
        except Exception as e:
            logger.error(f"Failed to extract text from {file_path}: {e}")
            return ""

    def _chunk_text(self, text: str) -> List[str]:
        """
        将文本分块

        Args:
            text: 原始文本

        Returns:
            分块列表
        """
        chunk_size = self.config.chunk_size
        chunk_overlap = self.config.chunk_overlap

        # 首先尝试按段落分块
        paragraphs = self._split_paragraphs(text)

        chunks = []
        current_chunk = ""

        for para in paragraphs:
            # 如果单个段落超过 chunk_size，需要进一步拆分
            if len(para) > chunk_size:
                # 先保存当前累积的内容
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                    current_chunk = ""

                # 按句子拆分长段落
                sentences = self._split_sentences(para)
                sentence_chunk = ""

                for sentence in sentences:
                    if len(sentence_chunk) + len(sentence) <= chunk_size:
                        sentence_chunk += sentence
                    else:
                        if sentence_chunk.strip():
                            chunks.append(sentence_chunk.strip())
                        # 处理 overlap
                        overlap_text = sentence_chunk[-chunk_overlap:] if chunk_overlap > 0 else ""
                        sentence_chunk = overlap_text + sentence

                if sentence_chunk.strip():
                    current_chunk = sentence_chunk
            else:
                # 段落小于 chunk_size，尝试合并
                if len(current_chunk) + len(para) <= chunk_size:
                    current_chunk += "\n" + para
                else:
                    # 保存当前 chunk
                    if current_chunk.strip():
                        chunks.append(current_chunk.strip())
                    # 处理 overlap
                    overlap_text = current_chunk[-chunk_overlap:] if chunk_overlap > 0 else ""
                    current_chunk = overlap_text + "\n" + para

        # 保存最后一个 chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    def _split_paragraphs(self, text: str) -> List[str]:
        """按段落拆分文本"""
        # 按双换行符拆分
        paragraphs = re.split(r'\n\s*\n', text)
        # 过滤空段落并清理
        return [p.strip() for p in paragraphs if p.strip()]

    def _split_sentences(self, text: str) -> List[str]:
        """按句子拆分文本"""
        # 中文和英文句子分隔符
        pattern = r'[。！？.!?]+'

        sentences = []
        parts = re.split(pattern, text)

        # 重新添加分隔符
        matches = re.findall(pattern, text)
        for i, part in enumerate(parts):
            if i < len(matches):
                sentences.append(part + matches[i])
            else:
                if part.strip():
                    sentences.append(part)

        return [s.strip() for s in sentences if s.strip()]


def get_document_parser() -> DocumentParser:
    """获取文档解析器实例"""
    return DocumentParser()