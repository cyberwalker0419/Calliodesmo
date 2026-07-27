"""Task 4 测试：LocalSearchRetriever 图邻居 K 跳检索。"""

import uuid

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.interfaces.llm import LLMProvider, LLMResponse
from calliodesmo.interfaces.retriever import SearchMode
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
from calliodesmo.retrieval.local_search import LocalSearchRetriever
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


class _MockLLM(LLMProvider):
    """返回固定实体名列表的桩 LLM。"""

    def __init__(self, names):
        self._names = names

    async def complete(self, messages, *, temperature=0.2, max_tokens=None):
        import json

        return LLMResponse(
            content=json.dumps(self._names, ensure_ascii=False),
            model="test/mock",
            usage={},
        )


def _entity(name, chunk_ids, owner=USER_ID, level=ClearanceLevel.INTERNAL):
    return EntityRecord(
        name=name,
        type="org",
        description=f"desc {name}",
        source_chunk_ids=chunk_ids,
        owner_id=owner,
        access_level=level,
    )


def _relation(src, tgt, chunk_ids, owner=USER_ID, level=ClearanceLevel.INTERNAL):
    return RelationRecord(
        source=src,
        target=tgt,
        type="related",
        description=f"{src}->{tgt}",
        source_chunk_ids=chunk_ids,
        owner_id=owner,
        access_level=level,
    )


def _chunk(cid, content="chunk content", owner=USER_ID, level=ClearanceLevel.INTERNAL):
    return ChunkRecord(
        chunk_id=cid,
        doc_id="d1",
        content=content,
        vector=[0.1],
        owner_id=owner,
        access_level=level,
        library_scope=LibraryScope.PERSONAL,
    )


async def _setup(names, entities, relations, chunks):
    graph = InMemoryGraphStore()
    vs = InMemoryVectorStore()
    await graph.upsert_graph(entities, relations)
    await vs.upsert_chunks(chunks)
    llm = _MockLLM(names)
    seed = SeedExtractor(llm)
    retriever = LocalSearchRetriever(
        seed_extractor=seed, graph_store=graph, vector_store=vs, hops=1
    )
    return retriever


class TestSeedExtractor:
    @pytest.mark.asyncio
    async def test_extract_validates_against_graph(self):
        """命中 GraphStore 的保留，未命中过滤。"""
        entities = [
            _entity("OpenAI", ["c1"], level=ClearanceLevel.PUBLIC),
            _entity("GPT-4", ["c2"]),
        ]
        graph = InMemoryGraphStore()
        await graph.upsert_graph(entities, [])
        llm = _MockLLM(["OpenAI", "Unknown", "GPT-4"])
        seed = SeedExtractor(llm)
        names = await seed.extract("test", access=_access(), graph=graph)
        assert "OpenAI" in names
        assert "GPT-4" in names
        assert "Unknown" not in names

    @pytest.mark.asyncio
    async def test_extract_empty_response(self):
        graph = InMemoryGraphStore()
        llm = _MockLLM([])
        seed = SeedExtractor(llm)
        names = await seed.extract("test", access=_access(), graph=graph)
        assert names == []


class TestLocalSearchRetriever:
    @pytest.mark.asyncio
    async def test_k_hop_expansion(self):
        """从种子出发 K 跳扩展，收集关联 chunk。"""
        entities = [
            _entity("OpenAI", ["c1"], level=ClearanceLevel.PUBLIC),
            _entity("GPT-4", ["c2"]),
            _entity("Microsoft", ["c3"]),
        ]
        relations = [
            _relation("OpenAI", "GPT-4", ["c1", "c2"]),
            _relation("Microsoft", "OpenAI", ["c3"]),
        ]
        chunks = [
            _chunk("c1", "OpenAI content"),
            _chunk("c2", "GPT-4 content"),
            _chunk("c3", "MS content"),
        ]
        retriever = await _setup(["OpenAI"], entities, relations, chunks)
        results = await retriever.retrieve(
            "OpenAI", top_k=10, mode=SearchMode.LOCAL, access=_access()
        )
        ids = {c.chunk_id for c in results}
        # c1 (OpenAI), c2 (GPT-4 via neighbor), c3 (Microsoft via neighbor)
        assert "c1" in ids
        assert "c2" in ids
        assert "c3" in ids
        assert all(c.source == "graph" for c in results)

    @pytest.mark.asyncio
    async def test_no_seeds_returns_empty(self):
        entities = [_entity("OpenAI", ["c1"])]
        chunks = [_chunk("c1")]
        retriever = await _setup(["NonExistent"], entities, [], chunks)
        results = await retriever.retrieve(
            "test", top_k=10, mode=SearchMode.LOCAL, access=_access()
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_clearance_filter(self):
        """越权邻居被 GraphStore 过滤不可见。"""
        entities = [
            _entity("OpenAI", ["c1"], level=ClearanceLevel.PUBLIC),
            _entity("Secret", ["c2"], level=ClearanceLevel.SECRET),
        ]
        relations = [_relation("OpenAI", "Secret", ["c1"])]
        chunks = [
            _chunk("c1", "public", level=ClearanceLevel.PUBLIC),
            _chunk("c2", "secret", level=ClearanceLevel.SECRET),
        ]
        retriever = await _setup(["OpenAI"], entities, relations, chunks)
        results = await retriever.retrieve(
            "OpenAI",
            top_k=10,
            mode=SearchMode.LOCAL,
            access=_access(clearance=ClearanceLevel.PUBLIC),
        )
        ids = {c.chunk_id for c in results}
        assert "c1" in ids
        assert "c2" not in ids

    @pytest.mark.asyncio
    async def test_scope_filter(self):
        """非 owner 不可见 personal 库实体。"""
        entities = [
            _entity("Mine", ["c1"], owner=USER_ID),
            _entity("Other", ["c2"], owner=OTHER_ID),
        ]
        relations = [_relation("Mine", "Other", ["c1"])]
        chunks = [_chunk("c1", "mine"), _chunk("c2", "other", owner=OTHER_ID)]
        retriever = await _setup(["Mine"], entities, relations, chunks)
        results = await retriever.retrieve(
            "Mine", top_k=10, mode=SearchMode.LOCAL, access=_access(user_id=USER_ID)
        )
        ids = {c.chunk_id for c in results}
        assert "c1" in ids
        assert "c2" not in ids
