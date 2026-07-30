"""P4.5 Task 3 Step 1：增量索引——content_hash 指纹短路。

硬指标：① 二次 ingest 同文档 call_count==0；② 新增 1 篇到 N 篇库 call_count 仅 = 1 篇量。
"""

import uuid

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel
from calliodesmo.ecl.chunker import TextChunker
from calliodesmo.ecl.cognify import CognifyPipeline
from calliodesmo.ecl.community_deriver import DocumentCommunityDeriver
from calliodesmo.ecl.engine import ECLIndexingEngine
from calliodesmo.ecl.extraction_template import ExtractionTemplateRegistry
from calliodesmo.ecl.extractor import LLMExtractor
from calliodesmo.ecl.load import LoadService
from calliodesmo.interfaces.llm import LLMProvider, LLMResponse
from calliodesmo.providers.hash_embedding import HashEmbeddingProvider
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
from calliodesmo.providers.registry import default_registry

_EXT_JSON = (
    '{"entities":[{"name":"OpenAI","type":"organization","description":""},'
    '{"name":"GPT-4","type":"model","description":""}],'
    '"relations":[{"source":"OpenAI","target":"GPT-4","type":"developed","description":""}],'
    '"claims":[],"covariates":[]}'
)


class _CountingExt(LLMProvider):
    """桩抽取器：每次 complete 计数 +1，返回固定 JSON。"""

    def __init__(self) -> None:
        self.call_count = 0

    async def complete(self, messages, *, temperature=0.2, max_tokens=None) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(content=_EXT_JSON, model="stub")


class _Sum(LLMProvider):
    async def complete(self, messages, *, temperature=0.2, max_tokens=None) -> LLMResponse:
        return LLMResponse(content='{"title":"T","summary":"S"}', model="stub")


def _build_engine() -> tuple[ECLIndexingEngine, _CountingExt]:
    ext = _CountingExt()
    cs = InMemoryCommunityStore()
    vec = InMemoryVectorStore()
    engine = ECLIndexingEngine(
        loader=default_registry(),
        chunker=TextChunker(),
        extractor=LLMExtractor(ext, ExtractionTemplateRegistry()),
        cognify=CognifyPipeline(summarizer=None),
        load_service=LoadService(vec, InMemoryGraphStore(), cs, HashEmbeddingProvider(32)),
        deriver=DocumentCommunityDeriver(_Sum(), cs),
        incremental_indexing=True,
    )
    return engine, ext


def _ctx() -> AccessContext:
    return AccessContext(
        user_id=uuid.uuid4(),
        username="u",
        clearance=ClearanceLevel.SECRET,
        permissions=frozenset(),
        project_ids=frozenset(),
        team_ids=frozenset(),
    )


async def test_reingest_same_doc_zero_calls(tmp_path):
    """① 二次 ingest 同文档 -> 抽取 call_count==0。"""
    engine, ext = _build_engine()
    f = tmp_path / "a.md"
    f.write_text("OpenAI 开发 GPT-4。", encoding="utf-8")
    await engine.ingest(f, access=_ctx())
    first = ext.call_count
    assert first > 0
    # 二次（同 engine/store，指纹已记录）-> 短路
    await engine.ingest(f, access=_ctx())
    assert ext.call_count == first  # 无新增调用


async def test_add_one_doc_only_one_doc_calls(tmp_path):
    """② N 篇库加 1 篇 -> 仅新增 1 篇触发抽取（已存量短路）。"""
    engine, ext = _build_engine()
    ctx = _ctx()
    a = tmp_path / "a.md"
    a.write_text("OpenAI 开发 GPT-4。", encoding="utf-8")
    await engine.ingest(a, access=ctx)
    base = ext.call_count
    # 再灌 a + b（a 未变 -> 短路；b 新 -> 抽取）
    b = tmp_path / "b.md"
    b.write_text("Anthropic 发布 Claude。", encoding="utf-8")
    await engine.ingest(tmp_path, access=ctx)  # 目录：加载 a + b
    # 仅 b 触发一次抽取（a 短路）
    assert ext.call_count == base + 1


