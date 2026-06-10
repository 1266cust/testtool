from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import os


@dataclass
class KnowledgeConfig:
    """知识库配置"""
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    collection_name: str = "testtool_knowledge"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    chunk_size: int = 500
    chunk_overlap: int = 50
    search_top_k: int = 5
    min_similarity_threshold: float = 0.6
    projects_dir: str = ""  # 项目文档存储目录


def get_knowledge_config() -> KnowledgeConfig:
    """获取知识库配置（从环境变量读取）"""
    projects_dir = os.environ.get(
        "KNOWLEDGE_PROJECTS_DIR",
        os.path.expanduser("~/.testtool/projects")
    )

    return KnowledgeConfig(
        milvus_host=os.environ.get("MILVUS_HOST", "localhost"),
        milvus_port=int(os.environ.get("MILVUS_PORT", "19530")),
        collection_name=os.environ.get("MILVUS_COLLECTION", "testtool_knowledge"),
        embedding_model=os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3"),
        embedding_dim=int(os.environ.get("EMBEDDING_DIM", "1024")),
        chunk_size=int(os.environ.get("CHUNK_SIZE", "500")),
        chunk_overlap=int(os.environ.get("CHUNK_OVERLAP", "50")),
        search_top_k=int(os.environ.get("SEARCH_TOP_K", "5")),
        min_similarity_threshold=float(os.environ.get("MIN_SIMILARITY", "0.6")),
        projects_dir=projects_dir,
    )