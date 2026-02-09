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
        # 使用 dict 保留插入顺序（Python 3.7+），值为时间戳
        self._processed_ids: dict[int, int] = {}
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

            logger.debug("💤 等待 %d 秒后进行下次轮询...", self._poll_interval)
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
                # 记录最大时间戳
                self._last_at_time = max(n.timestamp for n in notifications)
                for n in notifications:
                    self._processed_ids[n.at_id] = n.timestamp
                logger.info(
                    "初始化完成，跳过 %d 条历史通知, last_at_time=%d",
                    len(notifications),
                    self._last_at_time,
                )
            else:
                # 无历史通知，使用当前时间戳（避免处理之后的旧通知）
                import time
                self._last_at_time = int(time.time())
                logger.info("初始化完成，无历史通知，last_at_time=%d", self._last_at_time)
        except Exception:
            # 初始化失败，使用当前时间戳，避免后续处理大量历史消息
            import time
            self._last_at_time = int(time.time())
            logger.warning(
                "初始化拉取失败，设置 last_at_time=%d，将在下次轮询重试",
                self._last_at_time,
                exc_info=True,
            )

    async def _poll_once(self) -> None:
        """执行一次轮询."""
        logger.info("⏱️ 轮询中...")
        notifications = await self._bili.fetch_at_notifications()

        if not notifications:
            logger.info("📭 无新通知")
            return

        # 过滤：只处理时间戳 >= 上次记录的通知，且未处理过的
        # 使用 >= 因为同一秒可能有多条通知
        new_notifications = [
            n for n in notifications
            if n.timestamp >= self._last_at_time
            and n.at_id not in self._processed_ids
        ]

        if not new_notifications:
            logger.info("📭 无新通知（时间戳 <= %d）", self._last_at_time)
            return

        logger.info("📬 发现 %d 条新 @通知", len(new_notifications))

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
            self._processed_ids[notif.at_id] = notif.timestamp

            # 回复间隔，避免触发 B站 风控
            await asyncio.sleep(3)

        # 更新最新时间戳（取所有新通知中的最大时间戳）
        if new_notifications:
            max_new_ts = max(n.timestamp for n in new_notifications)
            self._last_at_time = max(self._last_at_time, max_new_ts)

        # 清理过大的已处理 ID 集合（按插入顺序移除最早的）
        if len(self._processed_ids) > self._max_processed_ids:
            excess = len(self._processed_ids) - self._max_processed_ids // 2
            # dict 保持插入顺序，移除最早插入的
            keys_to_remove = list(self._processed_ids.keys())[:excess]
            for rid in keys_to_remove:
                del self._processed_ids[rid]
            logger.debug(
                "清理已处理 ID 集合, 移除 %d 条", excess
            )
