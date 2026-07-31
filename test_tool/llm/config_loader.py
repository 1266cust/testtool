from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Optional

from .client import LLMConfig


CONFIG_FILE_NAME = "llm_config.json"
ENV_FILE_NAME = ".env"


def find_config_file() -> Optional[Path]:
    """查找配置文件，优先级：项目目录 > 当前工作目录"""
    search_paths = [
        Path(__file__).resolve().parents[2] / CONFIG_FILE_NAME,  # 项目根目录
        Path.cwd() / CONFIG_FILE_NAME,  # 当前工作目录
        Path(__file__).resolve().parents[2] / ENV_FILE_NAME,  # .env文件
        Path.cwd() / ENV_FILE_NAME,
    ]

    for path in search_paths:
        if path.exists():
            return path
    return None


def load_llm_config_from_file(config_path: Optional[Path] = None) -> Optional[LLMConfig]:
    """从配置文件加载LLM配置"""
    if config_path is None:
        config_path = find_config_file()

    if config_path is None:
        return None

    try:
        if config_path.suffix == ".json":
            with config_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            return LLMConfig(
                provider=data.get("provider", "deepseek"),
                model_name=data.get("model_name", "deepseek-chat"),
                api_key=data.get("api_key"),
                base_url=data.get("base_url"),
                max_tokens=int(data.get("max_tokens", 4096)),
                temperature=float(data.get("temperature", 0.7)),
                vision_provider=data.get("vision_provider"),
                vision_model_name=data.get("vision_model_name"),
                vision_api_key=data.get("vision_api_key"),
                vision_base_url=data.get("vision_base_url"),
            )

        elif config_path.name == ".env":
            return load_llm_config_from_env_file(config_path)

    except Exception as e:
        print(f"加载配置文件失败: {e}")
        return None

    return None


def load_llm_config_from_env_file(env_path: Path) -> Optional[LLMConfig]:
    """从.env文件加载配置"""
    try:
        with env_path.open("r", encoding="utf-8") as f:
            content = f.read()

        config_map = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                config_map[key] = value

        return LLMConfig(
            provider=config_map.get("LLM_PROVIDER", "deepseek"),
            model_name=config_map.get("LLM_MODEL", "deepseek-chat"),
            api_key=config_map.get("LLM_API_KEY"),
            base_url=config_map.get("LLM_BASE_URL"),
            max_tokens=int(config_map.get("LLM_MAX_TOKENS", "4096")),
            temperature=float(config_map.get("LLM_TEMPERATURE", "0.7")),
        )

    except Exception as e:
        print(f"加载.env文件失败: {e}")
        return None


def load_llm_config_from_env() -> LLMConfig:
    """从环境变量加载LLM配置"""
    return LLMConfig(
        provider=os.environ.get("LLM_PROVIDER", "deepseek"),
        model_name=os.environ.get("LLM_MODEL", "deepseek-chat"),
        api_key=os.environ.get("LLM_API_KEY"),
        base_url=os.environ.get("LLM_BASE_URL"),
        max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "4096")),
        temperature=float(os.environ.get("LLM_TEMPERATURE", "0.7")),
    )


def load_llm_config() -> LLMConfig:
    """加载LLM配置，优先级：配置文件 > 环境变量"""
    # 优先从配置文件加载
    file_config = load_llm_config_from_file()
    if file_config and file_config.api_key:
        return file_config

    # 其次从环境变量加载
    env_config = load_llm_config_from_env()
    if env_config.api_key:
        return env_config

    # 返回默认配置（无API Key）
    return LLMConfig()


def get_env_api_key(provider: str) -> Optional[str]:
    """获取指定提供商的API Key"""
    env_key_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
    }

    env_key = env_key_map.get(provider.lower(), "LLM_API_KEY")
    return os.environ.get(env_key) or os.environ.get("LLM_API_KEY")