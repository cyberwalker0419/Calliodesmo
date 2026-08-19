"""查询改写默认实现：MultiQuery 多视角 + 配置开关（P5 Task 1）。

- ``MultiQueryGenerator``：LLM 生成 num_queries 个视角子查询（StubLLM 确定性 JSON 数组）
- ``RewriteRouter``：配置开关，关闭时原样返回单查询（向后兼容默认关闭）
"""

from __future__ import annotations

import json

from calliodesmo.interfaces.llm import LLMMessage, LLMProvider
from calliodesmo.interfaces.rewriter import QueryRewriter


class MultiQueryGenerator(QueryRewriter):
    """LLM 生成 num_queries 个视角子查询（JSON 数组）。"""

    def __init__(self, llm: LLMProvider, num_queries: int = 3) -> None:
        self._llm = llm
        self._num_queries = num_queries

    async def generate(self, query: str) -> list[str]:
        prompt = (
            f"针对问题生成 {self._num_queries} 个不同视角的子查询，"
            "覆盖可能的不同措辞/角度。仅返回 JSON 字符串数组，不加解释。\n问题：" + query
        )
        resp = await self._llm.complete(
            [
                LLMMessage(role="system", content="你是查询改写引擎。"),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.3,
            max_tokens=256,
        )
        return self._parse_queries(resp.content)

    @staticmethod
    def _parse_queries(text: str) -> list[str]:
        """从 LLM 响应解析子查询列表（容错：非法 JSON 返空）。"""
        try:
            data = json.loads(text.strip())
            if isinstance(data, list):
                return [str(q) for q in data if q]
        except (json.JSONDecodeError, ValueError):
            pass
        return []


class RewriteRouter:
    """查询改写入口：enabled=False 时原样返回单查询（配置开关，默认关闭）。"""

    def __init__(self, rewriter: QueryRewriter, enabled: bool = False) -> None:
        self._rewriter = rewriter
        self._enabled = enabled

    async def rewrite(self, query: str) -> list[str]:
        if not self._enabled:
            return [query]
        generated = await self._rewriter.generate(query)
        # 空生成回退原查询：LLM 偶发吐不出可解析子查询时降级为单查询，
        # 避免 MultiQueryRetriever 空召回（P5 Task 2 健壮性收尾）
        return generated if generated else [query]
