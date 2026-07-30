"""Task 4：MergeService 端到端合并（scope 改写 + provenance + 幂等 + 自审）。"""

import types
import uuid

import pytest

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission, Project, Team, User
from calliodesmo.collab.merge import MergeService
from calliodesmo.collab.models import Contribution, ContributionStatus
from calliodesmo.collab.service import ContributionError, ContributionService
from calliodesmo.interfaces.community_store import CommunityRecord
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore

_svc = ContributionService()
_merge = MergeService()


def _ctx(user_id, *, permissions=None, project_ids=None, team_ids=None) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=ClearanceLevel.INTERNAL,
        permissions=permissions or frozenset(),
        project_ids=frozenset(project_ids or []),
        team_ids=frozenset(team_ids or []),
    )


def _stores():
    return types.SimpleNamespace(
        vector_store=InMemoryVectorStore(),
        graph_store=InMemoryGraphStore(),
        community_store=InMemoryCommunityStore(),
    )


async def _user(session, name) -> User:
    u = User(username=name, hashed_password="x", clearance=ClearanceLevel.INTERNAL)
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


async def _seed_source(stores, user_id, doc_id="d"):
    await stores.vector_store.upsert_chunks(
        [
            ChunkRecord(
                chunk_id=f"{doc_id}#0",
                doc_id=doc_id,
                content="c0",
                vector=[1.0],
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            ),
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
            ),
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
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            ),
        ]
    )


async def _approved_to_project(session, source, project_id):
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
    reviewer = await _user(session, "reviewer")
    await _svc.approve(session, c.id, user_id=reviewer.id)
    await session.flush()
    return c, reviewer


async def test_merge_writes_to_target_scope_with_provenance(session):
    source = await _user(session, "source")
    stores = _stores()
    await _seed_source(stores, source.id)
    project_id = (await _project(session)).id
    c, reviewer = await _approved_to_project(session, source, project_id)
    source_access = _ctx(source.id)
    target_access = _ctx(reviewer.id, permissions={Permission.APPROVE}, project_ids=[project_id])
    await _merge.merge(
        session,
        c.id,
        stores=stores,
        source_access=source_access,
        target_access=target_access,
    )
    # status MERGED
    assert (await session.get(Contribution, c.id)).status == ContributionStatus.MERGED
    # 目标 scope 可见合并后数据
    visible = await stores.graph_store.list_entities(access=target_access)
    openai = next(e for e in visible if e.name == "OpenAI")
    assert openai.library_scope == LibraryScope.PROJECT
    assert openai.project_id == project_id
    assert openai.owner_id is None
    assert openai.metadata["provenance"]["contribution_id"] == str(c.id)
    # chunk 改写 scope
    chunks = await stores.vector_store.list_chunks(access=target_access)
    assert any(c.library_scope == LibraryScope.PROJECT for c in chunks)
    # 社区改写 scope
    comms = await stores.community_store.list_communities(access=target_access)
    assert any(cm.library_scope == LibraryScope.PROJECT for cm in comms)


async def test_merge_idempotent(session):
    source = await _user(session, "source")
    stores = _stores()
    await _seed_source(stores, source.id)
    project_id = (await _project(session)).id
    c, reviewer = await _approved_to_project(session, source, project_id)
    source_access = _ctx(source.id)
    target_access = _ctx(reviewer.id, permissions={Permission.APPROVE}, project_ids=[project_id])
    await _merge.merge(
        session,
        c.id,
        stores=stores,
        source_access=source_access,
        target_access=target_access,
    )
    # 已 MERGED 不可再合并
    with pytest.raises(ContributionError, match="幂等"):
        await _merge.merge(
            session,
            c.id,
            stores=stores,
            source_access=source_access,
            target_access=target_access,
        )


async def test_merge_only_approved(session):
    source = await _user(session, "source")
    stores = _stores()
    project_id = (await _project(session)).id
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
    reviewer = await _user(session, "reviewer")
    with pytest.raises(ContributionError, match="仅 approved"):
        await _merge.merge(
            session,
            c.id,
            stores=stores,
            source_access=_ctx(source.id),
            target_access=_ctx(
                reviewer.id, permissions={Permission.APPROVE}, project_ids=[project_id]
            ),
        )


async def test_merge_self_review_blocked(session):
    source = await _user(session, "source")
    stores = _stores()
    await _seed_source(stores, source.id)
    project_id = (await _project(session)).id
    # source 自己 approve（绕过自审：直接用 reviewer approve，但 merge 用 source 自己）
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
    reviewer = await _user(session, "reviewer")
    await _svc.approve(session, c.id, user_id=reviewer.id)
    await session.flush()
    # source 自己 merge -> 自审阻断
    with pytest.raises(ContributionError, match="自审阻断"):
        await _merge.merge(
            session,
            c.id,
            stores=stores,
            source_access=_ctx(source.id),
            target_access=_ctx(
                source.id, permissions={Permission.APPROVE}, project_ids=[project_id]
            ),
        )
