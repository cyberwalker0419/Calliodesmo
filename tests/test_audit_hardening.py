"""P9 Task 4：审计硬化——敏感字段脱敏、查询 API、留存策略。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import calliodesmo.models  # noqa: F401
from calliodesmo.audit.models import AuditLog
from calliodesmo.audit.service import (
    AuditEntry,
    list_audit_logs,
    purge_expired_audit,
    record_audit,
    sanitize_audit_detail,
)
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission, Role, RolePermission
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import assign_role, create_user, seed_default_roles
from calliodesmo.config import get_settings

# ---------- 脱敏（纯函数） ----------


class TestSanitizeAuditDetail:
    def test_masks_top_level_secrets(self):
        cleaned = sanitize_audit_detail(
            {"username": "bob", "password": "pw-123456", "api_key": "sk-xxx", "count": 3}
        )
        assert cleaned["username"] == "bob"
        assert cleaned["count"] == 3
        assert cleaned["password"] == "***"
        assert cleaned["api_key"] == "***"

    def test_masks_nested_and_lists(self):
        cleaned = sanitize_audit_detail(
            {
                "request": {"Authorization": "Bearer abc", "mode": "local"},
                "items": [{"token": "t-1", "id": 7}, {"Secret": "s"}],
            }
        )
        assert cleaned["request"]["mode"] == "local"
        assert cleaned["request"]["Authorization"] == "***"
        assert cleaned["items"][0] == {"token": "***", "id": 7}
        assert cleaned["items"][1] == {"Secret": "***"}

    def test_key_name_variants(self):
        for key in ("password_hash", "jwt_secret_key", "refresh_TOKEN", "cookie"):
            assert sanitize_audit_detail({key: "value"})[key] == "***", key

    def test_does_not_mutate_input(self):
        original = {"password": "pw", "nested": {"token": "t"}}
        snapshot = {"password": "pw", "nested": {"token": "t"}}
        sanitize_audit_detail(original)
        assert original == snapshot

    def test_non_dict_passthrough(self):
        assert sanitize_audit_detail(None) == {}
        assert sanitize_audit_detail(["a", {"token": "x"}]) == ["a", {"token": "***"}]


# ---------- 服务层（连真实 PG） ----------


async def _make_user(session: AsyncSession, username: str, *, permissions: set[Permission]):
    await seed_default_roles(session)
    role = Role(name=f"role-{username}", description="test")
    session.add(role)
    await session.flush()
    for permission in permissions:
        session.add(RolePermission(role_id=role.id, permission=permission))
    user = await create_user(
        session, username=username, password="pw-123456", clearance=ClearanceLevel.SECRET
    )
    await assign_role(session, user=user, role_name=f"role-{username}", scope=LibraryScope.TEAM)
    await session.commit()
    return user


class TestRecordAuditSanitizes:
    async def test_detail_masked_before_persist(self, session: AsyncSession):
        user = await _make_user(session, "auditor", permissions={Permission.MANAGE_USERS})
        await record_audit(
            session,
            user_id=user.id,
            action="manage_user",
            detail={"op": "create", "password": "pw-123456"},
            source="api",
        )
        await session.commit()
        rows = (await session.execute(AuditLog.__table__.select())).fetchall()
        assert len(rows) == 1
        detail = rows[0].detail
        assert detail["password"] == "***"
        assert detail["op"] == "create"


class TestListAuditLogs:
    async def _seed(self, session: AsyncSession):
        alice = await _make_user(session, "alice", permissions={Permission.QUERY})
        bob = await _make_user(session, "bob", permissions={Permission.MANAGE_USERS})
        await record_audit(session, user_id=alice.id, action="login", source="api")
        await record_audit(session, user_id=alice.id, action="query", source="api")
        await record_audit(session, user_id=bob.id, action="login", source="cli")
        await session.commit()
        return alice, bob

    async def test_filters_and_ordering(self, session: AsyncSession):
        alice, _bob = await self._seed(session)
        entries, total = await list_audit_logs(session, action="login")
        assert total == 2
        assert {e.username for e in entries} == {"alice", "bob"}
        assert all(isinstance(e, AuditEntry) for e in entries)
        # 时间倒序（同秒内按 id 倒序，确定性由测试只断言集合）
        entries, total = await list_audit_logs(session, user_id=alice.id)
        assert total == 2
        assert {e.action for e in entries} == {"login", "query"}

    async def test_time_window_and_pagination(self, session: AsyncSession):
        await self._seed(session)
        future = datetime.now(UTC) + timedelta(days=1)
        entries, total = await list_audit_logs(session, since=future)
        assert total == 0 and entries == []
        past = datetime.now(UTC) - timedelta(days=1)
        entries, total = await list_audit_logs(session, until=past)
        assert total == 0
        page, total = await list_audit_logs(session, limit=2, offset=0)
        assert total == 3 and len(page) == 2
        rest, total = await list_audit_logs(session, limit=2, offset=2)
        assert total == 3 and len(rest) == 1

    async def test_source_filter(self, session: AsyncSession):
        await self._seed(session)
        entries, total = await list_audit_logs(session, source="cli")
        assert total == 1
        assert entries[0].source == "cli"


class TestPurgeExpiredAudit:
    async def test_deletes_only_expired(self, session: AsyncSession):
        user = await _make_user(session, "carol", permissions={Permission.MANAGE_USERS})
        await record_audit(session, user_id=user.id, action="login", source="api")
        await session.commit()
        # 手工把这条记录改到 40 天前
        row = (await session.execute(AuditLog.__table__.select())).fetchone()
        old = datetime.now(UTC) - timedelta(days=40)
        await session.execute(
            AuditLog.__table__.update()
            .where(AuditLog.__table__.c.id == row.id)
            .values(created_at=old)
        )
        await record_audit(session, user_id=user.id, action="query", source="api")
        await session.commit()

        assert await purge_expired_audit(session, retention_days=0) == 0  # 0 = 永久保留
        removed = await purge_expired_audit(session, retention_days=30)
        assert removed == 1
        await session.commit()
        assert await purge_expired_audit(session, retention_days=30) == 0
        _entries, total = await list_audit_logs(session)
        assert total == 1

    async def test_uses_settings_default(self, session: AsyncSession, monkeypatch):
        monkeypatch.setenv("CALLIODESMO_AUDIT_RETENTION_DAYS", "0")
        get_settings.cache_clear()
        assert await purge_expired_audit(session) == 0
        monkeypatch.delenv("CALLIODESMO_AUDIT_RETENTION_DAYS", raising=False)
        get_settings.cache_clear()


# ---------- API ----------


@pytest.fixture
async def audit_client(
    client: httpx.AsyncClient, session: AsyncSession
) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str]]]:
    """带一个 admin（manage_users）与一个 analyst（query）的测试客户端。"""
    admin = await _make_user(session, "audit-admin", permissions={Permission.MANAGE_USERS})
    analyst = await _make_user(session, "audit-analyst", permissions={Permission.QUERY})
    settings = get_settings()
    tokens = {
        "admin": create_access_token(
            subject=str(admin.id),
            secret_key=settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
            expires_minutes=settings.jwt_expire_minutes,
        ),
        "analyst": create_access_token(
            subject=str(analyst.id),
            secret_key=settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
            expires_minutes=settings.jwt_expire_minutes,
        ),
    }
    await record_audit(session, user_id=admin.id, action="login", source="api")
    await record_audit(
        session, user_id=analyst.id, action="query", detail={"mode": "local"}, source="api"
    )
    await session.commit()
    yield client, tokens


class TestAuditApi:
    async def test_admin_can_query_with_filters(self, audit_client):
        client, tokens = audit_client
        resp = await client.get(
            "/admin/audit", headers={"Authorization": f"Bearer {tokens['admin']}"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 2
        assert {item["action"] for item in body["items"]} >= {"login", "query"}

        resp = await client.get(
            "/admin/audit",
            params={"action": "login"},
            headers={"Authorization": f"Bearer {tokens['admin']}"},
        )
        assert resp.status_code == 200
        assert all(item["action"] == "login" for item in resp.json()["items"])

    async def test_pagination_params(self, audit_client):
        client, tokens = audit_client
        resp = await client.get(
            "/admin/audit",
            params={"limit": 1},
            headers={"Authorization": f"Bearer {tokens['admin']}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1
        assert resp.json()["total"] >= 2

    async def test_requires_manage_users(self, audit_client):
        client, tokens = audit_client
        resp = await client.get(
            "/admin/audit", headers={"Authorization": f"Bearer {tokens['analyst']}"}
        )
        assert resp.status_code == 403

    async def test_bad_since_is_422(self, audit_client):
        client, tokens = audit_client
        resp = await client.get(
            "/admin/audit",
            params={"since": "not-a-date"},
            headers={"Authorization": f"Bearer {tokens['admin']}"},
        )
        assert resp.status_code == 422

    async def test_detail_never_exposes_secrets(self, audit_client, session: AsyncSession):
        client, tokens = audit_client
        await record_audit(
            session,
            user_id=None,  # 匿名/系统动作同样必须脱敏
            action="manage_user",
            detail={"op": "reset", "password": "plain-secret"},
            source="api",
        )
        await session.commit()
        resp = await client.get(
            "/admin/audit",
            params={"action": "manage_user"},
            headers={"Authorization": f"Bearer {tokens['admin']}"},
        )
        assert resp.status_code == 200
        assert "plain-secret" not in resp.text
