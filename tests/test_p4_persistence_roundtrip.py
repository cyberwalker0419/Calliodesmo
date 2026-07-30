"""P4.5 Task 4 Step 2：P4 合并落库贯通（持久化基线上的硬证明）。

证明 P4 协作推送的合并**真正落进真后端 DB**（PG+pgvector / Neo4j），且**进程重启不丢**：
analyst ingest(personal) -> Contribution(personal->project) -> submit -> approve ->
merge -> **全新 AppStores 实例指向同一 PG/Neo4j**（模拟重启）-> 项目库数据仍可读回
（实体/关系/社区/chunk 改写 scope + provenance + (name,type) 去重）。

这是"P4 合并真正进 DB"的硬证明——P4 内存态下合并同进程可见但重启全丢，本测试
在 Task 2 三主 store 真后端基线上证伪之。
"""

import types
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

pytest.importorskip("pgvector")  # CI 未装 persistence extra 时跳过收集
pytest.importorskip("neo4j")

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import (
    ClearanceLevel,
    LibraryScope,
    Permission,
    Project,
    Team,
    User,
)
from calliodesmo.collab.merge import MergeService
from calliodesmo.collab.models import Contribution, ContributionStatus
from calliodesmo.collab.service import ContributionService
from calliodesmo.config import get_settings
from calliodesmo.interfaces.community_store import CommunityRecord
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.neo4j_graph_store import Neo4jGraphStore
from calliodesmo.providers.pg_community_store import PgCommunityStore
from calliodesmo.providers.pg_vector_store import PgVectorStore

_DIM = get_settings().embedding_dimension
_svc = ContributionService()
_merge = MergeService()


def _ctx(
    user_id,
    *,
    permissions=None,
    project_ids=None,
    team_ids=None,
    clearance=ClearanceLevel.SECRET,
) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=clearance,
        permissions=permissions or frozenset(),
        project_ids=frozenset(project_ids or []),
        team_ids=frozenset(team_ids or []),
    )


def _vec(*coords: float) -> list[float]:
    """构造 _DIM 维向量（前若干位填 coords，其余 0）。"""
    vec = [0.0] * _DIM
    for i, c in enumerate(coords):
        vec[i] = c
    return vec


@pytest.fixture
def factory(_pg_engine):
    return async_sessionmaker(_pg_engine, expire_on_commit=False)


def _real_stores(driver, factory) -> types.SimpleNamespace:
    """构造真后端 stores 命名空间（PG 向量/社区 + Neo4j 图）。"""
    return types.SimpleNamespace(
        vector_store=PgVectorStore(factory),
        graph_store=Neo4jGraphStore(driver, factory),
        community_store=PgCommunityStore(factory),
    )


async def _user(session, name) -> User:
    u = User(username=f"{name}-{uuid.uuid4().hex[:6]}", hashed_password="x")
    session.add(u)
    await session.flush()
    return u


async def _project(session) -> Project:
    """建真实 Team+Project（PG 强制 FK，Contribution.target_project_id 须引用已存在行）。"""
    team = Team(name=f"team-{uuid.uuid4().hex[:8]}")
    session.add(team)
    await session.flush()
    project = Project(name=f"proj-{uuid.uuid4().hex[:8]}", team_id=team.id)
    session.add(project)
    await session.flush()
    return project


async def _seed_personal(stores, user_id, doc_id="d"):
    """向源用户 personal 库灌入三层样例数据（模拟 analyst ingest 结果）。"""
    await stores.vector_store.upsert_chunks(
        [
            ChunkRecord(
                chunk_id=f"{doc_id}#0",
                doc_id=doc_id,
                content="OpenAI 开发 GPT-4",
                vector=_vec(1.0),
                metadata={"doc_id": doc_id},
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            )
        ]
    )
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="OpenAI",
                type="organization",
                description="AI 公司",
                source_chunk_ids=[f"{doc_id}#0"],
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            ),
            EntityRecord(
                name="GPT-4",
                type="model",
                description="大模型",
                source_chunk_ids=[f"{doc_id}#0"],
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            ),
        ],
        [
            RelationRecord(
                source="OpenAI",
                target="GPT-4",
                type="developed",
                description="",
                source_chunk_ids=[f"{doc_id}#0"],
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            )
        ],
    )
    await stores.community_store.upsert_communities(
        [
            CommunityRecord(
                community_id=f"doc-{doc_id}",
                level=1,
                title=doc_id,
                summary="",
                member_entity_names=["OpenAI"],
                metadata={"doc_id": doc_id},
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            )
        ]
    )


