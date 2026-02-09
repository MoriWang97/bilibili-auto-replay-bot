"""消息处理器 — 编排视频信息获取、AI 总结、回复发送.

遵循 Single Responsibility：只负责单条 @通知的处理流程编排，
不关心通知如何获取（Monitor 的职责）。
"""

from __future__ import annotations

import logging
import re

from src.ai.base import AIProvider
from src.bilibili.client import BilibiliClient
from src.bilibili.models import AtNotification, VideoContext
from src.bot.cache import SummaryCache

logger = logging.getLogger(__name__)

# 匹配 @用户名 部分，用于从评论内容中提取用户实际问题
_AT_PATTERN = re.compile(r"@[\w\-]+\s*")

# 识别总结意图的关键词
_SUMMARY_KEYWORDS = {"总结", "概括", "摘要", "说了什么", "讲了什么", "内容是什么", "说了啥", "讲了啥"}


class MessageProcessor:
    """处理单条 @通知的完整流程.

    编排流程：
    1. 获取视频信息
    2. 获取字幕
    3. 检查缓存 / 调用 AI 生成总结
    4. 发送回复
    """

    def __init__(
        self,
        bili_client: BilibiliClient,
        ai_provider: AIProvider,
        cache: SummaryCache,
        *,
        max_subtitle_chars: int = 8000,
        reply_prefix: str = "【AI总结】",
        max_reply_chars: int = 900,
    ) -> None:
        self._bili = bili_client
        self._ai = ai_provider
        self._cache = cache
        self._max_subtitle_chars = max_subtitle_chars
        self._reply_prefix = reply_prefix
        self._max_reply_chars = max_reply_chars

    async def process(self, notification: AtNotification) -> bool:
        """处理一条 @通知.

        Args:
            notification: @通知对象。

        Returns:
            True 表示处理成功，False 表示失败。
        """
        bvid = notification.bvid
        logger.info(
            "处理 @通知: sender=%s bvid=%s content='%s'",
            notification.sender_name,
            bvid,
            notification.content[:50],
        )

        try:
            # 1. 获取视频信息
            video = await self._bili.fetch_video_info(bvid)

            # 2. 解析用户意图
            user_text = self._extract_user_question(notification.content)
            is_summary = self._is_summary_request(user_text)

            # 3. 尝试缓存（仅总结请求可缓存）
            if is_summary:
                cached = self._cache.get(bvid)
                if cached:
                    logger.info("使用缓存总结: %s", bvid)
                    reply_text = self._format_reply(cached)
                    return await self._send_reply(notification, reply_text)

            # 4. 获取字幕
            subtitle_text = None
            subtitle = await self._bili.fetch_subtitle(bvid, video.cid)
            if subtitle:
                subtitle_text = subtitle.body[: self._max_subtitle_chars]

            # 5. 构建视频上下文
            duration_min = video.duration // 60
            duration_sec = video.duration % 60
            context = VideoContext(
                bvid=bvid,
                title=video.title,
                description=video.description[:500],
                owner_name=video.owner_name,
                duration_text=f"{duration_min}分{duration_sec}秒",
                subtitle=subtitle_text,
                user_question=user_text if not is_summary else "",
            )

            # 6. 调用 AI
            if is_summary:
                ai_result = await self._ai.summarize_video(
                    context.to_prompt()
                )
                # 写入缓存
                self._cache.put(bvid, ai_result)
            else:
                ai_result = await self._ai.answer_question(
                    context.to_prompt(), user_text
                )

            # 7. 发送回复
            reply_text = self._format_reply(ai_result)
            return await self._send_reply(notification, reply_text)

        except Exception:
            logger.error(
                "处理 @通知失败: bvid=%s", bvid, exc_info=True
            )
            return False

    def _extract_user_question(self, content: str) -> str:
        """从评论内容中提取用户实际问题（去掉 @xxx 部分）."""
        cleaned = _AT_PATTERN.sub("", content).strip()
        return cleaned

    def _is_summary_request(self, text: str) -> bool:
        """判断是否为总结请求（而非具体问题）.

        无文本或包含总结关键词 → 总结请求；
        有具体问题 → 问答请求。
        """
        if not text:
            return True
        return any(kw in text for kw in _SUMMARY_KEYWORDS)

    def _format_reply(self, ai_text: str) -> str:
        """格式化回复文本，加前缀并截断."""
        reply = f"{self._reply_prefix}\n{ai_text}"
        if len(reply) > self._max_reply_chars:
            reply = reply[: self._max_reply_chars - 3] + "..."
        return reply

    async def _send_reply(
        self, notification: AtNotification, text: str
    ) -> bool:
        """发送评论回复."""
        # 确定 root 和 parent
        if notification.root_id == 0:
            # @在根评论中，root 和 parent 都是 source_id
            root = notification.source_id
            parent = notification.source_id
        else:
            root = notification.root_id
            parent = notification.source_id

        result = await self._bili.send_reply(
            oid=notification.oid,
            root=root,
            parent=parent,
            message=text,
        )
        if result.success:
            logger.info(
                "回复成功: bvid=%s rpid=%d", notification.bvid, result.rpid
            )
        else:
            logger.warning(
                "回复失败: bvid=%s msg=%s",
                notification.bvid,
                result.message,
            )
        return result.success
