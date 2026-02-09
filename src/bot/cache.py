"""视频总结缓存 — Proxy 模式.

在 AI 提供商前增加缓存代理层，对同一视频的重复请求
直接返回缓存结果，大幅降低 AI API 调用成本。

@see https://refactoring.guru/design-patterns/proxy

省钱关键：
- 同一视频被多次 @总结 时只调用一次 AI
- TTL 机制确保缓存不会无限增长
- LRU 淘汰策略控制内存占用
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict

logger = logging.getLogger(__name__)


class SummaryCache:
    """视频总结缓存（LRU + TTL）.

    使用 OrderedDict 实现 LRU 淘汰，
    每个条目带有过期时间戳。
    """

    def __init__(
        self, ttl: int = 86400, max_size: int = 500
    ) -> None:
        """初始化缓存.

        Args:
            ttl:      缓存过期时间（秒），默认 24 小时。
            max_size: 最大缓存条数。
        """
        self._ttl = ttl
        self._max_size = max_size
        self._cache: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, bvid: str) -> str | None:
        """查询缓存.

        Args:
            bvid: 视频 BV 号。

        Returns:
            缓存的总结文本，未命中返回 None。
        """
        entry = self._cache.get(bvid)
        if entry is None:
            self._misses += 1
            return None

        content, expire_at = entry
        if time.monotonic() > expire_at:
            # 已过期，移除
            del self._cache[bvid]
            self._misses += 1
            logger.debug("缓存过期: %s", bvid)
            return None

        # 命中，移到末尾（最近使用）
        self._cache.move_to_end(bvid)
        self._hits += 1
        logger.debug("缓存命中: %s (hits=%d)", bvid, self._hits)
        return content

    def put(self, bvid: str, content: str) -> None:
        """写入缓存.

        Args:
            bvid:    视频 BV 号。
            content: 总结文本。
        """
        # 淘汰超出容量的旧条目
        while len(self._cache) >= self._max_size:
            evicted_key, _ = self._cache.popitem(last=False)
            logger.debug("缓存淘汰: %s", evicted_key)

        expire_at = time.monotonic() + self._ttl
        self._cache[bvid] = (content, expire_at)
        self._cache.move_to_end(bvid)
        logger.debug("缓存写入: %s", bvid)

    @property
    def stats(self) -> dict[str, int]:
        """返回缓存统计信息."""
        return {
            "size": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "max_size": self._max_size,
        }
