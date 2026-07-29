"""Task 1：ContributionService 状态机 / 审计 / 可见性过滤 / 并发乐观锁。"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm.exc import StaleDataError

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.audit.models import AuditLog
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission, User
from calliodesmo.collab.models import Contribution, ContributionStatus
from calliodesmo.collab.service import ContributionError, ContributionService
from calliodesmo.db.base import Base

_svc = ContributionService()


def _ctx(user_id, *, permissions=None, project_ids=None, team_ids=None) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=ClearanceLevel.INTERNAL,
        permissions=permissions or frozenset(),
        project_ids=frozenset(project_ids or []),
        team_ids=frozenset(team_ids or []),
    )


async def _user(session, username="u") -> User:
    u = User(username=username, hashed_password="x")
    session.add(u)
    await session.flush()
    return u


async def _draft(session, user, **kw):
    return await _svc.create(
        session,
        source_user_id=user.id,
        source_scope=LibraryScope.PERSONAL,
        target_scope=kw.get("target_scope", LibraryScope.PROJECT),
        target_project_id=kw.get("target_project_id", uuid.uuid4()),
        target_team_id=kw.get("target_team_id"),
        title=kw.get("title", "t"),
        doc_ids=kw.get("doc_ids", ["d#0"]),
        source="api",
    )


async def test_create_draft_and_audit(session):
    user = await _user(session)
    c = await _draft(session, user, doc_ids=["d#0", "d#1"])
    await session.commit()
    assert c.status == ContributionStatus.DRAFT
    assert c.doc_ids == ["d#0", "d#1"]
    # 审计 push
    logs = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "push"))).scalars().all()
    )
    assert len(logs) == 1
    assert logs[0].resource_id == str(c.id)


async def test_create_rejects_invalid_scope_direction(session):
    user = await _user(session)
    # project -> personal 降向应抛错
    with pytest.raises(ContributionError, match="目标 scope"):
        await _svc.create(
            session,
            source_user_id=user.id,
            source_scope=LibraryScope.PROJECT,
            target_scope=LibraryScope.PERSONAL,
            title="x",
            doc_ids=[],
        )
    # team -> team 同级应抛错
    with pytest.raises(ContributionError):
        await _svc.create(
            session,
            source_user_id=user.id,
            source_scope=LibraryScope.TEAM,
            target_scope=LibraryScope.TEAM,
            target_team_id=uuid.uuid4(),
            title="x",
            doc_ids=[],
        )


async def test_create_rejects_missing_target_id(session):
    user = await _user(session)
    with pytest.raises(ContributionError, match="target_project_id"):
        await _svc.create(
            session,
            source_user_id=user.id,
            source_scope=LibraryScope.PERSONAL,
            target_scope=LibraryScope.PROJECT,
            title="x",
            doc_ids=[],
        )
    with pytest.raises(ContributionError, match="target_team_id"):
        await _svc.create(
            session,
            source_user_id=user.id,
            source_scope=LibraryScope.PERSONAL,
            target_scope=LibraryScope.TEAM,
            title="x",
            doc_ids=[],
        )


async def test_state_machine_happy_path(session):
    user = await _user(session)
    c = await _draft(session, user)
    await session.flush()
    await _svc.submit(session, c.id, user_id=user.id)
    await _svc.approve(session, c.id, user_id=uuid.uuid4())  # Task 3 加自审阻断
    await _svc.merge(session, c.id, user_id=uuid.uuid4())
    await session.commit()
    fetched = await session.get(Contribution, c.id)
    assert fetched.status == ContributionStatus.MERGED
    assert fetched.merged_at is not None
    assert fetched.reviewed_by is not None
    # version 随流转自增：create(1) submit(2) approve(3) merge(4)
    assert fetched.version == 4


async def test_state_machine_illegal_transition(session):
    user = await _user(session)
    c = await _draft(session, user)
    await session.flush()
    # draft 直接 approve 非法
    with pytest.raises(ContributionError, match="非法状态跳转"):
        await _svc.approve(session, c.id, user_id=uuid.uuid4())
    # draft 直接 merge 非法
    with pytest.raises(ContributionError):
        await _svc.merge(session, c.id, user_id=uuid.uuid4())


async def test_reopen_rejected(session):
    """B2：rejected -> submitted reopen，保留同一 MR 上下文。"""
    user = await _user(session)
    c = await _draft(session, user)
    await session.flush()
    await _svc.submit(session, c.id, user_id=user.id)
    await _svc.reject(session, c.id, user_id=uuid.uuid4(), reason="改一下")
    assert (await session.get(Contribution, c.id)).status == ContributionStatus.REJECTED
    await _svc.reopen(session, c.id, user_id=user.id)
    assert (await session.get(Contribution, c.id)).status == ContributionStatus.SUBMITTED


async def test_close(session):
    user = await _user(session)
    c = await _draft(session, user)
    await session.flush()
    await _svc.close(session, c.id, user_id=user.id)
    assert (await session.get(Contribution, c.id)).status == ContributionStatus.CLOSED
    # closed 不可再 approve
    with pytest.raises(ContributionError):
        await _svc.approve(session, c.id, user_id=uuid.uuid4())


async def test_visibility_filtering(session):
    source = await _user(session, "source")
    reviewer = await _user(session, "reviewer")
    other = await _user(session, "other")
    pid = uuid.uuid4()
    c = await _draft(session, source, target_project_id=pid)
    await session.flush()
    # 源用户可见
    assert await _svc.get(session, c.id, access=_ctx(source.id)) is not None
    # 目标项目内持 APPROVE 的 reviewer 可见
    ctx_rev = _ctx(reviewer.id, permissions=frozenset({Permission.APPROVE}), project_ids=[pid])
    assert await _svc.get(session, c.id, access=ctx_rev) is not None
    # 无关用户不可见（返回 None）
    assert await _svc.get(session, c.id, access=_ctx(other.id)) is None
    # 列表过滤
    assert len(await _svc.list(session, access=ctx_rev)) == 1
    assert len(await _svc.list(session, access=_ctx(other.id))) == 0


async def test_version_optimistic_lock():
    """B1：并发——version 乐观锁，stale 对象提交抛 StaleDataError。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        user = User(username="u", hashed_password="x")
        s.add(user)
        await s.flush()
        c = await _draft(s, user)
        await s.commit()
        cid = c.id
    # s1 持 stale version=1，s2 改并 commit（version->2），s1 提交应抛 StaleDataError
    async with factory() as s1:
        c1 = await s1.get(Contribution, cid)
        async with factory() as s2:
            c2 = await s2.get(Contribution, cid)
            c2.title = "被另一个会话改了"
            await s2.commit()
        c1.title = "用过期版本改"
        with pytest.raises(StaleDataError):
            await s1.commit()
    await engine.dispose()
