"""配置管理 — 加载 YAML 配置文件.

使用 pydantic-settings 进行配置校验，
确保必填项不为空、类型正确。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator


class AzureOpenAIConfig(BaseModel):
    """Azure OpenAI 相关配置."""

    endpoint: str
    deployment: str = "gpt-52"
    api_version: str = "2025-04-01-preview"

    @field_validator("endpoint")
    @classmethod
    def not_placeholder(cls, v: str) -> str:
        if "your_" in v or not v.strip():
            raise ValueError(
                "请填入真实的 Azure OpenAI 配置值"
            )
        return v.strip()


class KeyVaultConfig(BaseModel):
    """Azure Key Vault 配置."""

    vault_url: str
    api_key_secret_name: str = "AzureAI--ApiKey"
    sessdata_secret_name: str = "Bili--Sessdata"
    bili_jct_secret_name: str = "Bili--JCT"
    uid_secret_name: str = "Bili--UID"

    @field_validator("vault_url")
    @classmethod
    def not_placeholder(cls, v: str) -> str:
        if "your_" in v or not v.strip():
            raise ValueError(
                "请填入真实的 Key Vault URL"
            )
        return v.strip()


class BotConfig(BaseModel):
    """机器人行为配置."""

    poll_interval: int = 30
    max_subtitle_chars: int = 8000
    cache_ttl: int = 86400
    cache_max_size: int = 500
    reply_prefix: str = "【AI总结】"
    max_reply_chars: int = 900


class LoggingConfig(BaseModel):
    """日志配置."""

    level: str = "INFO"


class AppConfig(BaseModel):
    """应用总配置."""

    azure_openai: AzureOpenAIConfig
    keyvault: KeyVaultConfig
    bot: BotConfig = BotConfig()
    logging: LoggingConfig = LoggingConfig()


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """加载配置文件.

    按优先级查找配置文件：
    1. 指定路径
    2. config/config.yaml
    3. config.yaml

    Args:
        config_path: 配置文件路径（可选）。

    Returns:
        AppConfig 对象。
    """
    search_paths = [
        Path("config/config.yaml"),
        Path("config.yaml"),
    ]

    if config_path:
        path = Path(config_path)
    else:
        path = None
        for sp in search_paths:
            if sp.exists():
                path = sp
                break

    if path is None or not path.exists():
        print(
            "❌ 找不到配置文件！请复制 config/config.example.yaml "
            "为 config/config.yaml 并填入你的信息。"
        )
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    try:
        return AppConfig(**raw)
    except Exception as e:
        print(f"❌ 配置文件校验失败: {e}")
        sys.exit(1)
