"""SeedExtractor：从 query 抽取种子实体名，经 GraphStore 验证有效。

轻量 NER/LLM：用 LLMProvider 从 query 抽取实体名列表，再验证命中 GraphStore。
未命中的过滤掉，仅保留图中存在的实体作为种子。
"""

from __future__ import annotations

import json

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.graph_store import GraphStore
from calliodesmo.interfaces.llm import LLMMessage, LLMProvider

_SYSTEM_PROMPT = (
    "你是种子实体抽取引擎。从用户的问题中提取可能出现在知识图谱中的实体名。"
    '返回 JSON 数组格式，如 ["OpenAI", "GPT-4"]。仅返回 JSON 数组，不加解释。'
)


class SeedExtractor:
    """从 query 抽种子实体名，命中 GraphStore 的保留，未命中过滤。"""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def extract(self, query: str, *, access: AccessContext, graph: GraphStore) -> list[str]:
        """返回经 GraphStore 验证的种子实体名列表。"""
        resp = await self._llm.complete(
            [
                LLMMessage(role="system", content=_SYSTEM_PROMPT),
                LLMMessage(role="user", content=query),
            ],
            temperature=0.0,
            max_tokens=256,
        )
        names = self._parse_names(resp.content)
        # 验证命中 GraphStore（越权实体被 graph 过滤不可见）
        valid: list[str] = []
        for name in names:
            entity = await graph.get_entity(name, access=access)
            if entity is not None:
                valid.append(name)
        return valid

    @staticmethod
    def _parse_names(text: str) -> list[str]:
        """从 LLM 响应解析实体名列表（容错：非法 JSON 返空）。"""
        try:
            data = json.loads(text.strip())
            if isinstance(data, list):
                return [str(n) for n in data if n]
        except (json.JSONDecodeError, ValueError):
            pass
        return []
