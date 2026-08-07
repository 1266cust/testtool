from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import json
import hashlib
import logging

from .providers import get_provider

logger = logging.getLogger("llm.client")


@dataclass
class LLMConfig:
    """LLM配置"""
    provider: str = "deepseek"
    model_name: str = "deepseek-chat"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout_seconds: int = 120
    retry_count: int = 3

    enable_cache: bool = True
    cache_ttl_seconds: int = 3600

    vision_provider: Optional[str] = None
    vision_model_name: Optional[str] = None
    vision_api_key: Optional[str] = None
    vision_base_url: Optional[str] = None

    @property
    def has_vision_model(self) -> bool:
        return bool(self.vision_provider and self.vision_model_name and self.vision_api_key)

    def get_vision_config(self) -> "LLMConfig":
        """获取视觉模型配置（如果有独立配置），否则返回自身"""
        if self.has_vision_model:
            return LLMConfig(
                provider=self.vision_provider,
                model_name=self.vision_model_name,
                api_key=self.vision_api_key,
                base_url=self.vision_base_url,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                timeout_seconds=self.timeout_seconds,
                retry_count=self.retry_count,
                enable_cache=self.enable_cache,
                cache_ttl_seconds=self.cache_ttl_seconds,
            )
        return self


class LLMClient:
    """LLM客户端统一封装"""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self._provider_instance = None
        self._cache: Dict[str, Any] = {}

    def _get_provider(self):
        """获取提供商实例"""
        if self._provider_instance is None:
            self._provider_instance = get_provider(self.config.provider)
        return self._provider_instance

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> str:
        """生成响应"""
        cache_key = self._build_cache_key(prompt, system_prompt)
        if self.config.enable_cache and cache_key in self._cache:
            return self._cache[cache_key]

        provider = self._get_provider()
        response = provider.generate(
            model=self.config.model_name,
            prompt=prompt,
            system_prompt=system_prompt,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            temperature=kwargs.get("temperature", self.config.temperature),
            timeout=self.config.timeout_seconds,
        )

        if self.config.enable_cache:
            self._cache[cache_key] = response

        return response

    def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """生成JSON格式响应"""
        response = self.generate(prompt, system_prompt)
        return self._parse_json_response(response)

    def _build_cache_key(self, prompt: str, system: Optional[str]) -> str:
        combined = (system or "") + "::" + prompt
        return hashlib.md5(combined.encode()).hexdigest()

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析JSON响应"""
        cleaned = response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

        cleaned = cleaned.strip()
        if not cleaned.startswith("{"):
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start >= 0 and end > start:
                cleaned = cleaned[start:end]

        return json.loads(cleaned)

    def generate_with_images(
        self,
        prompt: str,
        image_paths: list,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> str:
        """多模态生成：支持图片输入，需要视觉模型配置"""
        if not self.config.has_vision_model:
            return '{"page_description":"","page_type":"","elements":[],"interaction_flows":[],"page_flows":[],"test_points":[]}'
        vision_config = self.config.get_vision_config()
        provider = get_provider(vision_config.provider)
        try:
            response = provider.generate_with_images(
                model=vision_config.model_name,
                prompt=prompt,
                image_paths=image_paths,
                system_prompt=system_prompt,
                api_key=vision_config.api_key,
                base_url=vision_config.base_url,
                max_tokens=kwargs.get("max_tokens", vision_config.max_tokens),
                temperature=kwargs.get("temperature", vision_config.temperature),
                timeout=vision_config.timeout_seconds,
            )
            return response
        except Exception as exc:
            err_msg = str(exc)
            if "does not support image input" in err_msg or "image" in err_msg.lower():
                logger.warning(f"Vision model {vision_config.provider}/{vision_config.model_name} 不支持图片输入，已跳过视觉分析")
                return '{"page_description":"","page_type":"","elements":[],"interaction_flows":[],"page_flows":[],"test_points":[]}'
            raise

    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()