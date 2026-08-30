"""P6 Task 1：协作时间字段带时区往返断言（闭环 2026-W31 逾期 TODO）。

contributions 表时间列（reviewed_at / merged_at / created_at / updated_at）统一
``DateTime(timezone=True)``（TIMESTAMPTZ），服务层写 aware UTC datetime；
往返（写入 → commit → 重新读回）不丢时区信息。

测试走 ``create_all`` 全新表（直出 TIMESTAMPTZ）；既有库（含 dev 库）列型回填
（``ALTER COLUMN ... TYPE TIMESTAMPTZ USING <col> AT TIME ZONE 'UTC'``）由 Task 11
``db/migrate.py`` 承接，本任务不引入迁移工具。
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.auth.models import LibraryScope, Project, Team, User
from calliodesmo.collab.models import Contribution, ContributionStatus
from calliodesmo.collab.service import ContributionService

_svc = ContributionService()


def test_contribution_time_columns_are_timestamptz():
    """结构断言：四个时间列均为 DateTime(timezone=True)（TIMESTAMPTZ）。"""
    for name in ("reviewed_at", "merged_at", "created_at", "updated_at"):
        coltype = Contribution.__table__.c[name].type
        assert getattr(coltype, "timezone", False) is True, f"{name} 缺 timezone=True"


async def _user(session, username="u") -> User:
    u = User(username=username, hashed_password="x")
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


async def _draft(session, user_id: uuid.UUID) -> Contribution:
    return await _svc.create(
        session,
        source_user_id=user_id,
        source_scope=LibraryScope.PERSONAL,
        target_scope=LibraryScope.PROJECT,
        target_project_id=(await _project(session)).id,
        title="时区往返",
        doc_ids=["d#0"],
        source="test",
    )


async def test_aware_datetime_roundtrip(session):
    """ORM 往返：直写 aware datetime → commit → 重新查询读回不丢 tz，时刻一致。"""
    user = await _user(session)
    contribution = await _draft(session, user.id)
    reviewed = datetime(2026, 8, 29, 12, 30, 45, tzinfo=UTC)
    merged = datetime(2026, 8, 29, 13, 0, 0, tzinfo=UTC)
    contribution.reviewed_at = reviewed
    contribution.merged_at = merged
    cid = contribution.id
    await session.commit()
    session.expire_all()  # 强制失效身份映射，重新 SELECT 才是真 DB 往返
    fetched = (
        await session.execute(select(Contribution).where(Contribution.id == cid))
    ).scalar_one()
    assert fetched.reviewed_at is not None and fetched.reviewed_at.tzinfo is not None
    assert fetched.merged_at is not None and fetched.merged_at.tzinfo is not None
    # TIMESTAMPTZ 往返保时刻（asyncpg 读回 UTC aware）
    assert fetched.reviewed_at == reviewed
    assert fetched.merged_at == merged
    # server_default now() 的 created_at/updated_at 同样带时区读回
    assert fetched.created_at.tzinfo is not None
    assert fetched.updated_at.tzinfo is not None


async def test_service_transitions_write_aware_timestamps(session):
    """服务层往返：approve/reject/merge 写入的时间戳读回均带时区（不再 UTC-naive）。"""
    user = await _user(session)
    reviewer = await _user(session, "reviewer")
    uid, rid = user.id, reviewer.id
    contribution = await _draft(session, uid)
    await session.flush()
    cid = contribution.id
    before = datetime.now(UTC)
    await _svc.submit(session, contribution.id, user_id=user.id)
    await _svc.approve(session, contribution.id, user_id=reviewer.id)
    await _svc.merge(session, contribution.id, user_id=reviewer.id)
    await session.commit()
    session.expire_all()
    fetched = (
        await session.execute(select(Contribution).where(Contribution.id == cid))
    ).scalar_one()
    assert fetched.status == ContributionStatus.MERGED
    assert fetched.reviewed_at is not None and fetched.reviewed_at.tzinfo is not None
    assert fetched.merged_at is not None and fetched.merged_at.tzinfo is not None
    # 写入时刻合理性：不早于操作前、不超前过多（防回退 naive 解释造成 8 小时级漂移）
    assert fetched.reviewed_at >= before
    assert fetched.merged_at >= before
    assert fetched.merged_at - before < timedelta(minutes=5)
    # reject 路径的 reviewed_at 同样走 aware 写入（新建一条验证）
    c2 = await _draft(session, uid)
    await session.flush()
    c2id = c2.id
    await _svc.submit(session, c2.id, user_id=uid)
    await _svc.reject(session, c2.id, user_id=rid, reason="tz")
    await session.commit()
    session.expire_all()
    fetched2 = (
        await session.execute(select(Contribution).where(Contribution.id == c2id))
    ).scalar_one()
    assert fetched2.reviewed_at is not None and fetched2.reviewed_at.tzinfo is not None
