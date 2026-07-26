"""Task 3：建图 / 实体消解 / 社区检测 / 社区摘要 测试。"""

import sys

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.ecl.cognify import (
    CognifyPipeline,
    ConnectedComponentsDetector,
    EntityRelationGraphBuilder,
    LLMAliasResolver,
    LLMCommunitySummarizer,
    NameEntityResolver,
    NetworkxCommunityDetector,
)
from calliodesmo.interfaces.extractor import Entity, ExtractionResult, Relation
from calliodesmo.interfaces.llm import LLMProvider, LLMResponse


def _ctx() -> AccessContext:
    return AccessContext(
        user_id=__import__("uuid").uuid4(),
        username="u",
        clearance=ClearanceLevel.INTERNAL,
    )


def _result() -> ExtractionResult:
    return ExtractionResult(
        entities=[
            Entity(
                name="OpenAI", type="organization", description="AI 公司", source_chunk_ids=["d#0"]
            ),
            Entity(
                name="GPT-4", type="model", description="大模型", source_chunk_ids=["d#0", "d#1"]
            ),
            Entity(name="Sam Altman", type="person", description="CEO", source_chunk_ids=["d#1"]),
        ],
        relations=[
            Relation(
                source="OpenAI",
                target="GPT-4",
                type="developed",
                description="",
                source_chunk_ids=["d#0"],
            ),
            Relation(
                source="OpenAI",
                target="OpenAI",
                type="self",
                description="",
                source_chunk_ids=["d#0"],
            ),  # 自环
            Relation(
                source="OpenAI",
                target="GPT-4",
                type="developed",
                description="",
                source_chunk_ids=["d#1"],
            ),  # 重复
            Relation(
                source="Sam Altman",
                target="OpenAI",
                type="leads",
                description="",
                source_chunk_ids=["d#1"],
            ),
        ],
    )


# ---- Step 1: 建图 ----


def test_graph_builder_nodes_and_edges():
    graph = EntityRelationGraphBuilder().build(_result())
    assert set(graph["nodes"]) == {"OpenAI", "GPT-4", "Sam Altman"}
    edges = [(e.source, e.target, e.type) for e in graph["edges"]]
    assert ("OpenAI", "OpenAI", "self") not in edges  # 自环过滤
    assert edges.count(("OpenAI", "GPT-4", "developed")) == 1  # 重复边过滤
    assert ("Sam Altman", "OpenAI", "leads") in edges


# ---- Step 2: 实体消解 ----


def test_name_resolver_merges_duplicates():
    result = ExtractionResult(
        entities=[
            Entity(
                name="OpenAI",
                type="organization",
                description="AI 公司",
                source_chunk_ids=["d#0"],
                template_conforming=True,
            ),
            Entity(
                name="openai",
                type="organization",
                description="位于旧金山",
                source_chunk_ids=["d#1"],
                template_conforming=False,
            ),
            Entity(name="GPT-4", type="model", description="大模型", source_chunk_ids=["d#0"]),
        ],
        relations=[],
    )
    graph = EntityRelationGraphBuilder().build(result)
    resolved = NameEntityResolver().resolve(graph)
    assert len(resolved["nodes"]) == 2  # OpenAI/openai 合并
    node = resolved["nodes"]["openai"]
    assert set(node.source_chunk_ids) == {"d#0", "d#1"}  # 跨 chunk 合并
    assert "AI 公司" in node.description and "位于旧金山" in node.description  # 描述汇总
    assert node.template_conforming is True  # 并集


def test_name_resolver_alias_table():
    result = ExtractionResult(
        entities=[
            Entity(
                name="OpenAI Inc.",
                type="organization",
                description="母公司",
                source_chunk_ids=["d#0"],
            ),
            Entity(
                name="OpenAI", type="organization", description="子公司", source_chunk_ids=["d#1"]
            ),
        ],
        relations=[],
    )
    graph = EntityRelationGraphBuilder().build(result)
    resolver = NameEntityResolver(aliases={"OpenAI": ["OpenAI Inc."]})
    resolved = resolver.resolve(graph)
    assert len(resolved["nodes"]) == 1  # 别名合并


# ---- Step 3: LLMAliasResolver ----


class _StubLLM(LLMProvider):
    def __init__(self, content: str) -> None:
        self._content = content

    async def complete(self, messages, *, temperature=0.2, max_tokens=None) -> LLMResponse:
        return LLMResponse(content=self._content, model="stub")


