"""P3 Task 1：/library 只读浏览端点（visible_to 过滤 + query 守卫 + stores 单例）。"""

import uuid
from collections.abc import AsyncIterator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

import calliodesmo.models  # noqa: F401
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
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.interfaces.profile_card import ProfileCard


async def _seed_actor(
    session: AsyncSession,
    username: str,
    permissions: set[Permission],
    clearance: ClearanceLevel = ClearanceLevel.SECRET,
):
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


async def _seed_stores(owner_id: uuid.UUID):
    """往内存 stores 单例灌两种可见性数据：owner 个人库 INTERNAL + 他人个人库 PUBLIC。"""
    from calliodesmo.api.deps import get_app_stores

    stores = get_app_stores()
    other_id = uuid.uuid4()
    await stores.profile_card_store.upsert(
        [
            ProfileCard(
                entity_name="张三",
                entity_type="person",
                aliases=[],
                role=None,
                organization=None,
                associates=[],
                timespan=None,
                description="本人库卡片",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner_id,
            ),
            ProfileCard(
                entity_name="李四",
                entity_type="person",
                aliases=[],
                role=None,
                organization=None,
                associates=[],
                timespan=None,
                description="他人库卡片",
                access_level=ClearanceLevel.PUBLIC,
                library_scope=LibraryScope.PERSONAL,
                owner_id=other_id,
            ),
        ]
    )
    await stores.community_store.upsert_communities(
        [
            CommunityRecord(
                community_id="c-l0",
                level=0,
                title="实体社区",
                summary="s",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner_id,
            ),
            CommunityRecord(
                community_id="c-l1",
                level=1,
                title="文档社区",
                summary="s",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner_id,
            ),
        ]
    )
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="张三",
                type="person",
                description="本人库实体",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner_id,
            ),
            EntityRecord(
                name="王五",
                type="person",
                description="邻居实体",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner_id,
            ),
            EntityRecord(
                name="秘密实体",
                type="org",
                description="越权实体",
                access_level=ClearanceLevel.SECRET,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner_id,
            ),
        ],
        [
            RelationRecord(
                source="张三",
                target="王五",
                type="knows",
                description="认识",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner_id,
            )
        ],
    )
    return stores


async def test_profile_cards_filtered_by_visibility(session):
    from calliodesmo.api import deps

    deps.reset_app_stores()
    user, token = await _seed_actor(session, "browser", {Permission.QUERY})
    await _seed_stores(user.id)
    try:
        async with _make_client(session) as c:
            resp = await c.get("/library/profile-cards", headers=_auth(token))
        assert resp.status_code == 200
        names = {card["entity_name"] for card in resp.json()}
        assert names == {"张三"}  # 他人个人库卡片不可见
        card = resp.json()[0]
        assert card["description"] == "本人库卡片"
        assert card["access_level"] == "INTERNAL"
        assert card["library_scope"] == "personal"
    finally:
        deps.reset_app_stores()


async def test_profile_cards_requires_query_permission(session):
    from calliodesmo.api import deps

    deps.reset_app_stores()
    _, token = await _seed_actor(session, "no-query", {Permission.INGEST})
    try:
        async with _make_client(session) as c:
            resp = await c.get("/library/profile-cards", headers=_auth(token))
        assert resp.status_code == 403
    finally:
        deps.reset_app_stores()


async def test_communities_level_filter(session):
    from calliodesmo.api import deps

    deps.reset_app_stores()
    user, token = await _seed_actor(session, "comm-browser", {Permission.QUERY})
    await _seed_stores(user.id)
    try:
        async with _make_client(session) as c:
            all_resp = await c.get("/library/communities", headers=_auth(token))
            assert all_resp.status_code == 200
            assert len(all_resp.json()) == 2
            l1 = await c.get("/library/communities?level=1", headers=_auth(token))
            assert [c["community_id"] for c in l1.json()] == ["c-l1"]
    finally:
        deps.reset_app_stores()


async def test_entity_detail_with_neighbors(session):
    from calliodesmo.api import deps

    deps.reset_app_stores()
    user, token = await _seed_actor(session, "entity-browser", {Permission.QUERY})
    await _seed_stores(user.id)
    try:
        async with _make_client(session) as c:
            resp = await c.get("/library/entities/张三", headers=_auth(token))
            assert resp.status_code == 200
            body = resp.json()
            assert body["name"] == "张三"
            assert body["type"] == "person"
            neighbor_names = {n["name"] for n in body["neighbors"]}
            assert neighbor_names == {"王五"}
            assert body["relations"][0]["type"] == "knows"
            # 越权实体（SECRET 他人不可见——当前用户 SECRET 但 owner 是本人，
            # 用低 clearance 用户验证）
    finally:
        deps.reset_app_stores()


async def test_entity_invisible_when_clearance_insufficient(session):
    from calliodesmo.api import deps

    deps.reset_app_stores()
    owner, _ = await _seed_actor(session, "owner-user", {Permission.QUERY})
    _, low_token = await _seed_actor(
        session, "low-clearance", {Permission.QUERY}, clearance=ClearanceLevel.INTERNAL
    )
    await _seed_stores(owner.id)
    try:
        async with _make_client(session) as c:
            # 低 clearance 用户查 SECRET 实体 -> 404（不泄露存在性）
            resp = await c.get("/library/entities/秘密实体", headers=_auth(low_token))
            assert resp.status_code == 404
            # 本人个人库对他人不可见
            resp2 = await c.get("/library/entities/张三", headers=_auth(low_token))
            assert resp2.status_code == 404
    finally:
        deps.reset_app_stores()


async def test_store_factories_share_singletons(session, monkeypatch):
    """stores 依赖工厂：get_*_store 与 get_search_engine 共享同一实例。"""
    from calliodesmo.api import deps
    from calliodesmo.config import get_settings

    monkeypatch.setenv("CALLIODESMO_LLM_MODEL", "test/stub")
    monkeypatch.setenv("CALLIODESMO_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("CALLIODESMO_EMBEDDING_DIMENSION", "64")
    get_settings.cache_clear()
    deps.reset_app_stores()
    try:
        s1 = await deps.get_profile_card_store()
        s2 = await deps.get_profile_card_store()
        assert s1 is s2
        graph = await deps.get_graph_store()
        engine = await deps.get_search_engine()
        # 引擎的 local retriever 持有同一 graph store 单例
        assert engine._local_retriever._graph_store is graph
        comm = await deps.get_community_store()
        assert engine._global_retriever._community_store is comm
    finally:
        deps.reset_app_stores()
        get_settings.cache_clear()
