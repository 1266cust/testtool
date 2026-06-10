from __future__ import annotations

from typing import List, Union, Optional
import numpy as np
import os

try:
    from sentence_transformers import SentenceTransformer
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False

from .config import KnowledgeConfig, get_knowledge_config
from ..core.logging import get_logger

logger = get_logger("knowledge.embedding")


class Embedder:
    """嵌入模型"""

    _instance: Optional[Embedder] = None

    def __init__(self, config: Optional[KnowledgeConfig] = None):
        """
        初始化嵌入模型

        Args:
            config: 知识库配置
        """
        self.config = config or get_knowledge_config()
        self.model = None
        self._initialized = False

    def _lazy_init(self):
        """延迟初始化模型"""
        if self._initialized:
            return

        if not HAS_SENTENCE_TRANSFORMERS:
            logger.warning("sentence-transformers not installed, embedding will return dummy vectors")
            self._initialized = True
            return

        try:
            logger.info(f"Loading embedding model: {self.config.embedding_model}")
            # 设置环境变量以优化性能
            os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK', '1')
            self.model = SentenceTransformer(self.config.embedding_model)
            logger.info("Embedding model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self.model = None

        self._initialized = True

    @classmethod
    def get_instance(cls, config: Optional[KnowledgeConfig] = None) -> Embedder:
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = Embedder(config)
        return cls._instance

    def get_embeddings(
        self,
        texts: Union[str, List[str]],
        show_progress_bar: bool = False,
    ) -> List[List[float]]:
        """
        获取文本的嵌入向量

        Args:
            texts: 单个文本或文本列表
            show_progress_bar: 是否显示进度条

        Returns:
            嵌入向量列表
        """
        self._lazy_init()

        if isinstance(texts, str):
            texts = [texts]

        if self.model is None:
            # 模型未加载，返回模拟向量
            logger.warning("Embedding model not available, returning dummy vectors")
            return [[0.0] * self.config.embedding_dim for _ in texts]

        try:
            embeddings = self.model.encode(
                sentences=texts,
                normalize_embeddings=True,
                show_progress_bar=show_progress_bar,
            )
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Failed to get embeddings: {e}")
            return [[0.0] * self.config.embedding_dim for _ in texts]

    def compute_similarity(self, text1: str, text2: str) -> float:
        """
        计算两个文本之间的相似度

        Args:
            text1: 第一个文本
            text2: 第二个文本

        Returns:
            相似度分数 (0-1)
        """
        embeddings = self.get_embeddings([text1, text2])
        similarity = np.dot(embeddings[0], embeddings[1])
        return float(similarity)

    def get_embedding_dim(self) -> int:
        """获取嵌入向量维度"""
        return self.config.embedding_dim


def get_embedder() -> Embedder:
    """获取嵌入模型实例"""
    return Embedder.get_instance()