async def test_llm_alias_resolver_merges_via_llm():
    result = ExtractionResult(
        entities=[
            Entity(name="OpenAI", type="organization", description="a", source_chunk_ids=["d#0"]),
            Entity(
                name="OpenAI Inc.", type="organization", description="b", source_chunk_ids=["d#1"]
            ),
        ],
        relations=[],
    )
    graph = EntityRelationGraphBuilder().build(result)
    llm = _StubLLM('{"groups":[["OpenAI","OpenAI Inc."]]}')
    resolver = LLMAliasResolver(llm)
    resolved = await resolver.resolve_async(graph)
    assert len(resolved["nodes"]) == 1


async def test_llm_alias_resolver_fallback_on_bad_json():
    graph = EntityRelationGraphBuilder().build(
        ExtractionResult(
            entities=[
                Entity(name="OpenAI", type="org", description="a", source_chunk_ids=["d#0"]),
                Entity(name="openai", type="org", description="b", source_chunk_ids=["d#1"]),
            ],
            relations=[],
        )
    )
    resolver = LLMAliasResolver(_StubLLM("not json"))
    resolved = await resolver.resolve_async(graph)
    assert len(resolved["nodes"]) == 1  # 回退名归一化仍合并


# ---- Step 4: 连通分量社区检测 ----


def test_connected_components_deterministic():
    graph = EntityRelationGraphBuilder().build(_result())
    det = ConnectedComponentsDetector()
    comms1 = det.detect(graph, access=_ctx())
    comms2 = det.detect(graph, access=_ctx())
    assert [c.member_entity_names for c in comms1] == [c.member_entity_names for c in comms2]
    # 三个实体连通（OpenAI-GPT4, SamAltman-OpenAI）-> 一个社区
    assert len(comms1) == 1
    assert set(comms1[0].member_entity_names) == {"OpenAI", "GPT-4", "Sam Altman"}
    assert comms1[0].level == 0


def test_connected_components_isolated_nodes():
    result = ExtractionResult(
        entities=[
            Entity(name="A", type=None, description="", source_chunk_ids=["d#0"]),
            Entity(name="B", type=None, description="", source_chunk_ids=["d#0"]),
            Entity(name="C", type=None, description="", source_chunk_ids=["d#0"]),
        ],
        relations=[
            Relation(source="A", target="B", type="r", description="", source_chunk_ids=["d#0"])
        ],
    )
    graph = EntityRelationGraphBuilder().build(result)
    comms = ConnectedComponentsDetector().detect(graph, access=_ctx())
    assert len(comms) == 2  # {A,B} 与 {C}


def test_community_carries_access_fields():
    import uuid

    uid = uuid.uuid4()
    ctx = AccessContext(user_id=uid, username="u", clearance=ClearanceLevel.INTERNAL)
    graph = EntityRelationGraphBuilder().build(_result())
    comms = ConnectedComponentsDetector().detect(graph, access=ctx)
    c = comms[0]
    assert c.owner_id == uid
    assert c.library_scope == LibraryScope.PERSONAL
    assert c.access_level == ClearanceLevel.INTERNAL


# ---- Step 5: networkx 缺依赖友好报错 ----


def test_networkx_missing_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "networkx", None)
    graph = EntityRelationGraphBuilder().build(_result())
    with pytest.raises(RuntimeError, match="graph-analytics"):
        NetworkxCommunityDetector().detect(graph, access=_ctx())


# ---- Step 6: 社区摘要 ----


async def test_community_summarizer():
    graph = EntityRelationGraphBuilder().build(_result())
    comms = ConnectedComponentsDetector().detect(graph, access=_ctx())
    llm = _StubLLM('{"title":"AI 公司生态","summary":"OpenAI、GPT-4 与 Sam Altman 构成核心生态。"}')
    summarizer = LLMCommunitySummarizer(llm)
    comms = await summarizer.summarize(comms, graph)
    assert comms[0].title == "AI 公司生态"
    assert "核心生态" in comms[0].summary


# ---- Step 7: 串联端到端 ----


async def test_cognify_pipeline_end_to_end():
    llm = _StubLLM('{"title":"生态","summary":"概览。"}')
    pipeline = CognifyPipeline(summarizer=LLMCommunitySummarizer(llm))
    comms, graph = await pipeline.run(_result(), access=_ctx())
    assert len(comms) >= 1
    assert all(c.summary for c in comms)
    # 消解后图节点数 <= 原始
    assert len(graph["nodes"]) <= 3
