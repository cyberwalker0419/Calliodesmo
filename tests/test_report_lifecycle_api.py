"""P8 Task 6：报告生命周期 API 测试（版本 / 回滚 / 软删除 / 复核 / 越权）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import calliodesmo.models  # noqa: F401
from calliodesmo.analysis.lifecycle import create_version
from calliodesmo.analysis.report_store import AnalysisReportStore
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import (
    ClearanceLevel,
    LibraryScope,
    Permission,
    Role,
    RolePermission,
)
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import assign_role, create_user, seed_default_roles
from calliodesmo.config import get_settings
from calliodesmo.db.session import get_session


def _token(user) -> str:
    settings = get_settings()
    return create_access_token(
        subject=str(user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user)}"}


async def _seed_user(session: AsyncSession, username: str, permissions: set[Permission]):
    await seed_default_roles(session)
    role = Role(name=f"role-{username}", description="test")
    session.add(role)
    await session.flush()
    for permission in permissions:
        session.add(RolePermission(role_id=role.id, permission=permission))
    user = await create_user(
        session, username=username, password="pw-123456", clearance=ClearanceLevel.SECRET
    )
    await assign_role(session, user=user, role_name=f"role-{username}", scope=LibraryScope.PERSONAL)
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
        subject_label="生命周期 API 测试",
        payload=_payload(summary),
        source_doc_ids=[],
        source_chunk_count=0,
        access_level=ClearanceLevel.INTERNAL,
        model="test/model",
        prompt_version="summary.v1",
        usage={"total_tokens": 1},
        verification=None,
    )


def _client(session: AsyncSession) -> httpx.AsyncClient:
    from calliodesmo.api.app import create_app

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_versions_and_rollback(session):
    owner = await _seed_user(session, "lc-api-owner", {Permission.ANALYZE})
    report = await _make_report(session, owner)
    await session.commit()
    report.payload = _payload("v2")
    await session.commit()
    await create_version(session, report.id, access=_access(owner, {Permission.ANALYZE}))
    await session.commit()

    async with _client(session) as client:
        headers = _auth(owner)
        resp = await client.get(f"/analysis/reports/{report.id}/versions", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert [item["version"] for item in data["items"]] == [2, 1]

        resp = await client.post(
            f"/analysis/reports/{report.id}/rollback",
            json={"version": 1},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["current_version"] == 3

        resp = await client.get(f"/analysis/reports/{report.id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["payload"]["summary"] == "v1"


async def test_soft_delete_restore(session):
    owner = await _seed_user(session, "lc-api-delete", {Permission.ANALYZE})
    report = await _make_report(session, owner)
    await session.commit()

    async with _client(session) as client:
        headers = _auth(owner)
        resp = await client.delete(f"/analysis/reports/{report.id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        resp = await client.get(f"/analysis/reports/{report.id}", headers=headers)
        assert resp.status_code == 404

        resp = await client.get("/analysis/reports", headers=headers)
        assert resp.json()["total"] == 0

        resp = await client.post(f"/analysis/reports/{report.id}/restore", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["deleted"] is False

        resp = await client.get(f"/analysis/reports/{report.id}", headers=headers)
        assert resp.status_code == 200


async def test_review_flow_and_illegal_transition(session):
    owner = await _seed_user(session, "lc-api-review", {Permission.ANALYZE, Permission.APPROVE})
    report = await _make_report(session, owner)
    await session.commit()

    async with _client(session) as client:
        headers = _auth(owner)
        resp = await client.post(
            f"/analysis/reports/{report.id}/review",
            json={"action": "submit", "note": "请复核"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["review_status"] == "pending"

        resp = await client.post(
            f"/analysis/reports/{report.id}/review",
            json={"action": "approve", "note": "通过"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["review_status"] == "approved"

        resp = await client.post(
            f"/analysis/reports/{report.id}/review",
            json={"action": "approve"},
            headers=headers,
        )
        assert resp.status_code == 409


async def test_review_requires_approve_permission(session):
    owner = await _seed_user(session, "lc-api-noapprove", {Permission.ANALYZE})
    report = await _make_report(session, owner)
    await session.commit()

    async with _client(session) as client:
        headers = _auth(owner)
        await client.post(
            f"/analysis/reports/{report.id}/review",
            json={"action": "submit"},
            headers=headers,
        )
        resp = await client.post(
            f"/analysis/reports/{report.id}/review",
            json={"action": "approve"},
            headers=headers,
        )
        assert resp.status_code == 404


async def test_stranger_cannot_delete_or_list_versions(session):
    owner = await _seed_user(session, "lc-api-stranger-owner", {Permission.ANALYZE})
    report = await _make_report(session, owner)
    await session.commit()
    stranger = await _seed_user(session, "lc-api-stranger", {Permission.ANALYZE})

    async with _client(session) as client:
        headers = _auth(stranger)
        resp = await client.delete(f"/analysis/reports/{report.id}", headers=headers)
        assert resp.status_code == 404
        resp = await client.get(f"/analysis/reports/{report.id}/versions", headers=headers)
        assert resp.status_code == 404
        resp = await client.post(
            f"/analysis/reports/{report.id}/rollback",
            json={"version": 1},
            headers=headers,
        )
        assert resp.status_code == 404


async def test_missing_permission_403(session):
    user = await _seed_user(session, "lc-api-noanalyze", {Permission.QUERY})
    async with _client(session) as client:
        resp = await client.get("/analysis/reports", headers=_auth(user))
        assert resp.status_code == 403


@pytest.mark.parametrize("bad_version", [0, -1])
async def test_rollback_validation(session, bad_version):
    owner = await _seed_user(session, f"lc-api-badver-{bad_version}", {Permission.ANALYZE})
    report = await _make_report(session, owner)
    await session.commit()
    async with _client(session) as client:
        resp = await client.post(
            f"/analysis/reports/{report.id}/rollback",
            json={"version": bad_version},
            headers=_auth(owner),
        )
        assert resp.status_code == 422


async def test_list_include_deleted_restore_entry(session):
    """显示已删除：include_deleted=true 返回软删除行（deleted 标记），默认不返回。"""
    owner = await _seed_user(session, "lc-api-include-deleted", {Permission.ANALYZE})
    report = await _make_report(session, owner)
    await session.commit()

    async with _client(session) as client:
        headers = _auth(owner)
        await client.delete(f"/analysis/reports/{report.id}", headers=headers)
        resp = await client.get("/analysis/reports", headers=headers)
        assert resp.json()["total"] == 0
        resp = await client.get("/analysis/reports?include_deleted=true", headers=headers)
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["deleted"] is True
