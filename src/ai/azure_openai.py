"""Azure OpenAI 策略实现 — Strategy 模式的具体策略.

使用 Azure OpenAI GPT 模型生成视频总结和回答。
"""

from __future__ import annotations

import logging

from openai import APIConnectionError, APITimeoutError, AsyncAzureOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.ai.base import AIProvider

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_SUMMARY = """你是一个 B站视频内容总结助手。
用户会给你一个视频的标题、简介和带时间戳的字幕内容，请你生成一个带时间线的总结。

【核心原则 — 最高优先级】
- 你只能基于提供的字幕内容进行总结，严禁编造、推测或脑补任何未在字幕中出现的信息
- 如果字幕内容缺失、极少（例如只有几句话）、不完整或无实质内容，你必须直接回复：
  "该视频字幕内容不足，无法生成有效总结 😅 建议直接观看视频~"
- 不要试图根据视频标题或简介去猜测、扩展或编造视频的具体内容
- 如果字幕中只有背景音乐描述、语气词、或无意义的片段，同样视为无有效内容

【格式要求】
- 这是B站评论区，不支持任何 Markdown 语法！
- 禁止使用 **粗体**、*斜体*、# 标题、- 列表 等 Markdown 格式
- 必须在每个要点前标注时间戳，格式如 00:00 或 1:23:45
- B站评论区的时间戳格式可以被点击跳转，所以务必准确标注
- 每个要点独占一行，保持简洁
- 适合手机端阅读

【时间戳格式示例】
00:00 开场介绍主题
02:15 第一个核心观点
05:30 案例分析
08:45 总结和结论

【内容要求】
- 总结控制在 300 字以内
- 提炼 4-6 个关键时间节点
- 时间戳要尽量精确到相关内容开始的位置
- 每一个总结要点都必须有字幕原文作为依据
- 语气友好自然，像热心的 B站用户
- 不要提及"字幕"、"根据字幕"等词汇"""

_SYSTEM_PROMPT_QA = """你是一个 B站视频内容问答助手。
用户会给你一个视频的标题、简介和带时间戳的字幕内容，以及一个具体的问题。

【核心原则 — 最高优先级】
- 你只能基于提供的字幕内容来回答问题，严禁编造、推测或脑补任何未在字幕中出现的信息
- 如果字幕内容缺失、极少、不完整或无实质内容，你必须直接回复：
  "该视频字幕内容不足，无法回答你的问题 😅 建议直接观看视频~"
- 不要试图根据视频标题或简介去猜测答案
- 如果用户的问题在字幕中找不到相关信息，诚实说明视频中未提及该内容

【格式要求】
- 这是B站评论区，不支持任何 Markdown 语法！
- 禁止使用 **粗体**、*斜体*、# 标题 等 Markdown 格式
- 如果答案在视频特定位置，请标注时间戳（如 05:30）方便跳转
- 直接用纯文本回答，可用 emoji 点缀
- 适合手机端阅读

【内容要求】
- 回答控制在 250 字以内
- 如果能定位到具体时间点，请标注时间戳
- 每一个回答都必须有字幕原文作为依据
- 语气友好自然，像热心的 B站用户
- 不要提及"字幕"、"根据字幕"等词汇"""


class AzureOpenAIProvider(AIProvider):
    """Azure OpenAI 具体策略.

    封装 Azure OpenAI API 调用，实现 AIProvider 策略接口。
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        api_version: str = "2025-01-01-preview",
    ) -> None:
        self._deployment = deployment
        self._client = AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=15),
        retry=retry_if_exception_type((APIConnectionError, APITimeoutError)),
    )
    async def summarize_video(self, video_context: str) -> str:
        """调用 Azure OpenAI 生成视频总结."""
        logger.debug("调用 AI 生成总结, 上下文长度: %d", len(video_context))

        response = await self._client.chat.completions.create(
            model=self._deployment,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT_SUMMARY},
                {"role": "user", "content": video_context},
            ],
            max_completion_tokens=800,
            temperature=0.3,
        )

        result = response.choices[0].message.content or ""
        logger.info(
            "AI 总结生成完成, tokens: prompt=%s completion=%s",
            response.usage.prompt_tokens if response.usage else "?",
            response.usage.completion_tokens if response.usage else "?",
        )
        return result.strip()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=15),
        retry=retry_if_exception_type((APIConnectionError, APITimeoutError)),
    )
    async def answer_question(
        self, video_context: str, question: str
    ) -> str:
        """调用 Azure OpenAI 回答关于视频的问题."""
        logger.debug("调用 AI 回答问题: %s", question[:50])

        user_message = f"{video_context}\n\n用户问题：{question}"

        response = await self._client.chat.completions.create(
            model=self._deployment,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT_QA},
                {"role": "user", "content": user_message},
            ],
            max_completion_tokens=800,
            temperature=0.5,
        )

        result = response.choices[0].message.content or ""
        logger.info(
            "AI 回答生成完成, tokens: prompt=%s completion=%s",
            response.usage.prompt_tokens if response.usage else "?",
            response.usage.completion_tokens if response.usage else "?",
        )
        return result.strip()

    async def close(self) -> None:
        """关闭 Azure OpenAI 客户端."""
        await self._client.close()
