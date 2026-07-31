from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMGenerationConfig:
    """LLM生成配置"""
    enabled: bool = True
    provider: str = "deepseek"
    model_name: str = "deepseek-chat"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.7

    enable_smart_test_points: bool = True
    enable_smart_cases: bool = True
    enable_case_review: bool = True
    enable_auto_fix: bool = True

    max_cases_per_point: int = 5

    vision_provider: Optional[str] = None
    vision_model_name: Optional[str] = None
    vision_api_key: Optional[str] = None
    vision_base_url: Optional[str] = None

    @property
    def has_vision_model(self) -> bool:
        return bool(self.vision_provider and self.vision_model_name and self.vision_api_key)


@dataclass
class GenerationConfig:
    """测试用例生成配置"""
    system_name: str = "目标系统"
    base_url: str = "<base_url>"
    admin_user: str = "<admin_user>"
    normal_user: str = "<normal_user>"
    dataset_prefix: str = "Batch-<yyyymmdd>-<seq>"
    verify_level: str = "ui+api+db+log"

    llm_config: LLMGenerationConfig = field(default_factory=LLMGenerationConfig)
    review_enabled: bool = True
    auto_fix_enabled: bool = True