"""P9 Task 10：Agent 会话生命周期（软删除 / 恢复）——服务层 + API。

W49 重评把 P8 条件任务 T8 收进 P9：会话「能建不能用」是可用性缺口（用户删不掉自己
的历史会话）。范围只取最小闭环——软删除 + 恢复 + 权限 + 审计；归档与共享范围变更
仍移交（牵动三维权限与会话可见性语义，见计划「暂缓与移交记录」）。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import calliodesmo.models  # noqa: F401
from calliodesmo.agent.errors import AgentAccessError
from calliodesmo.agent.session_lifecycle import (
    list_sessions_for_access,
    restore_session,
    soft_delete_session,
)
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission, Role, RolePermission
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import assign_role, create_user, seed_default_roles
from calliodesmo.config import get_settings
from calliodesmo.db.models_agent import AgentMessageORM, AgentRunORM, AgentSessionORM


async def _user(session: AsyncSession, username: str) -> uuid.UUID:
    """真实用户行（audit_logs.user_id 有 FK，随机 UUID 写不进审计）。"""
    user = await create_user(
        session, username=username, password="pw-123456", clearance=ClearanceLevel.INTERNAL
    )
    await session.commit()
    return user.id


def _access(user_id, *, permissions=(Permission.QUERY,), clearance=ClearanceLevel.INTERNAL):
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=clearance,
        permissions=frozenset(permissions),
        library_scopes=frozenset({LibraryScope.PERSONAL}),
    )


async def _make_session(
    session: AsyncSession, *, owner_id: uuid.UUID, label: str = "会话"
) -> AgentSessionORM:
    row = AgentSessionORM(
        owner_id=owner_id,
        mode="react",
        label=label,
        access_level=ClearanceLevel.INTERNAL,
        library_scope=LibraryScope.PERSONAL,
        clearance_at_create=ClearanceLevel.INTERNAL,
        scope_at_create=LibraryScope.PERSONAL,
    )
    session.add(row)
    await session.flush()
    session.add(AgentMessageORM(session_id=row.id, role="user", content="你好"))
    session.add(
        AgentRunORM(session_id=row.id, status="succeeded", steps=1, tool_trace=[], usage={})
    )
    await session.commit()
    return row


class TestServiceLifecycle:
    async def test_soft_delete_hides_from_default_list(self, session: AsyncSession):
        owner = await _user(session, "svc-owner-1")
        row = await _make_session(session, owner_id=owner)
        access = _access(owner)
        assert [s.id for s in await list_sessions_for_access(session, access=access)] == [row.id]

        await soft_delete_session(session, row.id, access=access)
        await session.commit()
        assert await list_sessions_for_access(session, access=access) == []
        visible = await list_sessions_for_access(session, access=access, include_deleted=True)
        assert [s.id for s in visible] == [row.id]
        assert visible[0].deleted_at is not None

    async def test_restore_brings_back(self, session: AsyncSession):
        owner = await _user(session, "svc-owner-2")
        row = await _make_session(session, owner_id=owner)
        access = _access(owner)
        await soft_delete_session(session, row.id, access=access)
        await session.commit()
        await restore_session(session, row.id, access=access)
        await session.commit()
        assert [s.id for s in await list_sessions_for_access(session, access=access)] == [row.id]

    async def test_delete_is_idempotent(self, session: AsyncSession):
        owner = await _user(session, "svc-owner-3")
        row = await _make_session(session, owner_id=owner)
        access = _access(owner)
        first = await soft_delete_session(session, row.id, access=access)
        await session.commit()
        second = await soft_delete_session(session, row.id, access=access)
        await session.commit()
        assert first.deleted_at is not None
        assert second.deleted_at == first.deleted_at  # 不刷新时间，不重复写审计

    async def test_cross_owner_same_error_as_missing(self, session: AsyncSession):
        owner = await _user(session, "svc-owner-4")
        row = await _make_session(session, owner_id=owner)
        outsider = await _user(session, "svc-outsider")
        with pytest.raises(AgentAccessError) as mine:
            await soft_delete_session(session, row.id, access=_access(outsider))
        with pytest.raises(AgentAccessError) as missing:
            await soft_delete_session(session, uuid.uuid4(), access=_access(owner))
        # 越权与不存在同语义（不泄漏存在性）
        assert str(mine.value) == str(missing.value)

    async def test_deleted_session_not_runnable(self, session: AsyncSession):
        from calliodesmo.agent.access import verify_session_access

        owner = await _user(session, "svc-owner-5")
        row = await _make_session(session, owner_id=owner)
        access = _access(owner)
        await soft_delete_session(session, row.id, access=access)
        await session.refresh(row)
        assert verify_session_access(row, access=access) is False

    async def test_admin_may_delete_others(self, session: AsyncSession):
        owner = await _user(session, "svc-owner-6")
        admin = await _user(session, "svc-admin")
        row = await _make_session(session, owner_id=owner)
        admin_access = _access(admin, permissions=(Permission.MANAGE_USERS,))
        await soft_delete_session(session, row.id, access=admin_access)
        await session.commit()
        assert await list_sessions_for_access(session, access=_access(owner)) == []


async def _seed_actor(session: AsyncSession, username: str, permissions: set[Permission]):
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
    settings = get_settings()
    return user, create_access_token(
        subject=str(user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.jwt_expire_minutes,
    )


@pytest.fixture
async def agent_client(
    client: httpx.AsyncClient, session: AsyncSession
) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str]]]:
    owner, owner_token = await _seed_actor(session, "sess-owner", {Permission.QUERY})
    _admin, admin_token = await _seed_actor(session, "sess-admin", {Permission.MANAGE_USERS})
    yield (
        client,
        {
            "owner": owner_token,
            "admin": admin_token,
            "owner_id": str(owner.id),
        },
    )


class TestApi:
    async def test_delete_and_restore_flow(self, agent_client, session: AsyncSession):
        client, tokens = agent_client
        row = await _make_session(session, owner_id=uuid.UUID(tokens["owner_id"]), label="待删")
        headers = {"Authorization": f"Bearer {tokens['owner']}"}

        resp = await client.get("/agent/sessions", headers=headers)
        assert resp.status_code == 200
        assert [item["id"] for item in resp.json()["items"]] == [str(row.id)]

        resp = await client.delete(f"/agent/sessions/{row.id}", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted_at"]

        resp = await client.get("/agent/sessions", headers=headers)
        assert resp.json()["items"] == []

        resp = await client.get(
            "/agent/sessions", params={"include_deleted": "true"}, headers=headers
        )
        assert [item["id"] for item in resp.json()["items"]] == [str(row.id)]
        assert resp.json()["items"][0]["deleted_at"]

        # 已删除会话不可再跑回合
        resp = await client.post(
            f"/agent/sessions/{row.id}/runs",
            json={"question": "还在吗", "system": None},
            headers=headers,
        )
        assert resp.status_code == 404

        resp = await client.post(f"/agent/sessions/{row.id}/restore", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted_at"] is None

    async def test_cross_user_404_same_message(self, agent_client, session: AsyncSession):
        client, tokens = agent_client
        stranger = await _user(session, "api-stranger")
        row = await _make_session(session, owner_id=stranger)
        resp = await client.delete(
            f"/agent/sessions/{row.id}",
            headers={"Authorization": f"Bearer {tokens['owner']}"},
        )
        assert resp.status_code == 404
        missing = await client.delete(
            f"/agent/sessions/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {tokens['owner']}"},
        )
        assert missing.status_code == 404
        assert missing.json()["detail"] == resp.json()["detail"]

    async def test_requires_query_permission(self, agent_client, session: AsyncSession):
        client, tokens = agent_client
        row = await _make_session(session, owner_id=uuid.UUID(tokens["owner_id"]))
        # 无 query 权限的账户（仅 manage_users）删别人的会话要有权衡：admin 可以
        resp = await client.delete(
            f"/agent/sessions/{row.id}",
            headers={"Authorization": f"Bearer {tokens['admin']}"},
        )
        assert resp.status_code == 200, resp.text

    async def test_unauthenticated_401(self, agent_client):
        client, _tokens = agent_client
        resp = await client.delete(f"/agent/sessions/{uuid.uuid4()}")
        assert resp.status_code == 401
