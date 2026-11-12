"""P8 Task 6：报告生命周期服务测试（版本 / 软删除 / 复核 / 并发 / 权限）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import calliodesmo.models  # noqa: F401
from calliodesmo.analysis.lifecycle import (
    ConcurrencyConflict,
    ReportNotFoundError,
    ReviewTransitionError,
    approve,
    create_version,
    list_versions,
    reject,
    restore,
    rollback,
    soft_delete,
    submit_review,
)
from calliodesmo.analysis.report_store import AnalysisReportStore
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import (
    ClearanceLevel,
    LibraryScope,
    Permission,
    Role,
    RolePermission,
)
from calliodesmo.auth.service import assign_role, create_user, seed_default_roles
from calliodesmo.db.models_analysis import AnalysisReportORM


async def _seed_user(session: AsyncSession, username: str, *, permissions: set[Permission]):
    await seed_default_roles(session)
    role_name = f"role-{username}"
    role = Role(name=role_name, description="test")
    session.add(role)
    await session.flush()
    for permission in permissions:
        session.add(RolePermission(role_id=role.id, permission=permission))
    user = await create_user(
        session, username=username, password="pw-123456", clearance=ClearanceLevel.SECRET
    )
    await assign_role(session, user=user, role_name=role_name, scope=LibraryScope.PERSONAL)
    await session.commit()
    return user


def _access(user, permissions: set[Permission]) -> AccessContext:
    return AccessContext(
        user_id=user.id,
        username=user.username,
        clearance=ClearanceLevel.SECRET,
        permissions=frozenset(permissions),
        library_scopes=frozenset({LibraryScope.PERSONAL}),
    )


def _payload(summary: str) -> dict:
    return {
        "task_type": "summary",
        "status": "ok",
        "generated_at": datetime.now(UTC).isoformat(),
        "model": "test/model",
        "prompt_version": "summary.v1",
        "usage": {"total_tokens": 1},
        "warnings": [],
        "source_chunk_ids": [],
        "payload": {"summary": summary},
    }


async def _make_report(session: AsyncSession, user, summary: str = "v1"):
    return await AnalysisReportStore().create(
        session,
        job_id=None,
        user_id=user.id,
        task_type="summary",
        status="ok",
        subject_label="测试报告",
        payload=_payload(summary),
        source_doc_ids=[],
        source_chunk_count=0,
        access_level=ClearanceLevel.INTERNAL,
        model="test/model",
        prompt_version="summary.v1",
        usage={"total_tokens": 1},
        verification={"version": 1, "totals": {"claims": 0}, "needs_review": False},
    )


@pytest.fixture
async def owner(session):
    user = await _seed_user(session, "lifecycle-owner", permissions={Permission.ANALYZE})
    return user, _access(user, {Permission.ANALYZE})


@pytest.fixture
async def reviewer(session):
    user = await _seed_user(
        session,
        "lifecycle-reviewer",
        permissions={Permission.ANALYZE, Permission.APPROVE},
    )
    return user, _access(user, {Permission.ANALYZE, Permission.APPROVE})


class TestVersions:
    async def test_create_writes_first_version(self, session, owner):
        user, access = owner
        report = await _make_report(session, user)
        await session.commit()
        versions = await list_versions(session, report.id, access=access)
        assert [v.version for v in versions] == [1]
        assert versions[0].snapshot["payload"]["payload"]["summary"] == "v1"

    async def test_create_version_appends_and_old_immutable(self, session, owner):
        user, access = owner
        report = await _make_report(session, user)
        await session.commit()
        report.payload = _payload("v2")
        await session.commit()
        version = await create_version(session, report.id, access=access)
        await session.commit()
        assert version.version == 2
        versions = await list_versions(session, report.id, access=access)
        assert [v.version for v in versions] == [2, 1]
        assert versions[0].snapshot["payload"]["payload"]["summary"] == "v2"
        assert versions[1].snapshot["payload"]["payload"]["summary"] == "v1"

    async def test_rollback_appends_target_snapshot(self, session, owner):
        user, access = owner
        report = await _make_report(session, user)
        await session.commit()
        report.payload = _payload("v2")
        await session.commit()
        await create_version(session, report.id, access=access)
        await session.commit()

        version = await rollback(session, report.id, version=1, access=access)
        await session.commit()
        assert version.version == 3
        fresh = await session.get(AnalysisReportORM, report.id)
        assert fresh.current_version == 3
        assert fresh.payload["payload"]["summary"] == "v1"
        versions = await list_versions(session, report.id, access=access)
        assert [v.version for v in versions] == [3, 2, 1]
        assert versions[0].snapshot["payload"]["payload"]["summary"] == "v1"

    async def test_rollback_missing_version(self, session, owner):
        user, access = owner
        report = await _make_report(session, user)
        await session.commit()
        with pytest.raises(ReportNotFoundError):
            await rollback(session, report.id, version=99, access=access)

    async def test_optimistic_lock_conflict(self, session, owner):
        user, access = owner
        report = await _make_report(session, user)
        await session.commit()
        with pytest.raises(ConcurrencyConflict):
            await create_version(session, report.id, access=access, expected_lock_version=99)


class TestSoftDelete:
    async def test_delete_hides_and_restore_recovers(self, session, owner):
        user, access = owner
        report = await _make_report(session, user)
        await session.commit()

        await soft_delete(session, report.id, access=access)
        await session.commit()
        assert await AnalysisReportStore().get(session, report.id, access=access) is None
        items, total = await AnalysisReportStore().list_visible(session, access=access)
        assert total == 0 and items == []

        await restore(session, report.id, access=access)
        await session.commit()
        assert await AnalysisReportStore().get(session, report.id, access=access) is not None

    async def test_delete_idempotent(self, session, owner):
        user, access = owner
        report = await _make_report(session, user)
        await session.commit()
        await soft_delete(session, report.id, access=access)
        await soft_delete(session, report.id, access=access)
        await session.commit()
        assert (await session.get(AnalysisReportORM, report.id)).deleted_at is not None


class TestReviewFlow:
    async def test_submit_approve(self, session, reviewer):
        user, access = reviewer
        report = await _make_report(session, user)
        await session.commit()
        await submit_review(session, report.id, access=access, note="请复核")
        await session.commit()
        fresh = await session.get(AnalysisReportORM, report.id)
        assert fresh.review_status == "pending"

        await approve(session, report.id, access=access, note="通过")
        await session.commit()
        fresh = await session.get(AnalysisReportORM, report.id)
        assert fresh.review_status == "approved"
        assert fresh.reviewed_by == user.id
        assert fresh.reviewed_at is not None

    async def test_reject_then_resubmit(self, session, reviewer):
        user, access = reviewer
        report = await _make_report(session, user)
        await session.commit()
        await submit_review(session, report.id, access=access)
        await session.commit()
        await reject(session, report.id, access=access, note="补证据")
        await session.commit()
        assert (await session.get(AnalysisReportORM, report.id)).review_status == "rejected"
        await submit_review(session, report.id, access=access)
        await session.commit()
        assert (await session.get(AnalysisReportORM, report.id)).review_status == "pending"

    async def test_illegal_transition(self, session, reviewer):
        user, access = reviewer
        report = await _make_report(session, user)
        await session.commit()
        with pytest.raises(ReviewTransitionError):
            await approve(session, report.id, access=access)

    async def test_approve_requires_permission(self, session, owner):
        user, access = owner
        report = await _make_report(session, user)
        await session.commit()
        await submit_review(session, report.id, access=access)
        await session.commit()
        with pytest.raises(ReportNotFoundError):
            await approve(session, report.id, access=access)


class TestPermissionBoundary:
    async def test_stranger_sees_nothing(self, session, owner):
        user = owner[0]
        report = await _make_report(session, user)
        await session.commit()
        stranger = await _seed_user(session, "lifecycle-stranger", permissions={Permission.ANALYZE})
        stranger_access = _access(stranger, {Permission.ANALYZE})
        with pytest.raises(ReportNotFoundError):
            await list_versions(session, report.id, access=stranger_access)
        with pytest.raises(ReportNotFoundError):
            await soft_delete(session, report.id, access=stranger_access)
        with pytest.raises(ReportNotFoundError):
            await rollback(session, report.id, version=1, access=stranger_access)
        with pytest.raises(ReportNotFoundError):
            await submit_review(session, report.id, access=stranger_access)

    async def test_versions_of_deleted_report_hidden(self, session, owner):
        user, access = owner
        report = await _make_report(session, user)
        await session.commit()
        await soft_delete(session, report.id, access=access)
        await session.commit()
        with pytest.raises(ReportNotFoundError):
            await list_versions(session, report.id, access=access)