async def test_merge_persists_across_restart(session, factory, neo4j_session):
    """合并落库贯通：merge 后全新 stores 实例（同一 PG/Neo4j）仍读回项目库数据。"""
    source = await _user(session, "source")
    reviewer = await _user(session, "reviewer")
    project = await _project(session)
    project_id = project.id
    # 请求边界：user/project 落库（stores 与 service 开独立 session，须 commit 才可见；
    # audit_logs.user_id / documents.owner_id 等 FK 依赖此提交）
    await session.commit()

    # 1) analyst ingest -> personal 库（stores1）
    stores1 = _real_stores(neo4j_session, factory)
    await _seed_personal(stores1, source.id)

    # 2) Contribution(personal->project) -> submit -> approve（各步骤=一次 API 请求）
    c = await _svc.create(
        session,
        source_user_id=source.id,
        source_scope=LibraryScope.PERSONAL,
        target_scope=LibraryScope.PROJECT,
        target_project_id=project_id,
        title="t",
        doc_ids=["d"],
    )
    await session.flush()
    await _svc.submit(session, c.id, user_id=source.id)
    await _svc.approve(session, c.id, user_id=reviewer.id)
    await session.commit()  # 请求边界：贡献状态机 + 审计落库

    source_access = _ctx(source.id)
    target_access = _ctx(reviewer.id, permissions={Permission.APPROVE}, project_ids=[project_id])

    # 3) merge（经 stores1 写真后端）-> status MERGED
    await _merge.merge(
        session,
        c.id,
        stores=stores1,
        source_access=source_access,
        target_access=target_access,
    )
    await session.commit()  # 请求边界：状态收尾 MERGED + 审计落库
    assert (await session.get(Contribution, c.id)).status == ContributionStatus.MERGED

    # 释放 stores1（模拟进程退出）
    del stores1

    # 4) 全新 AppStores 实例指向同一 PG/Neo4j（模拟重启）
    stores2 = _real_stores(neo4j_session, factory)

    # 5) 项目库数据仍可读回（实体/关系/社区/chunk 改写 scope + provenance + 去重）
    ents = await stores2.graph_store.list_entities(access=target_access)
    names = {e.name for e in ents}
    assert "OpenAI" in names and "GPT-4" in names
    openai = next(e for e in ents if e.name == "OpenAI")
    assert openai.library_scope == LibraryScope.PROJECT
    assert openai.project_id == project_id
    assert openai.owner_id is None
    assert openai.metadata["provenance"]["contribution_id"] == str(c.id)
    # (name, type) 去重：personal 那条不应再以 personal scope 可见
    personal_only = [e for e in ents if e.library_scope == LibraryScope.PERSONAL]
    assert all(e.name not in {"OpenAI"} for e in personal_only)

    rels = await stores2.graph_store.list_relations(access=target_access)
    assert any(r.source == "OpenAI" and r.target == "GPT-4" for r in rels)

    comms = await stores2.community_store.list_communities(access=target_access)
    assert any(cm.library_scope == LibraryScope.PROJECT for cm in comms)

    chunks = await stores2.vector_store.list_chunks(access=target_access)
    assert any(ck.library_scope == LibraryScope.PROJECT for ck in chunks)


async def test_merge_persists_query_hit_after_restart(session, factory, neo4j_session):
    """贯通延伸：合并后重启，项目库向量检索仍命中改写 scope 后的 chunk。"""
    source = await _user(session, "source")
    reviewer = await _user(session, "reviewer")
    project = await _project(session)
    project_id = project.id
    await session.commit()  # 请求边界：user/project 落库

    stores1 = _real_stores(neo4j_session, factory)
    await _seed_personal(stores1, source.id)

    c = await _svc.create(
        session,
        source_user_id=source.id,
        source_scope=LibraryScope.PERSONAL,
        target_scope=LibraryScope.PROJECT,
        target_project_id=project_id,
        title="t",
        doc_ids=["d"],
    )
    await session.flush()
    await _svc.submit(session, c.id, user_id=source.id)
    await _svc.approve(session, c.id, user_id=reviewer.id)
    await session.commit()
    await _merge.merge(
        session,
        c.id,
        stores=stores1,
        source_access=_ctx(source.id),
        target_access=_ctx(reviewer.id, permissions={Permission.APPROVE}, project_ids=[project_id]),
    )
    await session.commit()  # 请求边界：合并落库
    del stores1

    # 重启后的 stores
    stores2 = _real_stores(neo4j_session, factory)
    target_access = _ctx(reviewer.id, permissions={Permission.APPROVE}, project_ids=[project_id])
    # 向量检索命中项目库 chunk（模拟 /query 检索分支）；VectorHit 不带 scope，交叉验证
    hits = await stores2.vector_store.search(_vec(1.0), top_k=5, access=target_access)
    assert hits, "重启后项目库向量检索应有命中"
    hit_chunks = await stores2.vector_store.get_chunks_by_ids([h.chunk_id for h in hits])
    assert any(ck.library_scope == LibraryScope.PROJECT for ck in hit_chunks)
