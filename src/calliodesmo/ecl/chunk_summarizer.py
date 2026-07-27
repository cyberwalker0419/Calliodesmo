"""LLMChunkSummarizer：经 LLMProvider 生成 ~100 token chunk 短摘要（L0）。

摘要不进稠密索引/不进 rerank 打分，仅入 metadata["summary"] 供展示与粗筛。
空 chunk / 超短 chunk 返回原文截断。
"""

from __future__ import annotations

from calliodesmo.interfaces.llm import LLMMessage, LLMProvider

_SYSTEM_PROMPT = "你是文档摘要引擎。为给定的文本块生成约 100 token 的超短摘要。仅返回摘要文本。"
_MIN_LENGTH = 50


class LLMChunkSummarizer:
    """L0 chunk 短摘要生成器。"""

    def __init__(self, llm: LLMProvider, *, enabled: bool = False) -> None:
        self._llm = llm
        self._enabled = enabled

    async def summarize(self, content: str) -> str:
        """生成 chunk 短摘要。空/超短返回原文截断。"""
        if not self._enabled:
            return ""
        if not content or len(content) < _MIN_LENGTH:
            return content[:200] if content else ""
        resp = await self._llm.complete(
            [
                LLMMessage(role="system", content=_SYSTEM_PROMPT),
                LLMMessage(role="user", content=content),
            ],
            temperature=0.0,
            max_tokens=128,
        )
        return resp.content.strip()
