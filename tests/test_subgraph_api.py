"""P3 Task 5 Step 4：GET /library/subgraph 增量子图端点测试。"""

from collections.abc import AsyncIterator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

import calliodesmo.models  # noqa: F401
from calliodesmo.api import deps
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
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord


async def _seed(session):
    await seed_default_roles(session)
    role = Role(name="subgraph-role", description="t")
    session.add(role)
    await session.flush()
    session.add(RolePermission(role_id=role.id, permission=Permission.QUERY))
    user = await create_user(
        session, username="sg-user", password="pw-123456", clearance=ClearanceLevel.SECRET
    )
    await assign_role(session, user=user, role_name="subgraph-role", scope=LibraryScope.TEAM)
    await session.commit()
    s = get_settings()
    token = create_access_token(
        subject=str(user.id),
        secret_key=s.jwt_secret_key,
        algorithm=s.jwt_algorithm,
        expires_minutes=60,
    )
    return user.id, token


def _make_client(session):
    from calliodesmo.api.app import create_app

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_graph(owner_id):
    stores = deps.get_app_stores()
    # 链式图：A-B-C-D（A 为种子，hops=2 覆盖 A,B,C）
    recs = [
        EntityRecord(
            name=n,
            type="person",
            description=f"节点 {n}",
            access_level=ClearanceLevel.INTERNAL,
            library_scope=LibraryScope.PERSONAL,
            owner_id=owner_id,
        )
        for n in ("A", "B", "C", "D", "E")
    ]
    rels = [
        RelationRecord(
            source=s,
            target=t,
            type="knows",
            description="",
            access_level=ClearanceLevel.INTERNAL,
            library_scope=LibraryScope.PERSONAL,
            owner_id=owner_id,
        )
        for s, t in [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")]
    ]
    return stores, recs, rels


async def test_subgraph_basic_expansion(session):
    deps.reset_app_stores()
    user_id, token = await _seed(session)
    stores, recs, rels = _seed_graph(user_id)
    await stores.graph_store.upsert_graph(recs, rels)
    try:
        async with _make_client(session) as c:
            resp = await c.get(
                "/library/subgraph",
                params={"seeds": "A", "hops": 1, "limit": 50},
                headers=_auth(token),
            )
        assert resp.status_code == 200
        data = resp.json()
        names = {n["name"] for n in data["nodes"]}
        assert names == {"A", "B"}  # hops=1
        assert data["expanded_seeds"] == ["A"]
        assert data["truncated"] is False
        assert any(e["source"] == "A" and e["target"] == "B" for e in data["edges"])
    finally:
        deps.reset_app_stores()


async def test_subgraph_hops_two(session):
    deps.reset_app_stores()
    user_id, token = await _seed(session)
    stores, recs, rels = _seed_graph(user_id)
    await stores.graph_store.upsert_graph(recs, rels)
    try:
        async with _make_client(session) as c:
            resp = await c.get(
                "/library/subgraph",
                params={"seeds": "A", "hops": 2, "limit": 50},
                headers=_auth(token),
            )
        names = {n["name"] for n in resp.json()["nodes"]}
        assert names == {"A", "B", "C"}  # hops=2 覆盖 A-B-C
    finally:
        deps.reset_app_stores()


async def test_subgraph_truncation_at_limit(session):
    deps.reset_app_stores()
    user_id, token = await _seed(session)
    stores, recs, rels = _seed_graph(user_id)
    await stores.graph_store.upsert_graph(recs, rels)
    try:
        async with _make_client(session) as c:
            resp = await c.get(
                "/library/subgraph",
                params={"seeds": "A", "hops": 5, "limit": 3},
                headers=_auth(token),
            )
        data = resp.json()
        assert data["truncated"] is True
        assert len(data["nodes"]) == 3
    finally:
        deps.reset_app_stores()


async def test_subgraph_multiple_seeds(session):
    deps.reset_app_stores()
    user_id, token = await _seed(session)
    stores, recs, rels = _seed_graph(user_id)
    await stores.graph_store.upsert_graph(recs, rels)
    try:
        async with _make_client(session) as c:
            resp = await c.get(
                "/library/subgraph",
                params={"seeds": "A,E", "hops": 1, "limit": 50},
                headers=_auth(token),
            )
        names = {n["name"] for n in resp.json()["nodes"]}
        assert names == {"A", "B", "D", "E"}  # A->B, E->D
    finally:
        deps.reset_app_stores()


async def test_subgraph_requires_query_permission(session):
    deps.reset_app_stores()
    # 用无 QUERY 权限的角色
    await seed_default_roles(session)
    role = Role(name="no-query", description="t")
    session.add(role)
    await session.flush()
    session.add(RolePermission(role_id=role.id, permission=Permission.INGEST))
    user = await create_user(session, username="nq", password="pw-123456")
    await assign_role(session, user=user, role_name="no-query", scope=LibraryScope.TEAM)
    await session.commit()
    s = get_settings()
    token = create_access_token(
        subject=str(user.id),
        secret_key=s.jwt_secret_key,
        algorithm=s.jwt_algorithm,
        expires_minutes=60,
    )
    try:
        async with _make_client(session) as c:
            resp = await c.get("/library/subgraph", params={"seeds": "A"}, headers=_auth(token))
        assert resp.status_code == 403
    finally:
        deps.reset_app_stores()


async def test_subgraph_empty_seeds_rejected(session):
    deps.reset_app_stores()
    _, token = await _seed(session)
    try:
        async with _make_client(session) as c:
            resp = await c.get("/library/subgraph", params={"seeds": ""}, headers=_auth(token))
        assert resp.status_code == 422
    finally:
        deps.reset_app_stores()


async def test_subgraph_case_insensitive_seed(session):
    """档案卡展示名（小写）与图库原始名（混合大小写）不一时，按大小写不敏感命中。"""
    deps.reset_app_stores()
    user_id, token = await _seed(session)
    stores = deps.get_app_stores()
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="Mixed Case Entity",
                type="person",
                description="混合大小写名",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            ),
            EntityRecord(
                name="Other",
                type="person",
                description="邻居",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            ),
        ],
        [
            RelationRecord(
                source="Mixed Case Entity",
                target="Other",
                type="knows",
                description="",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=user_id,
            ),
        ],
    )
    try:
        async with _make_client(session) as c:
            # 用小写名查实体详情（图库存的是混合大小写）
            ent = await c.get("/library/entities/mixed case entity", headers=_auth(token))
            assert ent.status_code == 200
            assert ent.json()["name"] == "Mixed Case Entity"
            # neighbors 也应命中（用解析后的实体名匹配关系端点）
            assert any(n["name"] == "Other" for n in ent.json()["neighbors"])
            # 用小写名拉子图 -> 命中并展开邻居
            resp = await c.get(
                "/library/subgraph",
                params={"seeds": "mixed case entity", "hops": 1, "limit": 50},
                headers=_auth(token),
            )
            assert resp.status_code == 200
            names = {n["name"] for n in resp.json()["nodes"]}
            assert names == {"Mixed Case Entity", "Other"}
            assert resp.json()["expanded_seeds"] == ["Mixed Case Entity"]
    finally:
        deps.reset_app_stores()
