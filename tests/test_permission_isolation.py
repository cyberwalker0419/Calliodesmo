"""P3 Task 8：权限矩阵回归——每个受限端点 × 角色 × 期望状态码。

后端为权限唯一真相：前端隐藏仅 UX，越权直击后端端点 -> 403。
参数化矩阵覆盖 analyst/reviewer/admin 三角色对 /query、/admin/*、/library/*、
/admin/document-communities 的可见性，断言与 DEFAULT_ROLE_PERMISSIONS 一致。
"""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import calliodesmo.models  # noqa: F401
from calliodesmo.auth.models import (
    DEFAULT_ROLE_PERMISSIONS,
    ClearanceLevel,
    LibraryScope,
    Permission,
)
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import assign_role, create_user, seed_default_roles
from calliodesmo.config import get_settings
from calliodesmo.db.session import get_session


async def _seed_role_user(session: AsyncSession, role_name: str) -> tuple[uuid.UUID, str]:
    """用内置角色（analyst/reviewer/admin）造一个 SECRET clearance 的 team-scope 用户。"""
    await seed_default_roles(session)
    user = await create_user(
        session,
        username=f"{role_name}-matrix",
        password="pw-123456",
        clearance=ClearanceLevel.SECRET,
    )
    await assign_role(session, user=user, role_name=role_name, scope=LibraryScope.TEAM)
    await session.commit()
    settings = get_settings()
    token = create_access_token(
        subject=str(user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )
    return user.id, token


def _make_client(session: AsyncSession) -> httpx.AsyncClient:
    from calliodesmo.api.app import create_app

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _expects(perm: Permission) -> int:
    """有该权限 -> 200/201/204；无 -> 403。"""
    return 403


ROLES = ["analyst", "reviewer", "admin"]


@pytest.mark.parametrize("role", ROLES)
async def test_query_endpoint_permission_matrix(session, role):
    """`/query` 需 QUERY 权限。analyst/reviewer 有、admin 有。"""
    from calliodesmo.api.deps import get_search_engine
    from calliodesmo.interfaces.retriever import Answer, SearchMode

    class _Stub:
        async def query(self, question, *, mode: SearchMode, top_k, access):
            return Answer(text="a", source_chunk_ids=[], mode=mode, model="stub")

    _, token = await _seed_role_user(session, role)
    from calliodesmo.api.app import create_app

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    async def _eng():
        return _Stub()

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_search_engine] = _eng
    transport = httpx.ASGITransport(app=app)
    perms = DEFAULT_ROLE_PERMISSIONS[role]
    expected = 200 if Permission.QUERY in perms else 403
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/query",
            json={"question": "q", "mode": "native_rag", "top_k": 5},
            headers=_auth(token),
        )
        assert resp.status_code == expected


@pytest.mark.parametrize("role", ROLES)
async def test_admin_users_permission_matrix(session, role):
    """`/admin/users` 需 MANAGE_USERS。仅 admin 有。"""
    _, token = await _seed_role_user(session, role)
    perms = DEFAULT_ROLE_PERMISSIONS[role]
    expected = 200 if Permission.MANAGE_USERS in perms else 403
    async with _make_client(session) as c:
        resp = await c.get("/admin/users", headers=_auth(token))
    assert resp.status_code == expected


@pytest.mark.parametrize("role", ROLES)
async def test_admin_teams_permission_matrix(session, role):
    """`/admin/teams` 需 MANAGE_USERS。仅 admin。"""
    _, token = await _seed_role_user(session, role)
    expected = 200 if Permission.MANAGE_USERS in DEFAULT_ROLE_PERMISSIONS[role] else 403
    async with _make_client(session) as c:
        resp = await c.get("/admin/teams", headers=_auth(token))
    assert resp.status_code == expected


@pytest.mark.parametrize("role", ROLES)
async def test_library_profile_cards_permission_matrix(session, role):
    """`/library/profile-cards` 需 QUERY。analyst/reviewer/admin 都有。"""
    from calliodesmo.api import deps

    deps.reset_app_stores()
    _, token = await _seed_role_user(session, role)
    expected = 200 if Permission.QUERY in DEFAULT_ROLE_PERMISSIONS[role] else 403
    try:
        async with _make_client(session) as c:
            resp = await c.get("/library/profile-cards", headers=_auth(token))
        assert resp.status_code == expected
    finally:
        deps.reset_app_stores()


@pytest.mark.parametrize("role", ROLES)
async def test_admin_document_communities_permission_matrix(session, role):
    """`/admin/document-communities` 需 MANAGE_COMMUNITY。仅 admin。"""
    from calliodesmo.api import deps

    deps.reset_app_stores()
    _, token = await _seed_role_user(session, role)
    expected = 200 if Permission.MANAGE_COMMUNITY in DEFAULT_ROLE_PERMISSIONS[role] else 403
    try:
        async with _make_client(session) as c:
            resp = await c.get("/admin/document-communities", headers=_auth(token))
        assert resp.status_code == expected
    finally:
        deps.reset_app_stores()


# ---- P4.5 Task 4 Step 5：/collab push/approve/merge × 三角色矩阵 ----
# approve/merge 需 APPROVE（analyst 无 -> 403；reviewer/admin 有 -> 守卫过、贡献不存在 -> 404）。
# 随机 UUID 隔离守卫：403 = 权限拒绝，404 = 守卫通过后业务层找不到。


