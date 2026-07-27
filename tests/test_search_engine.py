"""Task 4 测试：DefaultSearchEngine 三模式端到端编排。"""

import json
import uuid

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.interfaces.community_store import CommunityRecord
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.interfaces.llm import LLMProvider, LLMResponse
from calliodesmo.interfaces.retriever import SearchMode
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.hash_embedding import HashEmbeddingProvider
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
from calliodesmo.retrieval.answer_synthesizer import AnswerSynthesizer
from calliodesmo.retrieval.global_search import GlobalSearchRetriever
from calliodesmo.retrieval.hybrid_retriever import HybridRetriever
from calliodesmo.retrieval.identity_reranker import IdentityReranker
from calliodesmo.retrieval.in_memory_sparse_index import InMemoryBM25Index
from calliodesmo.retrieval.local_search import LocalSearchRetriever
from calliodesmo.retrieval.search_engine import DefaultSearchEngine
from calliodesmo.retrieval.seed_extractor import SeedExtractor

USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _access(clearance=ClearanceLevel.INTERNAL, user_id=USER_ID):
    return AccessContext(
        user_id=user_id,
        username="analyst",
        clearance=clearance,
        permissions=frozenset({Permission.QUERY}),
        library_scopes=frozenset({LibraryScope.PERSONAL}),
    )


class _DualMockLLM(LLMProvider):
    """桩 LLM：种子抽取返回实体名列表，答案合成返回带标注答案。"""

    def __init__(self, entity_names, answer_text="基于上下文 [c1] 的回答。"):
        self._names = entity_names
        self._answer = answer_text

    async def complete(self, messages, *, temperature=0.2, max_tokens=None):
        system = next((m.content for m in messages if m.role == "system"), "")
        if "种子实体抽取" in system:
            return LLMResponse(
                content=json.dumps(self._names, ensure_ascii=False),
                model="test/mock",
                usage={},
            )
        else:
            return LLMResponse(
                content=self._answer,
                model="test/mock",
                usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            )


def _chunk(cid, content, owner=USER_ID, level=ClearanceLevel.INTERNAL):
    emb = HashEmbeddingProvider(dimension=64)
    vec = emb._embed_one(content)
    return ChunkRecord(
        chunk_id=cid,
        doc_id="d1",
        content=content,
        vector=vec,
        owner_id=owner,
        access_level=level,
        library_scope=LibraryScope.PERSONAL,
    )


async def _build_engine(
    clearance=ClearanceLevel.INTERNAL,
    user_id=USER_ID,
    entity_names=None,
    answer_text=None,
    add_secret=False,
):
    """构造完整的 DefaultSearchEngine（内存 stores + 桩 LLM）。"""
    names = entity_names or ["OpenAI"]
    answer = answer_text or "OpenAI 开发了 GPT-4 [c1]。"
    llm = _DualMockLLM(names, answer)

    # chunks
    chunks = [
        _chunk("c1", "OpenAI developed GPT-4, a large language model"),
        _chunk("c2", "Cooking recipes for dinner"),
    ]
    if add_secret:
        chunks.append(_chunk("c3", "Secret AI project", level=ClearanceLevel.SECRET))

    vs = InMemoryVectorStore()
    bm = InMemoryBM25Index()
    emb = HashEmbeddingProvider(dimension=64)
    await vs.upsert_chunks(chunks)
    await bm.index(chunks)

    # graph
    entities = [
        EntityRecord(
            name="OpenAI",
            type="org",
            description="AI company",
            source_chunk_ids=["c1"],
            owner_id=USER_ID,
        ),
    ]
    if add_secret:
        entities.append(
            EntityRecord(
                name="SecretOrg",
                type="org",
                description="secret",
                source_chunk_ids=["c3"],
                owner_id=USER_ID,
                access_level=ClearanceLevel.SECRET,
            )
        )
    relations = [
        RelationRecord(
            source="OpenAI",
            target="GPT-4",
            type="developed",
            description="developed",
            source_chunk_ids=["c1"],
            owner_id=USER_ID,
        ),
    ]
    graph = InMemoryGraphStore()
    await graph.upsert_graph(entities, relations)

    # communities
    communities = [
        CommunityRecord(
            community_id="cm1",
            level=0,
            title="AI",
            summary="AI research and models",
            member_entity_names=["OpenAI"],
            owner_id=USER_ID,
        ),
    ]
    comm_store = InMemoryCommunityStore()
    await comm_store.upsert_communities(communities)

    seed = SeedExtractor(llm)
    native = HybridRetriever(vector_store=vs, embedding_provider=emb, sparse_index=bm)
    local = LocalSearchRetriever(seed_extractor=seed, graph_store=graph, vector_store=vs, hops=1)
    glob = GlobalSearchRetriever(
        community_store=comm_store,
        graph_store=graph,
        vector_store=vs,
        embedding_provider=emb,
        top_communities=10,
    )
    synth = AnswerSynthesizer(llm)
    engine = DefaultSearchEngine(
        native_retriever=native,
        local_retriever=local,
        global_retriever=glob,
        reranker=IdentityReranker(),
        synthesizer=synth,
    )
    return engine


