"""B站 API 客户端 — Adapter 模式封装 B站 HTTP API.

将 B站复杂的 HTTP API 适配为简洁的领域接口，
隔离外部 API 变化对业务逻辑的影响。
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.bilibili.models import (
    AtNotification,
    ReplyResult,
    SubtitleContent,
    VideoInfo,
)

logger = logging.getLogger(__name__)

# ── B站 API 端点 ──────────────────────────────────────────────
_API_BASE = "https://api.bilibili.com"
_AT_FEED_URL = f"{_API_BASE}/x/msgfeed/at"
_VIDEO_INFO_URL = f"{_API_BASE}/x/web-interface/view"
_REPLY_ADD_URL = f"{_API_BASE}/x/v2/reply/add"
_PLAYER_WBI_URL = f"{_API_BASE}/x/player/wbi/v2"
_RELATION_URL = f"{_API_BASE}/x/relation/stat"  # 用户关系统计
_FOLLOWER_CHECK_URL = f"{_API_BASE}/x/relation"  # 检查关注关系

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com",
    "Origin": "https://www.bilibili.com",
}


class BilibiliClientError(Exception):
    """B站 API 调用异常."""


class BilibiliClient:
    """B站 API 适配器 — 将 HTTP API 转化为领域方法.

    职责：
    - 管理认证 Cookie
    - 封装 API 请求/响应
    - 异常处理与重试
    """

    def __init__(self, sessdata: str, bili_jct: str, uid: int) -> None:
        self._bili_jct = bili_jct
        self._uid = uid
        self._cookies = {
            "SESSDATA": sessdata,
            "bili_jct": bili_jct,
        }
        self._client = httpx.AsyncClient(
            headers=_HEADERS,
            cookies=self._cookies,
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ── 用户关系检查 ──────────────────────────────────────────

    async def is_user_following_me(self, user_uid: int) -> bool:
        """检查指定用户是否关注了当前账号.

        Args:
            user_uid: 要检查的用户 UID。

        Returns:
            True 表示用户已关注，False 表示未关注。
        """
        try:
            # 使用 x/relation 接口查询关系
            # attribute: 0=未关注, 1=关注, 2=被关注, 6=互相关注, 128=拉黑
            resp = await self._client.get(
                _FOLLOWER_CHECK_URL,
                params={"fid": user_uid},  # fid 是要查询的用户
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                logger.warning(
                    "查询用户关系失败: uid=%d, msg=%s",
                    user_uid,
                    data.get("message"),
                )
                return False

            # attribute 表示"我"对"fid"的关系
            # be_relation.attribute 表示"fid"对"我"的关系
            be_relation = data.get("data", {}).get("be_relation", {})
            attr = be_relation.get("attribute", 0)

            # 2=被关注, 6=互相关注 表示对方关注了我
            is_following = attr in (2, 6)
            logger.debug(
                "用户关系检查: uid=%d, be_relation_attr=%d, is_following=%s",
                user_uid,
                attr,
                is_following,
            )
            return is_following

        except Exception:
            logger.warning("检查用户关系异常: uid=%d", user_uid, exc_info=True)
            # 出错时默认允许，避免误伤
            return True

    # ── @提醒通知 ─────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10),
        retry=retry_if_exception_type(httpx.TransportError),
    )
    async def fetch_at_notifications(
        self, last_at_time: int = 0  # noqa: ARG002
    ) -> list[AtNotification]:
        """拉取 @提醒列表.

        Args:
            last_at_time: 已废弃，B站 API 的 at_time 是向后翻页用的，
                         不是获取新通知。我们总是获取最新通知，在调用方过滤。

        Returns:
            按时间倒序排列的 @通知列表。
        """
        # 注意：B站 at_time 参数是获取该时间之前的通知（翻页），不是之后的新通知
        # 所以我们始终不传 at_time，获取最新的通知列表
        params: dict[str, Any] = {"build": 0, "mobi_app": "web"}

        resp = await self._client.get(_AT_FEED_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            raise BilibiliClientError(
                f"获取 @通知失败: code={data.get('code')}, "
                f"message={data.get('message')}"
            )

        items = data.get("data", {}).get("items", [])
        notifications: list[AtNotification] = []

        for item in items:
            try:
                notif = self._parse_at_item(item)
                if notif:
                    notifications.append(notif)
            except Exception:
                logger.warning("解析 @通知条目失败: %s", item, exc_info=True)

        return notifications

    def _parse_at_item(self, item: dict) -> AtNotification | None:
        """解析单条 @通知原始数据."""
        # item.item 包含评论信息
        inner = item.get("item", {})
        subject_id = inner.get("subject_id", 0)
        source_id = inner.get("source_id", 0)
        root_id = inner.get("root_id", 0)
        target_id = inner.get("target_id", 0)  # noqa: F841
        at_time = item.get("at_time", 0)

        # 发送者信息
        user = item.get("user", {})
        sender_uid = user.get("mid", 0)
        sender_name = user.get("nickname", "")

        # 评论内容
        content = inner.get("source_content", "")

        # 获取 bvid：从 item.item.uri 或 native_uri 中提取
        uri = inner.get("uri", "") or inner.get("native_uri", "")
        bvid = self._extract_bvid(uri)
        if not bvid:
            logger.debug("无法从 URI 提取 BV 号: %s", uri)
            return None

        return AtNotification(
            at_id=item.get("id", 0),
            source_id=source_id,
            root_id=root_id,
            sender_uid=sender_uid,
            sender_name=sender_name,
            bvid=bvid,
            oid=subject_id,
            content=content,
            timestamp=at_time,
        )

    @staticmethod
    def _extract_bvid(uri: str) -> str | None:
        """从 URL 中提取 BV 号."""
        match = re.search(r"(BV[\w]{10})", uri)
        return match.group(1) if match else None

    # ── 视频信息 ──────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10),
        retry=retry_if_exception_type(httpx.TransportError),
    )
    async def fetch_video_info(self, bvid: str) -> VideoInfo:
        """获取视频基本信息.

        Args:
            bvid: 视频 BV 号。

        Returns:
            VideoInfo 领域对象。
        """
        resp = await self._client.get(
            _VIDEO_INFO_URL, params={"bvid": bvid}
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            raise BilibiliClientError(
                f"获取视频信息失败 ({bvid}): {data.get('message')}"
            )

        d = data["data"]
        pages = d.get("pages", [])
        cid = pages[0]["cid"] if pages else d.get("cid", 0)

        return VideoInfo(
            bvid=d["bvid"],
            aid=d["aid"],
            title=d["title"],
            description=d.get("desc", ""),
            owner_name=d.get("owner", {}).get("name", ""),
            duration=d.get("duration", 0),
            cid=cid,
        )

    # ── 字幕获取 ──────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10),
        retry=retry_if_exception_type(httpx.TransportError),
    )
    async def fetch_subtitle(
        self, bvid: str, cid: int
    ) -> SubtitleContent | None:
        """获取视频字幕（AI 生成的 CC 字幕优先）.

        Args:
            bvid: 视频 BV 号。
            cid:  分P 的 cid。

        Returns:
            SubtitleContent 或 None（无字幕时）。
        """
        # 通过 player/wbi/v2 接口获取字幕列表
        params = {"bvid": bvid, "cid": cid}
        resp = await self._client.get(_PLAYER_WBI_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        subtitle_info = (
            data.get("data", {}).get("subtitle", {}).get("subtitles", [])
        )

        if not subtitle_info:
            logger.info("视频 %s 无字幕", bvid)
            return None

        # 优先选择中文字幕
        chosen = subtitle_info[0]
        for sub in subtitle_info:
            lang = sub.get("lan", "")
            if lang.startswith("zh") or lang.startswith("ai-zh"):
                chosen = sub
                break

        subtitle_url = chosen.get("subtitle_url", "")
        if not subtitle_url:
            return None

        # 补全协议
        if subtitle_url.startswith("//"):
            subtitle_url = "https:" + subtitle_url

        return await self._download_subtitle(
            subtitle_url, chosen.get("lan", "unknown")
        )

    async def _download_subtitle(
        self, url: str, language: str
    ) -> SubtitleContent | None:
        """下载并解析字幕 JSON."""
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.warning("下载字幕失败: %s", url, exc_info=True)
            return None

        body_items = data.get("body", [])
        if not body_items:
            return None

        # 合并所有字幕行为纯文本
        lines = [item.get("content", "") for item in body_items]
        body_text = " ".join(lines)

        return SubtitleContent(language=language, body=body_text)

    # ── 发送回复 ──────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=3, max=15),
        retry=retry_if_exception_type(httpx.TransportError),
    )
    async def send_reply(
        self,
        oid: int,
        root: int,
        parent: int,
        message: str,
    ) -> ReplyResult:
        """发送评论回复.

        Args:
            oid:     评论区 ID（一般等于视频 aid）。
            root:    根评论 rpid（楼主评论 ID）。
            parent:  父评论 rpid（直接回复的评论 ID）。
            message: 回复文本内容。

        Returns:
            ReplyResult 表示回复结果。
        """
        form_data = {
            "oid": str(oid),
            "type": "1",  # 1 = 视频评论区
            "root": str(root),
            "parent": str(parent),
            "message": message,
            "csrf": self._bili_jct,
        }

        resp = await self._client.post(_REPLY_ADD_URL, data=form_data)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            msg = data.get("message", "unknown error")
            logger.error("回复失败: %s", msg)
            return ReplyResult(success=False, message=msg)

        rpid = data.get("data", {}).get("rpid", 0)
        logger.info("回复成功, rpid=%d", rpid)
        return ReplyResult(success=True, rpid=rpid)