async def test_changed_doc_reextracts(tmp_path):
    """③ 文档内容变更 -> 指纹不同 -> 重新抽取。"""
    engine, ext = _build_engine()
    f = tmp_path / "a.md"
    f.write_text("OpenAI 开发 GPT-4。", encoding="utf-8")
    await engine.ingest(f, access=_ctx())
    base = ext.call_count
    f.write_text("OpenAI 开发 GPT-4 与 DALL·E。", encoding="utf-8")  # 内容变 -> hash 变
    await engine.ingest(f, access=_ctx())
    assert ext.call_count == base + 1  # 重新抽取


async def test_incremental_disabled_reextracts_all(tmp_path):
    """incremental_indexing=False 逃生：全量重跑，不短路。"""
    engine, ext = _build_engine()
    engine.incremental_indexing = False
    f = tmp_path / "a.md"
    f.write_text("OpenAI 开发 GPT-4。", encoding="utf-8")
    await engine.ingest(f, access=_ctx())
    first = ext.call_count
    await engine.ingest(f, access=_ctx())
    assert ext.call_count == first * 2  # 再次全量抽取


# ---- P4.5 Task 3 Step 2(store)：delete_by_doc 三 store ----


async def test_delete_by_doc_across_stores():
    """InMemory 三 store delete_by_doc：chunk 删 / 图孤儿删+共享裁剪 / 社区成员移除。"""
    from calliodesmo.auth.models import ClearanceLevel, LibraryScope
    from calliodesmo.interfaces.community_store import CommunityRecord
    from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
    from calliodesmo.interfaces.vector_store import ChunkRecord
    from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
    from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
    from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore

    owner = uuid.uuid4()
    vec = InMemoryVectorStore()
    graph = InMemoryGraphStore()
    comm = InMemoryCommunityStore()

    await vec.upsert_chunks(
        [
            ChunkRecord(
                chunk_id="d#0", doc_id="d", content="c0", vector=[1.0],
                library_scope=LibraryScope.PERSONAL, owner_id=owner,
            ),
            ChunkRecord(
                chunk_id="d#1", doc_id="d", content="c1", vector=[1.0],
                library_scope=LibraryScope.PERSONAL, owner_id=owner,
            ),
        ]
    )
    await graph.upsert_graph(
        [
            EntityRecord(
                name="OnlyD", type="org", description="", source_chunk_ids=["d#0"],
                library_scope=LibraryScope.PERSONAL, owner_id=owner,
            ),
            EntityRecord(
                name="Shared", type="org", description="",
                source_chunk_ids=["d#1", "other#0"],
                library_scope=LibraryScope.PERSONAL, owner_id=owner,
            ),
        ],
        [
            RelationRecord(
                source="OnlyD", target="Shared", type="rel", description="",
                source_chunk_ids=["d#0"], library_scope=LibraryScope.PERSONAL, owner_id=owner,
            ),
        ],
    )
    await comm.upsert_communities(
        [
            CommunityRecord(
                community_id="c1", level=1, title="T", summary="",
                member_entity_names=["d", "other"],
                metadata={}, access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL, owner_id=owner,
            )
        ]
    )

    # 删文档 d
    await vec.delete_by_doc("d")
    await graph.delete_by_doc(["d#0", "d#1"])
    await comm.delete_by_doc("d")

    from calliodesmo.auth.context import AccessContext

    acc = AccessContext(
        user_id=owner, username="u", clearance=ClearanceLevel.SECRET,
        permissions=frozenset(), project_ids=frozenset(), team_ids=frozenset(),
    )
    chunks = await vec.list_chunks(access=acc)
    assert all(c.doc_id != "d" for c in chunks)  # d 的 chunk 全删

    ents = {e.name: e for e in await graph.list_entities(access=acc)}
    assert "OnlyD" not in ents  # 孤儿实体删
    assert ents["Shared"].source_chunk_ids == ["other#0"]  # 共享实体裁剪来源
    rels = await graph.list_relations(access=acc)
    assert all(r.source != "OnlyD" for r in rels)  # OnlyD 的边随孤儿删

    comms = await comm.list_communities(access=acc)
    assert "d" not in comms[0].member_entity_names  # 文档移出社区
    assert "other" in comms[0].member_entity_names  # 其他成员保留
