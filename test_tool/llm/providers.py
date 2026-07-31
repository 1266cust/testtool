from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, List
import base64
import requests


class LLMProvider(ABC):
    """LLM提供商抽象基类"""

    @abstractmethod
    def generate(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str],
        api_key: Optional[str],
        base_url: Optional[str],
        max_tokens: int,
        temperature: float,
        timeout: int,
    ) -> str:
        """生成响应"""
        pass

    def generate_with_images(
        self,
        model: str,
        prompt: str,
        image_paths: List[str],
        system_prompt: Optional[str],
        api_key: Optional[str],
        base_url: Optional[str],
        max_tokens: int,
        temperature: float,
        timeout: int,
    ) -> str:
        """多模态生成：支持图片输入（默认实现将图片编码为base64）"""
        from pathlib import Path

        content_parts = []
        for img_path in image_paths:
            p = Path(img_path)
            if not p.exists():
                continue
            suffix = p.suffix.lower()
            mime_map = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".bmp": "image/bmp",
                ".tiff": "image/tiff",
            }
            mime_type = mime_map.get(suffix, "image/png")
            with open(str(p), "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{b64}"},
            })
        content_parts.append({"type": "text", "text": prompt})

        from openai import OpenAI
        effective_base_url = base_url or "https://api.openai.com/v1"
        client = OpenAI(api_key=api_key, base_url=effective_base_url)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content_parts})

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        if isinstance(response, str):
            return response
        if hasattr(response, 'choices') and response.choices:
            return response.choices[0].message.content
        return str(response)


class DeepSeekProvider(LLMProvider):
    """DeepSeek提供商 (兼容OpenAI接口)"""

    def generate(self, model, prompt, system_prompt, api_key, base_url,
                 max_tokens, temperature, timeout):
        from openai import OpenAI

        effective_base_url = base_url or "https://api.deepseek.com/v1"
        client = OpenAI(api_key=api_key, base_url=effective_base_url)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        # 处理不同API返回格式
        if isinstance(response, str):
            return response
        if hasattr(response, 'choices') and response.choices:
            return response.choices[0].message.content
        # 兼容其他格式
        return str(response)


class OpenAIProvider(LLMProvider):
    """OpenAI提供商"""

    def generate(self, model, prompt, system_prompt, api_key, base_url,
                 max_tokens, temperature, timeout):
        from openai import OpenAI

        effective_base_url = base_url or "https://api.openai.com/v1"
        client = OpenAI(api_key=api_key, base_url=effective_base_url)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        # 处理不同API返回格式
        if isinstance(response, str):
            return response
        if hasattr(response, 'choices') and response.choices:
            return response.choices[0].message.content
        return str(response)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude提供商"""

    def generate(self, model, prompt, system_prompt, api_key, base_url,
                 max_tokens, temperature, timeout):
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)

        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or "",
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text


class LocalLLMProvider(LLMProvider):
    """本地LLM提供商 (如Ollama)"""

    def generate(self, model, prompt, system_prompt, api_key, base_url,
                 max_tokens, temperature, timeout):
        effective_base_url = base_url or "http://localhost:11434"

        url = effective_base_url.rstrip("/") + "/api/chat"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt or ""},
                {"role": "user", "content": prompt}
            ],
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
            "stream": False
        }

        response = requests.post(url, json=payload, timeout=timeout)
        result = response.json()

        if "message" in result:
            return result["message"].get("content", "")
        return result.get("response", "")


def get_provider(name: str) -> LLMProvider:
    """获取提供商实例"""
    providers = {
        "deepseek": DeepSeekProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "claude": AnthropicProvider,
        "local": LocalLLMProvider,
        "ollama": LocalLLMProvider,
    }
    provider_class = providers.get(name.lower(), DeepSeekProvider)
    return provider_class()