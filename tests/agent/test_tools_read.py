"""P7 T7：第一批只读工具契约——输入映射 / 输出结构 / clearance-scope 过滤矩阵。

红线专项：``get_chunk`` 工具层自补 ``visible_to``（接口无 access 过滤的跨密级
泄漏通道）；越权与不存在同一语义（经注册表收统一消息）。
"""

import uuid

import pytest

from calliodesmo.agent.errors import tool_unavailable_error
from calliodesmo.agent.registry import DefaultToolRegistry
from calliodesmo.agent.tools.communities import ListCommunitiesTool
from calliodesmo.agent.tools.documents import GetChunkTool, ListDocumentsTool
from calliodesmo.agent.tools.entities import EntityProfileTool, ListEntitiesTool
from calliodesmo.agent.tools.graph import GraphNeighborsTool
from calliodesmo.agent.tools.search import SearchKnowledgeTool
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.interfaces.agent import ToolCall
from calliodesmo.interfaces.community_store import CommunityRecord
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.interfaces.llm import ToolSpec
from calliodesmo.interfaces.profile_card import ProfileCard
from calliodesmo.interfaces.retriever import Answer, SearchEngine, SearchMode
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
from calliodesmo.stores.profile_card_store import InMemoryProfileCardStore

OWNER = uuid.uuid4()
TEAM = uuid.uuid4()


def _ctx(clearance=ClearanceLevel.INTERNAL, perms=frozenset({Permission.QUERY})):
    return AccessContext(
        user_id=OWNER,
        username="u",
        clearance=clearance,
        permissions=perms,
        library_scopes=frozenset({LibraryScope.PERSONAL, LibraryScope.TEAM}),
        team_ids=frozenset({TEAM}),
    )


def _chunk(cid, level=ClearanceLevel.INTERNAL, content="OpenAI 开发了 GPT-4。"):
    return ChunkRecord(
        chunk_id=cid,
        doc_id=f"doc-{cid}",
        content=content,
        vector=[0.0],
        access_level=level,
        library_scope=LibraryScope.TEAM,
        owner_id=OWNER,
        team_id=TEAM,
    )


def _entity(name, level=ClearanceLevel.INTERNAL):
    return EntityRecord(
        name=name,
        type="organization",
        description=f"{name} 描述",
        access_level=level,
        library_scope=LibraryScope.TEAM,
        owner_id=OWNER,
        team_id=TEAM,
    )


class _FakeEngine(SearchEngine):
    def __init__(self):
        self.seen: list = []

    async def query(self, question, *, mode, top_k, access):
        self.seen.append((question, mode, top_k, access))
        return Answer(
            text="GPT-4 由 OpenAI 开发。",
            source_chunk_ids=["c1"],
            mode=mode,
            context_chunks=[{"chunk_id": "c1", "content": "OpenAI 开发了 GPT-4。"}],
        )


# ---- search_knowledge ----


@pytest.mark.parametrize("mode", list(SearchMode))
async def test_search_delegates_three_modes_and_access(mode):
    engine = _FakeEngine()
    tool = SearchKnowledgeTool(engine)
    access = _ctx()
    out = await tool.run({"question": "q", "mode": mode.value, "top_k": 4}, access=access)
    q, m, k, acc = engine.seen[0]
    assert (q, m, k) == ("q", mode, 4)
    assert acc is access  # access 全程传参
    assert "[c1]" in out  # 引注口径


async def test_search_bad_mode_raises():
    tool = SearchKnowledgeTool(_FakeEngine())
    with pytest.raises(ValueError):
        await tool.run({"question": "q", "mode": "nope"}, access=_ctx())


# ---- graph_neighbors / list_entities ----


async def test_graph_neighbors_hops1_vs_subgraph():
    store = InMemoryGraphStore()
    await store.upsert_graph(
        [_entity("OpenAI"), _entity("GPT-4")],
        [
            RelationRecord(
                source="OpenAI",
                target="GPT-4",
                type="developed",
                description="dev",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.TEAM,
                owner_id=OWNER,
                team_id=TEAM,
            )
        ],
    )
    tool = GraphNeighborsTool(store)
    access = _ctx()
    out1 = await tool.run({"name": "OpenAI", "hops": 1}, access=access)
    assert "GPT-4" in out1

    out2 = await tool.run({"name": "OpenAI", "hops": 2, "limit": 10}, access=access)
    assert "子图" in out2 and "OpenAI" in out2


async def test_list_entities_clearance_filter():
    store = InMemoryGraphStore()
    await store.upsert_graph(
        [_entity("pub", ClearanceLevel.PUBLIC), _entity("sec", ClearanceLevel.SECRET)], []
    )
    tool = ListEntitiesTool(store)
    out = await tool.run({}, access=_ctx(ClearanceLevel.INTERNAL))
    assert "pub" in out and "sec" not in out  # 越权不泄漏存在性（store 侧过滤）


