"""AI 策略接口 — Strategy 模式的抽象基类.

定义 AI 提供商的统一接口，允许运行时切换不同的 AI 后端
（Azure OpenAI、OpenAI、本地模型等），而不影响业务逻辑。

@see https://refactoring.guru/design-patterns/strategy
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class AIProvider(ABC):
    """AI 提供商策略接口.

    所有 AI 后端实现必须遵循此接口，
    确保 Liskov 替换原则：任何子类都可以无缝替换。
    """

    @abstractmethod
    async def summarize_video(self, video_context: str) -> str:
        """根据视频上下文生成总结.

        Args:
            video_context: 格式化后的视频信息文本（标题+简介+字幕）。

        Returns:
            AI 生成的总结文本。
        """

    @abstractmethod
    async def answer_question(
        self, video_context: str, question: str
    ) -> str:
        """根据视频上下文回答用户问题.

        Args:
            video_context: 格式化后的视频信息文本。
            question:      用户的具体问题。

        Returns:
            AI 生成的回答文本。
        """

    @abstractmethod
    async def close(self) -> None:
        """释放资源."""
