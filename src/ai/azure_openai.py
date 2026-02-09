"""Azure OpenAI 策略实现 — Strategy 模式的具体策略.

使用 Azure OpenAI GPT 模型生成视频总结和回答。
"""

from __future__ import annotations

import logging

from openai import AsyncAzureOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.ai.base import AIProvider

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_SUMMARY = """你是一个 B站视频内容总结助手。
用户会给你一个视频的标题、简介和字幕内容，请你生成一个简洁明了的总结。
要求：
1. 总结控制在 300 字以内
2. 用条理清晰的方式组织（可以用序号列表）
3. 提炼出视频的核心观点和关键信息
4. 语气友好、自然，像一个热心的 B站用户
5. 不要提及"字幕"、"根据字幕"等词汇，直接总结内容"""

_SYSTEM_PROMPT_QA = """你是一个 B站视频内容问答助手。
用户会给你一个视频的标题、简介和字幕内容，以及一个具体的问题。
请你根据视频内容回答问题。
要求：
1. 回答控制在 300 字以内
2. 如果视频内容中没有相关信息，诚实说明
3. 语气友好、自然，像一个热心的 B站用户
4. 不要提及"字幕"、"根据字幕"等词汇"""


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
        retry=retry_if_exception_type(Exception),
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
            max_tokens=800,
            temperature=0.7,
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
        retry=retry_if_exception_type(Exception),
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
            max_tokens=800,
            temperature=0.7,
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
