"""@提醒轮询监控器 — 定期检查新的 @通知并分发处理.

遵循 Single Responsibility：只负责轮询调度和通知去重，
具体处理逻辑委托给 MessageProcessor。
"""

from __future__ import annotations

import asyncio
import logging

from src.bilibili.client import BilibiliClient
from src.bot.processor import MessageProcessor

logger = logging.getLogger(__name__)


class AtMonitor:
    """@提醒轮询监控器.

    职责：
    - 定期拉取 @通知
    - 去重（防止重复处理）
    - 将新通知分发给 MessageProcessor

    使用方式：
        monitor = AtMonitor(bili_client, processor, poll_interval=30)
        await monitor.run()  # 阻塞运行
    """

    def __init__(
        self,
        bili_client: BilibiliClient,
        processor: MessageProcessor,
        *,
        poll_interval: int = 30,
    ) -> None:
        self._bili = bili_client
        self._processor = processor
        self._poll_interval = poll_interval
        self._last_at_time: int = 0
        self._processed_ids: set[int] = set()
        self._running = False
        # 限制已处理 ID 集合的大小，防止内存泄漏
        self._max_processed_ids = 10000

    async def run(self) -> None:
        """启动轮询循环（阻塞）."""
        self._running = True
        logger.info(
            "🚀 @监控器启动，轮询间隔 %d 秒", self._poll_interval
        )

        # 首次拉取：只记录 at_time，不处理（避免回复历史消息）
        await self._initialize()

        while self._running:
            try:
                await self._poll_once()
            except Exception:
                logger.error("轮询异常", exc_info=True)

            await asyncio.sleep(self._poll_interval)

    async def stop(self) -> None:
        """停止轮询."""
        self._running = False
        logger.info("@监控器停止")

    async def _initialize(self) -> None:
        """首次拉取，记录当前最新时间戳，不处理历史通知."""
        try:
            notifications = await self._bili.fetch_at_notifications()
            if notifications:
                self._last_at_time = notifications[0].timestamp
                for n in notifications:
                    self._processed_ids.add(n.at_id)
                logger.info(
                    "初始化完成，跳过 %d 条历史通知, last_at_time=%d",
                    len(notifications),
                    self._last_at_time,
                )
            else:
                logger.info("初始化完成，无历史通知")
        except Exception:
            logger.warning("初始化拉取失败，将在下次轮询重试", exc_info=True)

    async def _poll_once(self) -> None:
        """执行一次轮询."""
        notifications = await self._bili.fetch_at_notifications(
            last_at_time=self._last_at_time
        )

        if not notifications:
            return

        # 过滤已处理的通知
        new_notifications = [
            n for n in notifications if n.at_id not in self._processed_ids
        ]

        if not new_notifications:
            return

        logger.info("发现 %d 条新 @通知", len(new_notifications))

        # 按时间正序处理（先旧后新）
        for notif in reversed(new_notifications):
            try:
                success = await self._processor.process(notif)
                if success:
                    logger.info(
                        "✅ 处理成功: sender=%s bvid=%s",
                        notif.sender_name,
                        notif.bvid,
                    )
                else:
                    logger.warning(
                        "⚠️ 处理失败: sender=%s bvid=%s",
                        notif.sender_name,
                        notif.bvid,
                    )
            except Exception:
                logger.error(
                    "❌ 处理异常: sender=%s bvid=%s",
                    notif.sender_name,
                    notif.bvid,
                    exc_info=True,
                )

            # 无论成功失败，都标记为已处理（避免重复尝试）
            self._processed_ids.add(notif.at_id)

            # 回复间隔，避免触发 B站 风控
            await asyncio.sleep(3)

        # 更新最新时间戳
        self._last_at_time = max(
            self._last_at_time, notifications[0].timestamp
        )

        # 清理过大的已处理 ID 集合
        if len(self._processed_ids) > self._max_processed_ids:
            excess = len(self._processed_ids) - self._max_processed_ids // 2
            # 移除最早的一些 ID
            to_remove = list(self._processed_ids)[:excess]
            for rid in to_remove:
                self._processed_ids.discard(rid)
            logger.debug(
                "清理已处理 ID 集合, 移除 %d 条", excess
            )
