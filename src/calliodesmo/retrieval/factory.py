"""SearchEngine 默认装配工厂：在共享 stores 之上构建三模式引擎。

与 ECL ``build_default_indexing_engine`` 的 LLM/嵌入路由一致：
- ``test/*`` 模型 -> StubLLMProvider（离线零网络）
- 其余 -> LiteLLMProvider（本地 localhost / ollama/ / lm-studio/ 豁免 key 校验）
嵌入：hash（离线/测试）| bge-m3（本地 extra）| remote（OpenAI 兼容远端）。
"""

from __future__ import annotations

from calliodesmo.config import Settings
from calliodesmo.interfaces.community_store import CommunityStore
from calliodesmo.interfaces.embedding import EmbeddingProvider
from calliodesmo.interfaces.graph_store import GraphStore
from calliodesmo.interfaces.llm import LLMProvider
from calliodesmo.interfaces.retriever import Reranker, SparseIndex
from calliodesmo.interfaces.vector_store import VectorStore
from calliodesmo.retrieval.answer_synthesizer import AnswerSynthesizer
from calliodesmo.retrieval.global_search import GlobalSearchRetriever
from calliodesmo.retrieval.hybrid_retriever import HybridRetriever
from calliodesmo.retrieval.identity_reranker import IdentityReranker
from calliodesmo.retrieval.local_search import LocalSearchRetriever
from calliodesmo.retrieval.search_engine import DefaultSearchEngine
from calliodesmo.retrieval.seed_extractor import SeedExtractor


def build_llm_provider(settings: Settings) -> LLMProvider:
    """按配置路由 LLM 后端（与 ECL 引擎同一套豁免规则）。"""
    model = settings.llm_model
    if model.startswith("test/"):
        from calliodesmo.providers.stub_llm import StubLLMProvider

        return StubLLMProvider(model=model)

    from calliodesmo.providers.litellm_provider import LiteLLMProvider

    extra_body = (
        {"chat_template_kwargs": {"enable_thinking": False}}
        if getattr(settings, "llm_disable_thinking", True)
        else None
    )
    local_hosts = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
    is_local = bool(settings.llm_api_base) and any(
        h in (settings.llm_api_base or "") for h in local_hosts
    )
    exempt = model.startswith("ollama/") or model.startswith("lm-studio/") or is_local
    if not exempt and not settings.llm_api_key:
        raise RuntimeError(
            "LLM 缺 API key：设置环境变量 CALLIODESMO_LLM_API_KEY"
            "（本地服务可设 CALLIODESMO_LLM_API_BASE 指向 http://localhost:... 自动豁免）"
        )
    return LiteLLMProvider(
        model=model,
        api_key=settings.llm_api_key,
        api_base=settings.llm_api_base,
        extra_body=extra_body,
    )


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """嵌入 provider 路由：hash | bge-m3 | remote。"""
    name = (settings.embedding_provider or "hash").lower()
    if name == "remote":
        from calliodesmo.providers.remote_embedding import RemoteEmbeddingProvider

        if not settings.embedding_api_base:
            raise RuntimeError(
                "remote 嵌入需设 CALLIODESMO_EMBEDDING_API_BASE（如 http://host:8082/v1）"
            )
        return RemoteEmbeddingProvider(
            api_base=settings.embedding_api_base,
            model=settings.embedding_model,
            dimension=settings.embedding_dimension,
        )
    if name == "bge-m3":
        from calliodesmo.providers.bge_m3 import BgeM3EmbeddingProvider

        return BgeM3EmbeddingProvider(
            model_name=settings.embedding_model, dimension=settings.embedding_dimension
        )
    from calliodesmo.providers.hash_embedding import HashEmbeddingProvider

    return HashEmbeddingProvider(dimension=settings.embedding_dimension or 64)


def build_reranker(settings: Settings) -> Reranker:
    """重排器路由：none（保序降级）| local（FlagEmbedding extra）| remote（HTTP rerank 服务）。"""
    name = (settings.reranker_provider or "none").lower()
    if name == "remote":
        if not settings.reranker_api_base:
            raise RuntimeError(
                "remote 重排需设 CALLIODESMO_RERANKER_API_BASE"
                "（如 http://rerank-host:8083，llama.cpp llama-server --rerank）"
            )
        from calliodesmo.retrieval.http_reranker import HttpReranker

        return HttpReranker(
            api_base=settings.reranker_api_base,
            model=settings.reranker_model,
            api_key=settings.reranker_api_key,
        )
    if name == "local":
        from calliodesmo.retrieval.bge_reranker import BgeReranker

        return BgeReranker(model=settings.reranker_model)
    return IdentityReranker()


def build_default_search_engine(
    settings: Settings,
    *,
    vector_store: VectorStore,
    graph_store: GraphStore,
    community_store: CommunityStore,
    sparse_index: SparseIndex,
    reranker=None,
) -> DefaultSearchEngine:
    """在共享 stores 之上装配默认搜索引擎（ingest/query/browse 同进程共享数据）。"""
    llm = build_llm_provider(settings)
    embedding = build_embedding_provider(settings)
    seed = SeedExtractor(llm)
    native = HybridRetriever(
        vector_store=vector_store, embedding_provider=embedding, sparse_index=sparse_index
    )
    local = LocalSearchRetriever(
        seed_extractor=seed,
        graph_store=graph_store,
        vector_store=vector_store,
        hops=settings.local_search_hops,
    )
    glob = GlobalSearchRetriever(
        community_store=community_store,
        graph_store=graph_store,
        vector_store=vector_store,
        embedding_provider=embedding,
        top_communities=settings.global_top_communities,
    )
    return DefaultSearchEngine(
        native_retriever=native,
        local_retriever=local,
        global_retriever=glob,
        reranker=reranker or IdentityReranker(),
        synthesizer=AnswerSynthesizer(llm),
    )