@pytest.mark.parametrize("role", ROLES)
async def test_collab_list_permission_matrix(session, role):
    """`GET /collab` 需 PUSH 或 APPROVE。三角色均有 -> 200。"""
    _, token = await _seed_role_user(session, role)
    perms = DEFAULT_ROLE_PERMISSIONS[role]
    expected = 200 if (Permission.PUSH in perms or Permission.APPROVE in perms) else 403
    async with _make_client(session) as c:
        resp = await c.get("/collab", headers=_auth(token))
    assert resp.status_code == expected


@pytest.mark.parametrize("role", ROLES)
async def test_collab_approve_permission_matrix(session, role):
    """`/collab/{id}/approve` 需 APPROVE。analyst 403；reviewer/admin 404（守卫过、贡献不存在）。"""
    _, token = await _seed_role_user(session, role)
    expected = 404 if Permission.APPROVE in DEFAULT_ROLE_PERMISSIONS[role] else 403
    async with _make_client(session) as c:
        resp = await c.post(f"/collab/{uuid.uuid4()}/approve", headers=_auth(token))
    assert resp.status_code == expected


@pytest.mark.parametrize("role", ROLES)
async def test_collab_merge_permission_matrix(session, role):
    """`/collab/{id}/merge` 需 APPROVE。analyst 403；reviewer/admin 404。"""
    _, token = await _seed_role_user(session, role)
    expected = 404 if Permission.APPROVE in DEFAULT_ROLE_PERMISSIONS[role] else 403
    async with _make_client(session) as c:
        resp = await c.post(f"/collab/{uuid.uuid4()}/merge", headers=_auth(token))
    assert resp.status_code == expected


async def test_unauthenticated_all_endpoints_reject(session):
    """匿名（无 token）访问受限端点 -> 401。"""
    endpoints = [
        ("GET", "/admin/users"),
        ("GET", "/admin/teams"),
        ("GET", "/library/profile-cards"),
        ("GET", "/admin/document-communities"),
        ("POST", "/query"),
    ]
    async with _make_client(session) as c:
        for method, path in endpoints:
            resp = await c.request(method, path, json={} if method == "POST" else None)
            assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"


async def test_clearance_isolation_in_library(session):
    """低 clearance 用户浏览不到高 access_level 数据（visible_to 后端唯一真相）。"""
    from calliodesmo.api import deps
    from calliodesmo.interfaces.graph_store import EntityRecord

    deps.reset_app_stores()
    # analyst clearance=INTERNAL，team scope
    await seed_default_roles(session)
    low_user = await create_user(
        session, username="low-clr", password="pw-123456", clearance=ClearanceLevel.INTERNAL
    )
    await assign_role(session, user=low_user, role_name="analyst", scope=LibraryScope.TEAM)
    await session.commit()
    settings = get_settings()
    token = create_access_token(
        subject=str(low_user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )
    # 灌一条 SECRET team-scope 实体（低 clearance 不可见）
    team_id = uuid.uuid4()
    stores = deps.get_app_stores()
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="秘密实体",
                type="org",
                description="confidential",
                access_level=ClearanceLevel.SECRET,
                library_scope=LibraryScope.TEAM,
                team_id=team_id,
            )
        ],
        [],
    )
    # 低 clearance 用户加入该 team（scope 命中但 clearance 不足）
    from calliodesmo.auth.service import add_team_member, create_team

    team = await create_team(session, name="隔离测试团队")
    await add_team_member(session, user=low_user, team=team)
    await session.commit()
    # 重新 seed store 用 team_id
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="秘密实体",
                type="org",
                description="confidential",
                access_level=ClearanceLevel.SECRET,
                library_scope=LibraryScope.TEAM,
                team_id=team.id,
            )
        ],
        [],
    )
    try:
        async with _make_client(session) as c:
            resp = await c.get("/library/entities/秘密实体", headers=_auth(token))
        # clearance INTERNAL < SECRET -> 404（不泄露存在性）
        assert resp.status_code == 404
    finally:
        deps.reset_app_stores()


async def test_role_permissions_match_default_matrix():
    """三角色权限与 DEFAULT_ROLE_PERMISSIONS 对齐（前后端一致性基线）。"""
    assert Permission.QUERY in DEFAULT_ROLE_PERMISSIONS["analyst"]
    assert Permission.QUERY in DEFAULT_ROLE_PERMISSIONS["reviewer"]
    assert Permission.QUERY in DEFAULT_ROLE_PERMISSIONS["admin"]
    assert Permission.MANAGE_USERS not in DEFAULT_ROLE_PERMISSIONS["analyst"]
    assert Permission.MANAGE_USERS not in DEFAULT_ROLE_PERMISSIONS["reviewer"]
    assert Permission.MANAGE_USERS in DEFAULT_ROLE_PERMISSIONS["admin"]
    assert Permission.MANAGE_COMMUNITY in DEFAULT_ROLE_PERMISSIONS["admin"]
    assert Permission.MANAGE_COMMUNITY not in DEFAULT_ROLE_PERMISSIONS["analyst"]
    # P6 Task 2（决策 1）：analyze 授予 analyst / reviewer / admin 三角色
    assert Permission.ANALYZE in DEFAULT_ROLE_PERMISSIONS["analyst"]
    assert Permission.ANALYZE in DEFAULT_ROLE_PERMISSIONS["reviewer"]
    assert Permission.ANALYZE in DEFAULT_ROLE_PERMISSIONS["admin"]