class TestDefaultSearchEngineNativeRAG:
    @pytest.mark.asyncio
    async def test_native_rag_mode(self):
        engine = await _build_engine()
        answer = await engine.query(
            "OpenAI GPT-4", mode=SearchMode.NATIVE_RAG, top_k=5, access=_access()
        )
        assert answer.mode == SearchMode.NATIVE_RAG
        assert len(answer.source_chunk_ids) >= 1
        assert "c1" in answer.source_chunk_ids
        assert len(answer.context_chunks) >= 1

    @pytest.mark.asyncio
    async def test_native_rag_clearance_filter(self):
        """低 clearance 用户跨模式检索不可见越权 chunk。"""
        engine = await _build_engine(add_secret=True)
        answer = await engine.query(
            "AI",
            mode=SearchMode.NATIVE_RAG,
            top_k=10,
            access=_access(clearance=ClearanceLevel.PUBLIC),
        )
        ids = set(answer.source_chunk_ids)
        assert "c3" not in ids


class TestDefaultSearchEngineLocal:
    @pytest.mark.asyncio
    async def test_local_mode(self):
        engine = await _build_engine(entity_names=["OpenAI"])
        answer = await engine.query("OpenAI", mode=SearchMode.LOCAL, top_k=5, access=_access())
        assert answer.mode == SearchMode.LOCAL
        assert "c1" in answer.source_chunk_ids

    @pytest.mark.asyncio
    async def test_local_clearance_filter(self):
        engine = await _build_engine(entity_names=["OpenAI", "SecretOrg"], add_secret=True)
        answer = await engine.query(
            "OpenAI",
            mode=SearchMode.LOCAL,
            top_k=10,
            access=_access(clearance=ClearanceLevel.PUBLIC),
        )
        ids = set(answer.source_chunk_ids)
        assert "c3" not in ids


class TestDefaultSearchEngineGlobal:
    @pytest.mark.asyncio
    async def test_global_mode(self):
        engine = await _build_engine()
        answer = await engine.query(
            "AI research", mode=SearchMode.GLOBAL, top_k=5, access=_access()
        )
        assert answer.mode == SearchMode.GLOBAL
        # 至少有答案返回
        assert answer.text != ""


class TestDefaultSearchEngineEndToEnd:
    @pytest.mark.asyncio
    async def test_three_modes_all_visible_filtered(self):
        """三模式全程 visible_to：低 clearance 用户跨模式均不可见越权 chunk。"""
        engine = await _build_engine(add_secret=True)
        for mode in SearchMode:
            answer = await engine.query(
                "AI",
                mode=mode,
                top_k=10,
                access=_access(clearance=ClearanceLevel.PUBLIC),
            )
            ids = set(answer.source_chunk_ids)
            assert "c3" not in ids, f"mode={mode} leaked secret chunk c3"
