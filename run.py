"""Bilibili AI 评论机器人 — 入口点.

启动流程：
1. 加载配置
2. 初始化组件（依赖注入）
3. 启动 @提醒轮询器
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.ai.azure_openai import AzureOpenAIProvider  # noqa: E402
from src.bilibili.client import BilibiliClient  # noqa: E402
from src.bot.cache import SummaryCache  # noqa: E402
from src.bot.monitor import AtMonitor  # noqa: E402
from src.bot.processor import MessageProcessor  # noqa: E402
from src.config.keyvault import KeyVaultSecretProvider  # noqa: E402
from src.config.settings import load_config  # noqa: E402


def _setup_logging(level: str) -> None:
    """配置日志."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=(
            "%(asctime)s | %(levelname)-7s | %(name)-25s | %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # 降低第三方库日志级别
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def main() -> None:
    """主入口 — 组装依赖并启动."""
    # 1. 加载配置
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    config = load_config(config_path)

    # 2. 配置日志
    _setup_logging(config.logging.level)
    logger = logging.getLogger("bilibili-bot")

    logger.info("=" * 50)
    logger.info("  Bilibili AI 评论机器人 启动")
    logger.info("=" * 50)

    # 3. 依赖注入 — 组装组件
    # Adapter: Key Vault 密钥提供者
    keyvault_provider = KeyVaultSecretProvider(
        vault_url=config.keyvault.vault_url,
    )
    api_key = keyvault_provider.get_secret(
        config.keyvault.api_key_secret_name,
    )
    sessdata = keyvault_provider.get_secret(
        config.keyvault.sessdata_secret_name,
    )
    bili_jct = keyvault_provider.get_secret(
        config.keyvault.bili_jct_secret_name,
    )
    uid = int(keyvault_provider.get_secret(
        config.keyvault.uid_secret_name,
    ))
    logger.info("已从 Key Vault 获取所有密钥 (API Key, SESSDATA, bili_jct, UID)")

    # Adapter: B站 API 客户端
    bili_client = BilibiliClient(
        sessdata=sessdata,
        bili_jct=bili_jct,
        uid=uid,
    )

    # Strategy: AI 提供商
    ai_provider = AzureOpenAIProvider(
        endpoint=config.azure_openai.endpoint,
        api_key=api_key,
        deployment=config.azure_openai.deployment,
        api_version=config.azure_openai.api_version,
    )

    # Proxy: 缓存
    cache = SummaryCache(
        ttl=config.bot.cache_ttl,
        max_size=config.bot.cache_max_size,
    )

    # 消息处理器
    processor = MessageProcessor(
        bili_client=bili_client,
        ai_provider=ai_provider,
        cache=cache,
        max_subtitle_chars=config.bot.max_subtitle_chars,
        reply_prefix=config.bot.reply_prefix,
        max_reply_chars=config.bot.max_reply_chars,
    )

    # @监控器
    monitor = AtMonitor(
        bili_client=bili_client,
        processor=processor,
        poll_interval=config.bot.poll_interval,
    )

    # 4. 优雅关闭
    async def shutdown() -> None:
        logger.info("正在关闭...")
        await monitor.stop()
        await bili_client.close()
        await ai_provider.close()
        keyvault_provider.close()
        logger.info("已关闭, 缓存统计: %s", cache.stats)

    # 注册信号处理
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            pass

    # 5. 启动
    logger.info(
        "配置: 轮询间隔=%ds, 字幕上限=%d字, 缓存TTL=%ds",
        config.bot.poll_interval,
        config.bot.max_subtitle_chars,
        config.bot.cache_ttl,
    )

    try:
        await monitor.run()
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C, 正在关闭...")
    finally:
        await shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
