"""数据模型 — B站 API 相关的领域实体."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AtNotification:
    """一条 @提醒通知."""

    at_id: int  # 通知 ID，用于去重
    source_id: int  # 评论 rpid
    root_id: int  # 根评论 rpid（0 表示自身即根评论）
    sender_uid: int  # 发送者 UID
    sender_name: str  # 发送者昵称
    bvid: str  # 视频 BV 号
    oid: int  # 评论区 oid（一般等于视频 aid）
    content: str  # @消息的文本内容
    timestamp: int  # 时间戳


@dataclass(frozen=True, slots=True)
class VideoInfo:
    """视频基本信息."""

    bvid: str
    aid: int
    title: str
    description: str
    owner_name: str
    duration: int  # 秒
    cid: int  # 第一个分P的 cid，用于获取字幕


@dataclass(slots=True)
class SubtitleContent:
    """视频字幕内容."""

    language: str
    body: str  # 合并后的纯文本字幕


@dataclass(slots=True)
class VideoContext:
    """发送给 AI 的完整视频上下文."""

    bvid: str
    title: str
    description: str
    owner_name: str
    duration_text: str
    subtitle: str | None = None  # 字幕文本，可能为空
    user_question: str = ""  # 用户额外问题

    def to_prompt(self) -> str:
        """将视频上下文格式化为 AI prompt."""
        parts = [
            f"视频标题：{self.title}",
            f"UP主：{self.owner_name}",
            f"时长：{self.duration_text}",
        ]
        if self.description:
            parts.append(f"视频简介：{self.description}")
        if self.subtitle:
            parts.append(f"视频字幕内容：\n{self.subtitle}")
        else:
            parts.append("（该视频没有字幕，请根据标题和简介进行总结）")

        if self.user_question:
            parts.append(f"\n用户的问题/要求：{self.user_question}")

        return "\n".join(parts)


@dataclass(slots=True)
class ReplyResult:
    """回复结果."""

    success: bool
    rpid: int = 0  # 回复的评论 ID
    message: str = ""