# ---- entity_profile ----


async def test_entity_profile_missing_unified_semantics():
    store = InMemoryProfileCardStore()
    tool = EntityProfileTool(store)
    with pytest.raises(LookupError):
        await tool.run({"name": "ghost"}, access=_ctx())


async def test_entity_profile_hit():
    store = InMemoryProfileCardStore()
    await store.upsert(
        [
            ProfileCard(
                entity_name="OpenAI",
                entity_type="organization",
                aliases=[],
                role=None,
                organization=None,
                associates=[],
                timespan=None,
                description="AI 公司",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.TEAM,
                owner_id=OWNER,
                team_id=TEAM,
            )
        ]
    )
    out = await EntityProfileTool(store).run({"name": "OpenAI"}, access=_ctx())
    assert "OpenAI" in out


# ---- list_documents / get_chunk（红线）----


async def test_list_documents_aggregates_and_filters():
    store = InMemoryVectorStore()
    await store.upsert_chunks(
        [
            _chunk("a1", ClearanceLevel.PUBLIC),
            _chunk("a2", ClearanceLevel.PUBLIC),
            _chunk("s1", ClearanceLevel.SECRET),
        ]
    )
    out = await ListDocumentsTool(store).run({}, access=_ctx(ClearanceLevel.INTERNAL))
    assert "doc-a1" in out and "1 块" in out
    assert "doc-s1" not in out


async def test_get_chunk_visible_to_self_compensation_redline():
    """接口无 access 过滤——工具层逐条复核：INTERNAL 取 SECRET 块 = 不存在语义。"""
    store = InMemoryVectorStore()
    await store.upsert_chunks(
        [_chunk("pub", ClearanceLevel.PUBLIC), _chunk("sec", ClearanceLevel.SECRET)]
    )
    tool = GetChunkTool(store)

    # 可见路径：带引注渲染
    out = await tool.run({"chunk_ids": ["pub"]}, access=_ctx(ClearanceLevel.INTERNAL))
    assert "[pub]" in out

    # 红线路径：store 会回 SECRET 块，但工具层 visible_to 剔除 -> 与不存在同语义
    with pytest.raises(LookupError):
        await tool.run({"chunk_ids": ["sec"]}, access=_ctx(ClearanceLevel.INTERNAL))

    # 高密上下文可见
    out2 = await tool.run({"chunk_ids": ["sec"]}, access=_ctx(ClearanceLevel.SECRET))
    assert "[sec]" in out2

    # 不存在 id 同语义
    with pytest.raises(LookupError):
        await tool.run({"chunk_ids": ["ghost"]}, access=_ctx(ClearanceLevel.SECRET))


async def test_get_chunk_via_registry_unified_message():
    """注册表收口：越权 get_chunk 与不存在工具同一错误消息。"""
    store = InMemoryVectorStore()
    await store.upsert_chunks([_chunk("sec", ClearanceLevel.SECRET)])
    reg = DefaultToolRegistry([GetChunkTool(store)])
    access = _ctx(ClearanceLevel.INTERNAL)

    denied = await reg.dispatch(
        ToolCall(id="c1", name="get_chunk", arguments={"chunk_ids": ["sec"]}), access=access
    )
    missing = await reg.dispatch(ToolCall(id="c2", name="ghost_tool", arguments={}), access=access)
    assert denied.error == missing.error == tool_unavailable_error()


# ---- list_communities ----


async def test_list_communities_clearance_filter():
    store = InMemoryCommunityStore()

    def _comm(cid, level):
        return CommunityRecord(
            community_id=cid,
            level=0,
            title=cid,
            summary="摘要",
            access_level=level,
            library_scope=LibraryScope.TEAM,
            owner_id=OWNER,
            team_id=TEAM,
        )

    await store.upsert_communities(
        [_comm("pub-c", ClearanceLevel.PUBLIC), _comm("conf-c", ClearanceLevel.CONFIDENTIAL)]
    )
    out = await ListCommunitiesTool(store).run({}, access=_ctx(ClearanceLevel.INTERNAL))
    assert "pub-c" in out and "conf-c" not in out


# ---- 工具契约形态（spec / 权限）----


def test_tool_specs_and_permissions():
    tools = [
        SearchKnowledgeTool(_FakeEngine()),
        GraphNeighborsTool(InMemoryGraphStore()),
        ListEntitiesTool(InMemoryGraphStore()),
        EntityProfileTool(InMemoryProfileCardStore()),
        ListDocumentsTool(InMemoryVectorStore()),
        ListCommunitiesTool(InMemoryCommunityStore()),
        GetChunkTool(InMemoryVectorStore()),
    ]
    for t in tools:
        assert isinstance(t.spec, ToolSpec)
        assert t.required_permission == Permission.QUERY
        assert t.spec.parameters["type"] == "object"
