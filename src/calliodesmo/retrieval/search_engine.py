"""DefaultSearchEngine：按 SearchMode 编排 retriever + rerank + synthesizer。

native_rag -> HybridRetriever -> rerank -> AnswerSynthesizer
local -> LocalSearchRetriever -> rerank -> AnswerSynthesizer
global -> GlobalSearchRetriever -> 不 rerank -> AnswerSynthesizer（社区摘要不进重排）
"""

from __future__ import annotations

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.retriever import Answer, Reranker, SearchEngine, SearchMode
from calliodesmo.retrieval.answer_synthesizer import AnswerSynthesizer
from calliodesmo.retrieval.global_search import GlobalSearchRetriever
from calliodesmo.retrieval.hybrid_retriever import HybridRetriever
from calliodesmo.retrieval.identity_reranker import IdentityReranker
from calliodesmo.retrieval.local_search import LocalSearchRetriever


class DefaultSearchEngine(SearchEngine):
    """默认搜索引擎：按 mode 分派 retriever，rerank（仅 Local/Native），合成答案。"""

    def __init__(
        self,
        *,
        native_retriever: HybridRetriever,
        local_retriever: LocalSearchRetriever,
        global_retriever: GlobalSearchRetriever,
        reranker: Reranker | None = None,
        synthesizer: AnswerSynthesizer | None = None,
    ) -> None:
        self._native_retriever = native_retriever
        self._local_retriever = local_retriever
        self._global_retriever = global_retriever
        self._reranker = reranker or IdentityReranker()
        self._synthesizer = synthesizer or AnswerSynthesizer(self._get_llm())

    def _get_llm(self):
        # 延迟导入避免循环依赖；synthesizer 需 LLM，由调用方注入或默认桩
        from calliodesmo.providers.stub_llm import StubLLMProvider

        return StubLLMProvider()

    async def query(
        self, question: str, *, mode: SearchMode, top_k: int, access: AccessContext
    ) -> Answer:
        if mode == SearchMode.NATIVE_RAG:
            candidates = await self._native_retriever.retrieve(
                question, top_k=top_k, mode=mode, access=access
            )
            candidates = await self._reranker.rerank(question, candidates, top_k=top_k)
        elif mode == SearchMode.LOCAL:
            candidates = await self._local_retriever.retrieve(
                question, top_k=top_k, mode=mode, access=access
            )
            candidates = await self._reranker.rerank(question, candidates, top_k=top_k)
        elif mode == SearchMode.GLOBAL:
            # Global 模式：社区摘要不进 rerank
            candidates = await self._global_retriever.retrieve(
                question, top_k=top_k, mode=mode, access=access
            )
        else:
            raise ValueError(f"未知检索模式：{mode}")

        return await self._synthesizer.synthesize(question, candidates, mode=mode, access=access)
