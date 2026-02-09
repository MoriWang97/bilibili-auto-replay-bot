"""Azure Key Vault 密钥提供者 — Adapter 模式.

将 Azure Key Vault SDK 适配为统一的密钥获取接口，
使上层业务逻辑不依赖具体的密钥存储实现。

@see https://refactoring.guru/design-patterns/adapter
"""

from __future__ import annotations

import logging

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

logger = logging.getLogger(__name__)


class KeyVaultSecretProvider:
    """Azure Key Vault 密钥适配器.

    封装 Azure Key Vault SDK，提供简洁的密钥获取接口。
    使用 DefaultAzureCredential 支持多种认证方式:
    - 本地开发: Azure CLI / VS Code 登录
    - 生产环境: Managed Identity / 环境变量
    """

    def __init__(self, vault_url: str) -> None:
        """初始化 Key Vault 客户端.

        Args:
            vault_url: Key Vault 的 URL (如 https://xxx.vault.azure.net/)
        """
        self._vault_url = vault_url
        self._credential = DefaultAzureCredential()
        self._client = SecretClient(
            vault_url=vault_url,
            credential=self._credential,
        )
        logger.info("Key Vault 客户端已初始化: %s", vault_url)

    def get_secret(self, secret_name: str) -> str:
        """从 Key Vault 获取密钥值.

        Args:
            secret_name: 密钥名称。

        Returns:
            密钥的字符串值。

        Raises:
            ValueError: 密钥不存在或值为空。
            azure.core.exceptions.HttpResponseError: Key Vault 访问失败。
        """
        logger.debug("正在从 Key Vault 获取密钥: %s", secret_name)
        secret = self._client.get_secret(secret_name)

        if secret.value is None:
            raise ValueError(
                f"Key Vault 密钥 '{secret_name}' 的值为空"
            )

        logger.info("成功获取密钥: %s", secret_name)
        return secret.value

    def close(self) -> None:
        """释放 Key Vault 客户端资源."""
        self._client.close()
        self._credential.close()
        logger.debug("Key Vault 客户端已关闭")
