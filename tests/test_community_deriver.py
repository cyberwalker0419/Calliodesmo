"""Task 5：文档社区自动派生（level=1）测试。"""

import uuid

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.ecl.cognify import GraphNode
from calliodesmo.ecl.community_deriver import DocumentCommunityDeriver
from calliodesmo.interfaces.chunker import Chunk
from calliodesmo.interfaces.llm import LLMProvider, LLMResponse
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore


class _StubLLM(LLMProvider):
    def __init__(self, content: str) -> None:
        self._content = content

    async def complete(self, messages, *, temperature=0.2, max_tokens=None) -> LLMResponse:
        return LLMResponse(content=self._content, model="stub")


def _ctx(user) -> AccessContext:
    return AccessContext(user_id=user, username="u", clearance=ClearanceLevel.INTERNAL)


def _graph():
    return {
        "nodes": {
            "openai": GraphNode(
                name="openai",
                type="organization",
                description="AI 公司",
                source_chunk_ids=["doc-a#0", "doc-a#1"],
            ),
            "gpt-4": GraphNode(
                name="gpt-4",
                type="model",
                description="大模型",
                source_chunk_ids=["doc-a#0", "doc-b#0"],
            ),
            "sam": GraphNode(
                name="sam", type="person", description="CEO", source_chunk_ids=["doc-b#0"]
            ),
        },
        "edges": [],
    }


async def test_derive_aggregates_by_doc_and_summarizes():
    owner = uuid.uuid4()
    chunks = [
        Chunk(
            chunk_id="doc-a#0",
            doc_id="doc-a",
            content="x",
            ordinal=0,
            library_scope=LibraryScope.PERSONAL,
            owner_id=owner,
        ),
        Chunk(
            chunk_id="doc-a#1",
            doc_id="doc-a",
            content="y",
            ordinal=1,
            library_scope=LibraryScope.PERSONAL,
            owner_id=owner,
        ),
        Chunk(
            chunk_id="doc-b#0",
            doc_id="doc-b",
            content="z",
            ordinal=0,
            library_scope=LibraryScope.PERSONAL,
            owner_id=owner,
        ),
    ]
    llm = _StubLLM('{"title":"文档概览","summary":"该文档涉及关键实体。"}')
    deriver = DocumentCommunityDeriver(llm)
    comms = await deriver.derive(chunks, _graph(), access=_ctx(owner))
    assert len(comms) == 2  # doc-a 与 doc-b
    by_id = {c.community_id: c for c in comms}
    assert by_id["doc-doc-a"].level == 1
    assert by_id["doc-doc-a"].title == "文档概览"
    assert "关键实体" in by_id["doc-doc-a"].summary
    # doc-a 关联 openai 与 gpt-4
    assert set(by_id["doc-doc-a"].member_entity_names) == {"openai", "gpt-4"}
    # doc-b 关联 gpt-4 与 sam
    assert set(by_id["doc-doc-b"].member_entity_names) == {"gpt-4", "sam"}
    # access 字段从 chunk 继承
    assert by_id["doc-doc-a"].owner_id == owner


async def test_derive_writes_to_community_store():
    owner = uuid.uuid4()
    store = InMemoryCommunityStore()
    chunks = [
        Chunk(
            chunk_id="doc-a#0",
            doc_id="doc-a",
            content="x",
            ordinal=0,
            library_scope=LibraryScope.PERSONAL,
            owner_id=owner,
        )
    ]
    graph_a = {
        "nodes": {
            "openai": GraphNode(
                name="openai",
                type="organization",
                description="AI 公司",
                source_chunk_ids=["doc-a#0"],
            ),
        },
        "edges": [],
    }
    llm = _StubLLM('{"title":"T","summary":"S"}')
    deriver = DocumentCommunityDeriver(llm, community_store=store)
    await deriver.derive(chunks, graph_a, access=_ctx(owner))
    listed = await store.list_communities(access=_ctx(owner))
    assert len(listed) == 1
    assert listed[0].level == 1
    assert listed[0].community_id == "doc-doc-a"


async def test_incremental_does_not_touch_existing():
    owner = uuid.uuid4()
    store = InMemoryCommunityStore()
    llm = _StubLLM('{"title":"T","summary":"S"}')
    deriver = DocumentCommunityDeriver(llm, community_store=store)

    # 第一批：doc-a
    chunks_a = [
        Chunk(
            chunk_id="doc-a#0",
            doc_id="doc-a",
            content="x",
            ordinal=0,
            library_scope=LibraryScope.PERSONAL,
            owner_id=owner,
        )
    ]
    await deriver.derive(chunks_a, _graph(), access=_ctx(owner))
    # 第二批：doc-b（不同文档）
    chunks_b = [
        Chunk(
            chunk_id="doc-b#0",
            doc_id="doc-b",
            content="z",
            ordinal=0,
            library_scope=LibraryScope.PERSONAL,
            owner_id=owner,
        )
    ]
    await deriver.derive(chunks_b, _graph(), access=_ctx(owner))

    listed = await store.list_communities(access=_ctx(owner))
    ids = {c.community_id for c in listed}
    assert ids == {"doc-doc-a", "doc-doc-b"}  # doc-a 仍在，未被动
