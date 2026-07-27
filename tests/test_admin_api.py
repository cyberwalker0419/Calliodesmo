"""P3 Task 1：/admin 管理端点 + require_permission 守卫 + 软删除与审计。"""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import calliodesmo.models  # noqa: F401
from calliodesmo.api.deps import require_permission
from calliodesmo.audit.models import AuditLog
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import (
    ClearanceLevel,
    LibraryScope,
    Permission,
    Role,
    RolePermission,
)
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import (
    assign_role,
    create_user,
    get_access_context,
    seed_default_roles,
)
from calliodesmo.config import get_settings
from calliodesmo.db.session import get_session


def _ctx(*permissions: Permission) -> AccessContext:
    return AccessContext(
        user_id=uuid.uuid4(),
        username="ctx-user",
        clearance=ClearanceLevel.SECRET,
        permissions=frozenset(permissions),
    )


def test_require_permission_allows():
    # 有权放行（不抛异常）
    require_permission(_ctx(Permission.MANAGE_USERS), Permission.MANAGE_USERS)


def test_require_permission_denies():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        require_permission(_ctx(Permission.QUERY), Permission.MANAGE_USERS)
    assert exc_info.value.status_code == 403


async def _seed_actor(
    session: AsyncSession,
    username: str,
    permissions: set[Permission],
    clearance: ClearanceLevel = ClearanceLevel.SECRET,
):
    """造一个带指定细粒度权限的用户，返回 (user, token)。"""
    await seed_default_roles(session)
    role = Role(name=f"role-{username}", description="test")
    session.add(role)
    await session.flush()
    for p in permissions:
        session.add(RolePermission(role_id=role.id, permission=p))
    user = await create_user(session, username=username, password="pw-123456", clearance=clearance)
    await assign_role(session, user=user, role_name=f"role-{username}", scope=LibraryScope.TEAM)
    await session.commit()
    settings = get_settings()
    token = create_access_token(
        subject=str(user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )
    return user, token


def _make_client(session: AsyncSession) -> httpx.AsyncClient:
    from calliodesmo.api.app import create_app

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


ADMIN_PERMS = {Permission.MANAGE_USERS, Permission.MANAGE_COMMUNITY, Permission.QUERY}


async def test_list_users_as_admin(session):
    _, token = await _seed_actor(session, "admin-list", ADMIN_PERMS)
    async with _make_client(session) as c:
        resp = await c.get("/admin/users", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert any(u["username"] == "admin-list" for u in body)
    admin = next(u for u in body if u["username"] == "admin-list")
    assert admin["clearance"] == "SECRET"
    assert admin["is_active"] is True
    assert {r["role"] for r in admin["roles"]} == {"role-admin-list"}


async def test_list_users_forbidden_without_manage_users(session):
    _, token = await _seed_actor(session, "analyst-only", {Permission.QUERY})
    async with _make_client(session) as c:
        resp = await c.get("/admin/users", headers=_auth(token))
    assert resp.status_code == 403


async def test_admin_requires_auth(session):
    async with _make_client(session) as c:
        resp = await c.get("/admin/users")
    assert resp.status_code == 401


async def test_create_user_endpoint(session):
    _, token = await _seed_actor(session, "admin-create", ADMIN_PERMS)
    async with _make_client(session) as c:
        resp = await c.post(
            "/admin/users",
            json={"username": "new-analyst", "password": "pw-123456", "clearance": "INTERNAL"},
            headers=_auth(token),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["username"] == "new-analyst"
        # 新用户可登录
        login = await c.post(
            "/auth/token", data={"username": "new-analyst", "password": "pw-123456"}
        )
        assert login.status_code == 200
    logs = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "manage_user")))
        .scalars()
        .all()
    )
    assert any(log.detail.get("op") == "create" for log in logs)


async def test_create_user_duplicate_conflict(session):
    _, token = await _seed_actor(session, "admin-dup", ADMIN_PERMS)
    async with _make_client(session) as c:
        resp = await c.post(
            "/admin/users",
            json={"username": "admin-dup", "password": "pw-123456"},
            headers=_auth(token),
        )
    assert resp.status_code == 409


async def test_update_user_clearance_and_active(session):
    _, token = await _seed_actor(session, "admin-update", ADMIN_PERMS)
    target = await create_user(session, username="target-user", password="pw-123456")
    await session.commit()
    async with _make_client(session) as c:
        resp = await c.patch(
            f"/admin/users/{target.id}",
            json={"clearance": "CONFIDENTIAL", "is_active": True},
            headers=_auth(token),
        )
    assert resp.status_code == 200
    assert resp.json()["clearance"] == "CONFIDENTIAL"
    await session.refresh(target)
    assert target.clearance == ClearanceLevel.CONFIDENTIAL


