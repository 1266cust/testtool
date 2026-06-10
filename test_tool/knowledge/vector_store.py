from __future__ import annotations

from typing import List, Dict, Any, Optional
import os

try:
    from pymilvus import connections, Collection, utility, DataType
    from pymilvus import CollectionSchema, FieldSchema
    HAS_PYMILVUS = True
except ImportError:
    HAS_PYMILVUS = False
    connections = None
    Collection = None
    utility = None
    DataType = None
    CollectionSchema = None
    FieldSchema = None

from .config import KnowledgeConfig, get_knowledge_config
from .models import DocumentChunk, RetrievedContext
from ..core.logging import get_logger

logger = get_logger("knowledge.vector_store")


class MilvusVectorStore:
    """Milvus向量数据库存储"""

    _instance: Optional[MilvusVectorStore] = None

    def __init__(self, config: Optional[KnowledgeConfig] = None):
        """
        初始化 Milvus 向量存储

        Args:
            config: 知识库配置
        """
        self.config = config or get_knowledge_config()
        self.host = self.config.milvus_host
        self.port = str(self.config.milvus_port)
        self.collection_name = self.config.collection_name
        self._connected = False
        self._collection = None

    def _connect(self):
        """连接到 Milvus 服务器"""
        if self._connected:
            return

        if not HAS_PYMILVUS:
            logger.warning("pymilvus not installed, vector store will be disabled")
            self._connected = True
            return

        try:
            connections.connect(
                alias="default",
                host=self.host,
                port=self.port,
            )
            self._connected = True
            logger.info(f"Connected to Milvus at {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to Milvus: {e}")
            self._connected = True  # Mark as connected to avoid repeated attempts

    def _ensure_collection(self) -> Optional[Collection]:
        """确保集合存在，如不存在则创建"""
        if not HAS_PYMILVUS:
            return None

        self._connect()

        try:
            if not utility.has_collection(self.collection_name):
                logger.info(f"Creating collection: {self.collection_name}")
                # 定义集合模式，增加 project_id 字段
                fields = [
                    FieldSchema(
                        name="id",
                        dtype=DataType.INT64,
                        is_primary=True,
                        auto_id=True,
                    ),
                    FieldSchema(
                        name="embedding",
                        dtype=DataType.FLOAT_VECTOR,
                        dim=self.config.embedding_dim,
                    ),
                    FieldSchema(
                        name="content",
                        dtype=DataType.VARCHAR,
                        max_length=4096,
                    ),
                    FieldSchema(
                        name="project_id",
                        dtype=DataType.VARCHAR,
                        max_length=64,
                    ),
                    FieldSchema(
                        name="doc_id",
                        dtype=DataType.VARCHAR,
                        max_length=64,
                    ),
                    FieldSchema(
                        name="source",
                        dtype=DataType.VARCHAR,
                        max_length=512,
                    ),
                    FieldSchema(
                        name="doc_type",
                        dtype=DataType.VARCHAR,
                        max_length=32,
                    ),
                    FieldSchema(
                        name="chunk_id",
                        dtype=DataType.VARCHAR,
                        max_length=128,
                    ),
                    FieldSchema(
                        name="chunk_index",
                        dtype=DataType.INT64,
                    ),
                ]
                schema = CollectionSchema(
                    fields=fields,
                    description="testtool知识库向量存储",
                )
                collection = Collection(name=self.collection_name, schema=schema)

                # 创建索引
                index_params = {
                    "metric_type": "COSINE",
                    "index_type": "HNSW",
                    "params": {"M": 8, "efConstruction": 64},
                }
                collection.create_index(
                    field_name="embedding",
                    index_params=index_params,
                )
                logger.info("Collection created with index")
                collection.load()
                return collection
            else:
                logger.info(f"Collection {self.collection_name} exists")
                collection = Collection(self.collection_name)
                collection.load()
                return collection
        except Exception as e:
            logger.error(f"Failed to ensure collection: {e}")
            return None

    @classmethod
    def get_instance(cls, config: Optional[KnowledgeConfig] = None) -> MilvusVectorStore:
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = MilvusVectorStore(config)
        return cls._instance

    def add_chunks(
        self,
        chunks: List[DocumentChunk],
        embeddings: List[List[float]],
    ) -> bool:
        """
        添加文档分块到向量数据库

        Args:
            chunks: 文档分块列表
            embeddings: 对应的嵌入向量列表

        Returns:
            是否成功
        """
        if not HAS_PYMILVUS:
            logger.warning("pymilvus not installed, cannot add chunks")
            return False

        collection = self._ensure_collection()
        if collection is None:
            return False

        if len(chunks) != len(embeddings):
            logger.error("Chunks and embeddings count mismatch")
            return False

        try:
            data = []
            for chunk, embedding in zip(chunks, embeddings):
                data.append({
                    "embedding": embedding,
                    "content": chunk.content,
                    "project_id": chunk.project_id,
                    "doc_id": chunk.doc_id,
                    "source": chunk.source,
                    "doc_type": chunk.doc_type,
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                })

            collection.insert(data)
            collection.flush()
            logger.info(f"Added {len(chunks)} chunks to vector store")
            return True
        except Exception as e:
            logger.error(f"Failed to add chunks: {e}")
            return False

    def search(
        self,
        query_vector: List[float],
        project_id: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[RetrievedContext]:
        """
        搜索最相似的文档（按项目过滤）

        Args:
            query_vector: 查询向量
            project_id: 项目ID
            top_k: 返回结果数量
            min_score: 最小相似度阈值

        Returns:
            检索结果列表
        """
        if not HAS_PYMILVUS:
            return []

        collection = self._ensure_collection()
        if collection is None:
            return []

        try:
            collection.load()
            search_params = {"metric_type": "COSINE", "params": {"ef": 32}}

            # 使用布尔表达式按项目过滤
            expr = f'project_id == "{project_id}"'

            results = collection.search(
                data=[query_vector],
                anns_field="embedding",
                param=search_params,
                limit=top_k * 3,  # 获取更多结果用于过滤
                expr=expr,
                output_fields=[
                    "content", "project_id", "doc_id",
                    "source", "doc_type", "chunk_id",
                ],
            )

            contexts = []
            for hits in results:
                for hit in hits:
                    if hit.score >= min_score:
                        contexts.append(RetrievedContext(
                            content=hit.entity.get("content"),
                            source=hit.entity.get("source"),
                            score=hit.score,
                            doc_type=hit.entity.get("doc_type"),
                            chunk_id=hit.entity.get("chunk_id"),
                        ))

            # 按相似度排序并取前 top_k
            contexts.sort(key=lambda x: x.score, reverse=True)
            return contexts[:top_k]
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def delete_by_doc_id(self, doc_id: str) -> bool:
        """
        删除指定文档的所有分块

        Args:
            doc_id: 文档ID

        Returns:
            是否成功
        """
        if not HAS_PYMILVUS:
            return False

        collection = self._ensure_collection()
        if collection is None:
            return False

        try:
            expr = f'doc_id == "{doc_id}"'
            collection.delete(expr)
            collection.flush()
            logger.info(f"Deleted chunks for doc_id: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete by doc_id: {e}")
            return False

    def delete_by_project(self, project_id: str) -> bool:
        """
        删除项目的所有文档分块

        Args:
            project_id: 项目ID

        Returns:
            是否成功
        """
        if not HAS_PYMILVUS:
            return False

        collection = self._ensure_collection()
        if collection is None:
            return False

        try:
            expr = f'project_id == "{project_id}"'
            collection.delete(expr)
            collection.flush()
            logger.info(f"Deleted all chunks for project: {project_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete by project: {e}")
            return False


def get_vector_store() -> MilvusVectorStore:
    """获取向量存储实例"""
    return MilvusVectorStore.get_instance()