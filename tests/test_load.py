"""Task 4 Step 5：LoadService 端到端落库测试。"""

import uuid

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.ecl.load import LoadService
from calliodesmo.interfaces.chunker import Chunk
from calliodesmo.interfaces.cognify import Community
from calliodesmo.interfaces.extractor import Entity, ExtractionResult, Relation
from calliodesmo.providers.hash_embedding import HashEmbeddingProvider
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore


def _make_services():
    return (
        InMemoryVectorStore(),
        InMemoryGraphStore(),
        InMemoryCommunityStore(),
        HashEmbeddingProvider(dimension=32),
    )


async def test_load_writes_all_three_stores():
    owner = uuid.uuid4()
    vs, gs, cs, emb = _make_services()
    loader = LoadService(vs, gs, cs, emb)
    chunks = [
        Chunk(
            chunk_id="d#0",
            doc_id="d",
            content="OpenAI 开发了 GPT-4。",
            ordinal=0,
            access_level=ClearanceLevel.INTERNAL,
            library_scope=LibraryScope.PERSONAL,
            owner_id=owner,
        ),
    ]
    result = ExtractionResult(
        entities=[
            Entity(
                name="OpenAI",
                type="org",
                description="a",
                source_chunk_ids=["d#0"],
                template_conforming=True,
            )
        ],
        relations=[
            Relation(
                source="OpenAI",
                target="GPT-4",
                type="developed",
                description="",
                source_chunk_ids=["d#0"],
            )
        ],
    )
    communities = [
        Community(
            community_id="comm-0",
            level=0,
            title="生态",
            summary="概览",
            member_entity_names=["OpenAI"],
            access_level=ClearanceLevel.INTERNAL,
            library_scope=LibraryScope.PERSONAL,
            owner_id=owner,
        ),
    ]
    access = AccessContext(user_id=owner, username="u", clearance=ClearanceLevel.INTERNAL)
    await loader.load(chunks, result, communities, access=access)

    assert len(vs) == 1
    assert len(gs) == 1
    assert len(cs) == 1
    # 检索可见
    hits = await vs.search((chunks[0].content and [1.0] * 32) or [], top_k=5, access=access)
    # 用真实向量检索更稳：取嵌入结果
    embed = await emb.embed([chunks[0].content])
    hits = await vs.search(embed.vectors[0], top_k=5, access=access)
    assert any(h.chunk_id == "d#0" for h in hits)
    ent = await gs.get_entity("OpenAI", access=access)
    assert ent is not None and ent.template_conforming is True
    comms = await cs.list_communities(access=access)
    assert len(comms) == 1 and comms[0].title == "生态"


async def test_load_access_fields_inherited_from_chunk():
    owner = uuid.uuid4()
    vs, gs, cs, emb = _make_services()
    loader = LoadService(vs, gs, cs, emb)
    chunks = [
        Chunk(
            chunk_id="d#0",
            doc_id="d",
            content="内容",
            ordinal=0,
            access_level=ClearanceLevel.CONFIDENTIAL,
            library_scope=LibraryScope.PERSONAL,
            owner_id=owner,
        ),
    ]
    result = ExtractionResult(
        entities=[Entity(name="X", type="t", description="d", source_chunk_ids=["d#0"])],
    )
    access = AccessContext(user_id=owner, username="u", clearance=ClearanceLevel.SECRET)
    await loader.load(chunks, result, [], access=access)
    # 实体继承 chunk 的 access 字段
    ent = await gs.get_entity("X", access=access)
    assert ent.access_level == ClearanceLevel.CONFIDENTIAL
    assert ent.owner_id == owner
    # 越权（clearance 不足）不可见
    low = AccessContext(user_id=owner, username="u", clearance=ClearanceLevel.INTERNAL)
    assert await gs.get_entity("X", access=low) is None


async def test_load_idempotent():
    owner = uuid.uuid4()
    vs, gs, cs, emb = _make_services()
    loader = LoadService(vs, gs, cs, emb)
    chunks = [
        Chunk(
            chunk_id="d#0",
            doc_id="d",
            content="x",
            ordinal=0,
            library_scope=LibraryScope.PERSONAL,
            owner_id=owner,
        )
    ]
    result = ExtractionResult(
        entities=[Entity(name="X", type="t", description="d", source_chunk_ids=["d#0"])]
    )
    access = AccessContext(user_id=owner, username="u", clearance=ClearanceLevel.INTERNAL)
    await loader.load(chunks, result, [], access=access)
    await loader.load(chunks, result, [], access=access)
    assert len(vs) == 1
    assert len(gs) == 1
