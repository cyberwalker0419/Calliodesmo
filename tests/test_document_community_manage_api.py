"""P3 Task 7：文档社区手动管理 API + CommunityStore 手动操作 + 自动派生不覆盖手改。"""

import uuid
from collections.abc import AsyncIterator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

import calliodesmo.models  # noqa: F401
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
from calliodesmo.interfaces.community_store import CommunityRecord
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore


async def _seed_actor(session, username, permissions):
    await seed_default_roles(session)
    role = Role(name=f"role-{username}", description="t")
    session.add(role)
    await session.flush()
    for p in permissions:
        session.add(RolePermission(role_id=role.id, permission=p))
    user = await create_user(
        session, username=username, password="pw-123456", clearance=ClearanceLevel.SECRET
    )
    await assign_role(session, user=user, role_name=f"role-{username}", scope=LibraryScope.TEAM)
    await session.commit()
    s = get_settings()
    token = create_access_token(
        subject=str(user.id),
        secret_key=s.jwt_secret_key,
        algorithm=s.jwt_algorithm,
        expires_minutes=60,
    )
    return user, token


def _make_client(session):
    from calliodesmo.api.app import create_app

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---- CommunityStore 手动操作（store 层）----


async def test_community_store_manual_rename_and_access():
    from calliodesmo.api import deps

    deps.reset_app_stores()
    try:
        store = InMemoryCommunityStore()
        owner = uuid.uuid4()
        await store.upsert_communities(
            [
                CommunityRecord(
                    community_id="doc-1",
                    level=1,
                    title="原标题",
                    summary="s",
                    access_level=ClearanceLevel.INTERNAL,
                    library_scope=LibraryScope.PERSONAL,
                    owner_id=owner,
                )
            ]
        )
        ctx = AccessContext(
            user_id=owner,
            username="u",
            clearance=ClearanceLevel.SECRET,
            permissions=frozenset({Permission.MANAGE_COMMUNITY}),
        )
        await store.rename("doc-1", "新标题", access=ctx)
        await store.set_access_level("doc-1", ClearanceLevel.CONFIDENTIAL, access=ctx)
        rec = store._records["doc-1"]
        assert rec.title == "新标题"
        assert rec.access_level == ClearanceLevel.CONFIDENTIAL
        assert rec.metadata.get("manual") is True
    finally:
        deps.reset_app_stores()


async def test_community_store_rename_invisible_to_user():
    store = InMemoryCommunityStore()
    other = uuid.uuid4()
    await store.upsert_communities(
        [
            CommunityRecord(
                community_id="doc-x",
                level=1,
                title="t",
                summary="s",
                access_level=ClearanceLevel.SECRET,
                library_scope=LibraryScope.PERSONAL,
                owner_id=other,
            )
        ]
    )
    ctx = AccessContext(
        user_id=uuid.uuid4(),
        username="u",
        clearance=ClearanceLevel.INTERNAL,
        permissions=frozenset({Permission.MANAGE_COMMUNITY}),
    )
    # 越权社区不可改 -> 返回 False
    assert await store.rename("doc-x", "hacked", access=ctx) is False
    assert store._records["doc-x"].title == "t"


# ---- API 端点 ----


async def _seed_doc_community_in_stores(owner_id):
    from calliodesmo.api.deps import get_app_stores

    stores = get_app_stores()
    await stores.community_store.upsert_communities(
        [
            CommunityRecord(
                community_id="doc-demo",
                level=1,
                title="自动派生标题",
                summary="s",
                member_entity_names=["OpenAI"],
                metadata={"doc_id": "demo"},
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner_id,
            ),
            CommunityRecord(
                community_id="comm-0",
                level=0,
                title="实体社区",
                summary="s",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner_id,
            ),
        ]
    )
    return stores


async def test_list_document_communities(session):
    from calliodesmo.api import deps

    deps.reset_app_stores()
    user, token = await _seed_actor(
        session, "admin-comm", {Permission.MANAGE_COMMUNITY, Permission.QUERY}
    )
    await _seed_doc_community_in_stores(user.id)
    try:
        async with _make_client(session) as c:
            resp = await c.get("/admin/document-communities", headers=_auth(token))
            assert resp.status_code == 200
            ids = [x["community_id"] for x in resp.json()]
            assert ids == ["doc-demo"]  # 仅 level=1 文档社区
    finally:
        deps.reset_app_stores()


async def test_rename_via_api(session):
    from sqlalchemy import select

    from calliodesmo.api import deps
    from calliodesmo.audit.models import AuditLog

    deps.reset_app_stores()
    user, token = await _seed_actor(
        session, "admin-rename", {Permission.MANAGE_COMMUNITY, Permission.QUERY}
    )
    await _seed_doc_community_in_stores(user.id)
    try:
        async with _make_client(session) as c:
            resp = await c.patch(
                "/admin/document-communities/doc-demo",
                json={"title": "手动命名标题"},
                headers=_auth(token),
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["title"] == "手动命名标题"
        logs = (
            (await session.execute(select(AuditLog).where(AuditLog.action == "manage_community")))
            .scalars()
            .all()
        )
        assert any(log.detail.get("op") == "rename" for log in logs)
    finally:
        deps.reset_app_stores()


async def test_set_access_via_api(session):
    from calliodesmo.api import deps

    deps.reset_app_stores()
    user, token = await _seed_actor(
        session, "admin-access", {Permission.MANAGE_COMMUNITY, Permission.QUERY}
    )
    await _seed_doc_community_in_stores(user.id)
    try:
        async with _make_client(session) as c:
            resp = await c.patch(
                "/admin/document-communities/doc-demo",
                json={"access_level": "CONFIDENTIAL"},
                headers=_auth(token),
            )
            assert resp.status_code == 200
            assert resp.json()["access_level"] == "CONFIDENTIAL"
    finally:
        deps.reset_app_stores()


async def test_manage_community_guard(session):
    from calliodesmo.api import deps

    deps.reset_app_stores()
    user, token = await _seed_actor(session, "analyst-nocomm", {Permission.QUERY})
    await _seed_doc_community_in_stores(user.id)
    try:
        async with _make_client(session) as c:
            resp = await c.get("/admin/document-communities", headers=_auth(token))
            assert resp.status_code == 403
    finally:
        deps.reset_app_stores()
