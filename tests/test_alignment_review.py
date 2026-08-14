"""Task 6 Step 3：AlignmentReviewService 收集-批准-驳回（in-memory stores 幂等落地）。

- ``collect_pending``：manifest 对齐对（未决 status 默认 pending）
- ``approve``：并集合并到目标库 + merge_decision=auto_merged + provenance + 审计；重复批准幂等
- ``reject``：仅置 status=rejected + 审计，不动 stores；重复驳回幂等
- 自审阻断：源用户不能复核自己的推送对齐
"""

import types
import uuid

import pytest

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.collab.alignment_review import AlignmentReviewService
from calliodesmo.collab.models import Contribution, ContributionStatus
from calliodesmo.collab.service import ContributionError, ContributionNotFoundError
from calliodesmo.interfaces.graph_store import EntityRecord
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore

_svc = AlignmentReviewService()


def _ctx(user_id, *, permissions=None, project_ids=None) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=ClearanceLevel.INTERNAL,
        permissions=permissions or frozenset(),
        project_ids=frozenset(project_ids or []),
        team_ids=frozenset(),
    )


def _stores():
    return types.SimpleNamespace(
        graph_store=InMemoryGraphStore(), vector_store=None, community_store=None
    )


async def _user(session, name):
    from calliodesmo.auth.models import User

    u = User(username=name, hashed_password="x")
    session.add(u)
    await session.flush()
    return u


async def _project(session):
    from calliodesmo.auth.models import Project, Team

    team = Team(name=f"team-{uuid.uuid4().hex[:8]}")
    session.add(team)
    await session.flush()
    project = Project(name=f"proj-{uuid.uuid4().hex[:8]}", team_id=team.id)
    session.add(project)
    await session.flush()
    return project


async def _contribution(session, user, project, *, manifest=None):
    c = Contribution(
        source_user_id=user.id,
        source_scope=LibraryScope.PERSONAL,
        target_scope=LibraryScope.PROJECT,
        target_project_id=project.id,
        title="t",
        doc_ids=["d"],
        status=ContributionStatus.SUBMITTED,
        manifest=manifest or {},
    )
    session.add(c)
    await session.flush()
    return c


def _pair(**kw):
    p = dict(
        pair_id="pair-1",
        source_name="OpenAI",
        target_name="OpenAI Inc",
        score=0.9,
        type="organization",
        source_type="organization",
        target_type="organization",
        source_description="AI 研究",
        target_description="AI 研究实验室",
    )
    p.update(kw)
    return p


async def _seed_entities(stores, source_user_id, project_id):
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="OpenAI",
                type="organization",
                description="AI 研究",
                source_chunk_ids=["d#0"],
                library_scope=LibraryScope.PERSONAL,
                owner_id=source_user_id,
            ),
        ],
        [],
    )
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="OpenAI Inc",
                type="organization",
                description="AI 研究实验室",
                source_chunk_ids=["t#0"],
                library_scope=LibraryScope.PROJECT,
                owner_id=None,
                project_id=project_id,
                access_level=ClearanceLevel.INTERNAL,
            ),
        ],
        [],
    )


async def test_collect_pending_returns_pairs(session):
    source = await _user(session, "src")
    project = await _project(session)
    c = await _contribution(
        session,
        source,
        project,
        manifest={"alignment_pending": [_pair()]},
    )
    pending = await _svc.collect_pending(session, c.id, access=_ctx(source.id))
    assert len(pending) == 1
    assert pending[0]["source_name"] == "OpenAI"
    assert pending[0].get("status", "pending") == "pending"


async def test_approve_merges_into_target_store(session):
    source = await _user(session, "src")
    reviewer = await _user(session, "rev")
    project = await _project(session)
    stores = _stores()
    await _seed_entities(stores, source.id, project.id)
    c = await _contribution(
        session,
        source,
        project,
        manifest={"alignment_pending": [_pair()]},
    )
    result = await _svc.approve(
        session,
        c.id,
        pair_id="pair-1",
        user_id=reviewer.id,
        stores=stores,
        source_access=_ctx(source.id),
        target_access=_ctx(reviewer.id, project_ids=[project.id]),
    )
    assert result["status"] == "approved"
    # 目标库合并后：source_chunk_ids 并集 + merge_decision=auto_merged + provenance
    tgt_access = _ctx(reviewer.id, project_ids=[project.id])
    target = await stores.graph_store.get_entity("OpenAI Inc", access=tgt_access)
    assert target is not None
    assert target.source_chunk_ids == ["t#0", "d#0"]
    assert target.metadata["merge_decision"] == "auto_merged"
    assert target.metadata["provenance"]["contribution_id"] == str(c.id)
    assert "AI 研究" in target.description  # 描述并集