async def test_deactivate_user_soft_delete(session):
    _, token = await _seed_actor(session, "admin-deact", ADMIN_PERMS)
    target = await create_user(session, username="gone-user", password="pw-123456")
    await session.commit()
    async with _make_client(session) as c:
        resp = await c.delete(f"/admin/users/{target.id}", headers=_auth(token))
        assert resp.status_code == 204
        # 停用后不可登录
        login = await c.post("/auth/token", data={"username": "gone-user", "password": "pw-123456"})
        assert login.status_code == 401
    await session.refresh(target)
    assert target.is_active is False
    # get_access_context 对停用用户返回 None（沿用 P0 逻辑）
    assert await get_access_context(session, target.id) is None
    # 历史审计记录保留（软删除不清痕）
    logs = (await session.execute(select(AuditLog))).scalars().all()
    assert any(log.action == "manage_user" for log in logs)


async def test_assign_role_endpoint(session):
    _, token = await _seed_actor(session, "admin-role", ADMIN_PERMS)
    target = await create_user(session, username="role-target", password="pw-123456")
    await session.commit()
    async with _make_client(session) as c:
        resp = await c.post(
            f"/admin/users/{target.id}/roles",
            json={"role": "analyst", "scope": "personal"},
            headers=_auth(token),
        )
        assert resp.status_code == 201, resp.text
        detail = await c.get("/admin/users", headers=_auth(token))
    user_out = next(u for u in detail.json() if u["username"] == "role-target")
    assert {r["role"] for r in user_out["roles"]} == {"analyst"}


async def test_teams_crud_and_members(session):
    _, token = await _seed_actor(session, "admin-team", ADMIN_PERMS)
    member = await create_user(session, username="team-member", password="pw-123456")
    await session.commit()
    async with _make_client(session) as c:
        # 创建团队
        resp = await c.post(
            "/admin/teams",
            json={"name": "分析一组", "description": "演示团队"},
            headers=_auth(token),
        )
        assert resp.status_code == 201, resp.text
        team_id = resp.json()["id"]
        # 列表
        listing = await c.get("/admin/teams", headers=_auth(token))
        assert listing.status_code == 200
        assert any(t["name"] == "分析一组" for t in listing.json())
        # 加成员
        add = await c.post(
            f"/admin/teams/{team_id}/members",
            json={"user_id": str(member.id), "role_in_team": "member"},
            headers=_auth(token),
        )
        assert add.status_code == 201, add.text
        # 成员出现在列表中
        listing = await c.get("/admin/teams", headers=_auth(token))
        team = next(t for t in listing.json() if t["id"] == team_id)
        assert str(member.id) in {m["user_id"] for m in team["members"]}
        # 移除成员
        rm = await c.delete(f"/admin/teams/{team_id}/members/{member.id}", headers=_auth(token))
        assert rm.status_code == 204
        listing = await c.get("/admin/teams", headers=_auth(token))
        team = next(t for t in listing.json() if t["id"] == team_id)
        assert str(member.id) not in {m["user_id"] for m in team["members"]}


async def test_projects_crud_and_members(session):
    _, token = await _seed_actor(session, "admin-proj", ADMIN_PERMS)
    member = await create_user(session, username="proj-member", password="pw-123456")
    await session.commit()
    async with _make_client(session) as c:
        team_resp = await c.post("/admin/teams", json={"name": "项目组团队"}, headers=_auth(token))
        team_id = team_resp.json()["id"]
        resp = await c.post(
            "/admin/projects",
            json={"name": "夜莺项目", "team_id": team_id, "description": "演示项目"},
            headers=_auth(token),
        )
        assert resp.status_code == 201, resp.text
        project_id = resp.json()["id"]
        add = await c.post(
            f"/admin/projects/{project_id}/members",
            json={"user_id": str(member.id), "role": "analyst", "role_in_project": "member"},
            headers=_auth(token),
        )
        assert add.status_code == 201, add.text
        listing = await c.get("/admin/projects", headers=_auth(token))
        proj = next(p for p in listing.json() if p["id"] == project_id)
        assert proj["team_id"] == team_id
        assert str(member.id) in {m["user_id"] for m in proj["members"]}
        rm = await c.delete(
            f"/admin/projects/{project_id}/members/{member.id}", headers=_auth(token)
        )
        assert rm.status_code == 204


async def test_manage_actions_audited(session):
    _, token = await _seed_actor(session, "admin-audit", ADMIN_PERMS)
    async with _make_client(session) as c:
        await c.post("/admin/teams", json={"name": "审计团队"}, headers=_auth(token))
    logs = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "manage_user")))
        .scalars()
        .all()
    )
    assert any(log.detail.get("op") == "create_team" for log in logs)