async def test_approve_idempotent(session):
    source = await _user(session, "src")
    reviewer = await _user(session, "rev")
    project = await _project(session)
    stores = _stores()
    await _seed_entities(stores, source.id, project.id)
    c = await _contribution(
        session,
        source,
        project,
        manifest={"alignment_pending": [_pair()]},
    )
    await _svc.approve(
        session,
        c.id,
        pair_id="pair-1",
        user_id=reviewer.id,
        stores=stores,
        source_access=_ctx(source.id),
        target_access=_ctx(reviewer.id, project_ids=[project.id]),
    )
    # 二次批准：不抛、仍 approved、目标实体不重复加 chunk
    result = await _svc.approve(
        session,
        c.id,
        pair_id="pair-1",
        user_id=reviewer.id,
        stores=stores,
        source_access=_ctx(source.id),
        target_access=_ctx(reviewer.id, project_ids=[project.id]),
    )
    assert result["status"] == "approved"
    tgt_access = _ctx(reviewer.id, project_ids=[project.id])
    target = await stores.graph_store.get_entity("OpenAI Inc", access=tgt_access)
    assert target.source_chunk_ids == ["t#0", "d#0"]


async def test_reject_marks_pair_no_store_write(session):
    source = await _user(session, "src")
    reviewer = await _user(session, "rev")
    project = await _project(session)
    stores = _stores()
    await _seed_entities(stores, source.id, project.id)
    c = await _contribution(
        session,
        source,
        project,
        manifest={"alignment_pending": [_pair()]},
    )
    result = await _svc.reject(
        session,
        c.id,
        pair_id="pair-1",
        user_id=reviewer.id,
        stores=stores,
        source_access=_ctx(source.id),
        target_access=_ctx(reviewer.id, project_ids=[project.id]),
    )
    assert result["status"] == "rejected"
    # 目标库实体未被改动（无 provenance / auto_merged）
    tgt_access = _ctx(reviewer.id, project_ids=[project.id])
    target = await stores.graph_store.get_entity("OpenAI Inc", access=tgt_access)
    assert "merge_decision" not in target.metadata
    assert target.source_chunk_ids == ["t#0"]
    # 重复驳回仍 rejected
    result2 = await _svc.reject(
        session,
        c.id,
        pair_id="pair-1",
        user_id=reviewer.id,
        stores=stores,
        source_access=_ctx(source.id),
        target_access=_ctx(reviewer.id, project_ids=[project.id]),
    )
    assert result2["status"] == "rejected"


async def test_approve_self_review_blocked(session):
    source = await _user(session, "src")
    project = await _project(session)
    stores = _stores()
    await _seed_entities(stores, source.id, project.id)
    c = await _contribution(
        session,
        source,
        project,
        manifest={"alignment_pending": [_pair()]},
    )
    with pytest.raises(ContributionError, match="自审阻断"):
        await _svc.approve(
            session,
            c.id,
            pair_id="pair-1",
            user_id=source.id,
            stores=stores,
            source_access=_ctx(source.id),
            target_access=_ctx(source.id, project_ids=[project.id]),
        )


async def test_approve_unknown_pair(session):
    source = await _user(session, "src")
    reviewer = await _user(session, "rev")
    project = await _project(session)
    stores = _stores()
    await _seed_entities(stores, source.id, project.id)
    c = await _contribution(
        session,
        source,
        project,
        manifest={"alignment_pending": [_pair()]},
    )
    with pytest.raises(ContributionNotFoundError):
        await _svc.approve(
            session,
            c.id,
            pair_id="nope",
            user_id=reviewer.id,
            stores=stores,
            source_access=_ctx(source.id),
            target_access=_ctx(reviewer.id, project_ids=[project.id]),
        )


async def test_approve_after_merge_blocked(session):
    """已 MERGED 的贡献不可再复核对齐。"""
    source = await _user(session, "src")
    reviewer = await _user(session, "rev")
    project = await _project(session)
    stores = _stores()
    await _seed_entities(stores, source.id, project.id)
    c = await _contribution(
        session,
        source,
        project,
        manifest={"alignment_pending": [_pair()]},
    )
    c.status = ContributionStatus.MERGED
    await session.flush()
    with pytest.raises(ContributionError, match="已合并"):
        await _svc.approve(
            session,
            c.id,
            pair_id="pair-1",
            user_id=reviewer.id,
            stores=stores,
            source_access=_ctx(source.id),
            target_access=_ctx(reviewer.id, project_ids=[project.id]),
        )


async def test_approve_status_persists_across_sessions(session):
    """manifest 就地 review_status 经 flag_modified 落库：新 session 读回 approved 且待审清空。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    source = await _user(session, "src")
    reviewer = await _user(session, "rev")
    project = await _project(session)
    stores = _stores()
    await _seed_entities(stores, source.id, project.id)
    c = await _contribution(
        session,
        source,
        project,
        manifest={"alignment_pending": [_pair()]},
    )
    tgt_access = _ctx(reviewer.id, permissions={Permission.APPROVE}, project_ids=[project.id])
    await _svc.approve(
        session,
        c.id,
        pair_id="pair-1",
        user_id=reviewer.id,
        stores=stores,
        source_access=_ctx(source.id),
        target_access=tgt_access,
    )
    await session.commit()
    # 新 session（同一测试 engine）读回：review_status=approved，待审为空
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as s2:
        fresh = await s2.get(Contribution, c.id)
        assert fresh.manifest["alignment_pending"][0]["review_status"] == "approved"
        pending = await _svc.collect_pending(s2, c.id, access=tgt_access)
        assert pending == []
