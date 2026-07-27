"""P3 Task 5 Step 10：ScopeSwitcher 后端--/library 列表与子图按 scope 过滤。

验证 scope 查询参能按库范围（personal/project/team）收窄结果，且无效值 422。
权限仍由 visible_to 兜底（后端唯一真相），scope 仅做视图层收窄。
"""

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
from calliodesmo.auth.service import (
    add_team_member,
    assign_role,
    create_team,
    create_user,
    seed_default_roles,
)
from calliodesmo.config import get_settings
from calliodesmo.db.session import get_session
from calliodesmo.interfaces.community_store import CommunityRecord
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.interfaces.profile_card import ProfileCard


async def _seed_team_member(
    session: AsyncSession,
    username: str,
    clearance: ClearanceLevel = ClearanceLevel.SECRET,
):
    """建一个有团队会员身份的查询用户：个人库 + 团队库均可见。"""
    await seed_default_roles(session)
    role = Role(name=f"role-{username}", description="test")
    session.add(role)
    await session.flush()
    session.add(RolePermission(role_id=role.id, permission=Permission.QUERY))
    user = await create_user(session, username=username, password="pw-123456", clearance=clearance)
    team = await create_team(session, name=f"team-{username}", description="t")
    await add_team_member(session, user=user, team=team, role_in_team="member")
    await assign_role(session, user=user, role_name=f"role-{username}", scope=LibraryScope.TEAM)
    await session.commit()
    settings = get_settings()
    token = create_access_token(
        subject=str(user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )
    return user, team, token


def _make_client(session: AsyncSession) -> httpx.AsyncClient:
    from calliodesmo.api.app import create_app

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_mixed_scope_stores(owner_id: uuid.UUID, team_id: uuid.UUID):
    """灌个人库 + 团队库各一份档案卡 / 社区 / 实体，供 scope 收窄验证。"""
    from calliodesmo.api.deps import get_app_stores

    stores = get_app_stores()
    await stores.profile_card_store.upsert(
        [
            ProfileCard(
                entity_name="个人卡",
                entity_type="person",
                aliases=[],
                role=None,
                organization=None,
                associates=[],
                timespan=None,
                description="个人库档案卡",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner_id,
            ),
            ProfileCard(
                entity_name="团队卡",
                entity_type="organization",
                aliases=[],
                role=None,
                organization=None,
                associates=[],
                timespan=None,
                description="团队库档案卡",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.TEAM,
                owner_id=owner_id,
                team_id=team_id,
            ),
        ]
    )
    await stores.community_store.upsert_communities(
        [
            CommunityRecord(
                community_id="comm-personal",
                level=1,
                title="个人文档社区",
                summary="s",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner_id,
            ),
            CommunityRecord(
                community_id="comm-team",
                level=1,
                title="团队文档社区",
                summary="s",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.TEAM,
                owner_id=owner_id,
                team_id=team_id,
            ),
        ]
    )
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="个人卡",
                type="person",
                description="个人库实体",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner_id,
            ),
            EntityRecord(
                name="团队卡",
                type="organization",
                description="团队库实体",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.TEAM,
                owner_id=owner_id,
                team_id=team_id,
            ),
        ],
        [
            RelationRecord(
                source="个人卡",
                target="团队卡",
                type="knows",
                description="跨库关系",
                access_level=ClearanceLevel.INTERNAL,
                library_scope=LibraryScope.PERSONAL,
                owner_id=owner_id,
            ),
        ],
    )
    return stores


async def test_profile_cards_scope_filter(session):
    from calliodesmo.api import deps

    deps.reset_app_stores()
    user, team, token = await _seed_team_member(session, "scope-browser")
    await _seed_mixed_scope_stores(user.id, team.id)
    try:
        async with _make_client(session) as c:
            all_resp = await c.get("/library/profile-cards", headers=_auth(token))
            assert all_resp.status_code == 200
            assert {x["entity_name"] for x in all_resp.json()} == {"个人卡", "团队卡"}

            personal = await c.get("/library/profile-cards?scope=personal", headers=_auth(token))
            assert {x["entity_name"] for x in personal.json()} == {"个人卡"}

            team_cards = await c.get("/library/profile-cards?scope=team", headers=_auth(token))
            assert {x["entity_name"] for x in team_cards.json()} == {"团队卡"}

            invalid = await c.get("/library/profile-cards?scope=nope", headers=_auth(token))
            assert invalid.status_code == 422
    finally:
        deps.reset_app_stores()


async def test_communities_scope_filter(session):
    from calliodesmo.api import deps

    deps.reset_app_stores()
    user, team, token = await _seed_team_member(session, "comm-scope")
    await _seed_mixed_scope_stores(user.id, team.id)
    try:
        async with _make_client(session) as c:
            team_resp = await c.get("/library/communities?scope=team", headers=_auth(token))
            assert team_resp.status_code == 200
            assert {x["community_id"] for x in team_resp.json()} == {"comm-team"}

            personal_resp = await c.get("/library/communities?scope=personal", headers=_auth(token))
            assert {x["community_id"] for x in personal_resp.json()} == {"comm-personal"}
    finally:
        deps.reset_app_stores()


async def test_subgraph_scope_filter(session):
    from calliodesmo.api import deps

    deps.reset_app_stores()
    user, team, token = await _seed_team_member(session, "sub-scope")
    await _seed_mixed_scope_stores(user.id, team.id)
    try:
        async with _make_client(session) as c:
            # 不过滤：种子=个人卡，BFS 扩到团队卡，含跨库边 -> 两节点一边
            all_resp = await c.get(
                "/library/subgraph",
                params={"seeds": "个人卡", "hops": 1, "limit": 50},
                headers=_auth(token),
            )
            assert all_resp.status_code == 200
            assert {n["name"] for n in all_resp.json()["nodes"]} == {"个人卡", "团队卡"}
            assert len(all_resp.json()["edges"]) == 1

            # scope=team：个人卡（personal）被滤掉，跨库边因端点缺失也被滤
            team_resp = await c.get(
                "/library/subgraph",
                params={"seeds": "个人卡", "hops": 1, "limit": 50, "scope": "team"},
                headers=_auth(token),
            )
            assert team_resp.status_code == 200
            assert {n["name"] for n in team_resp.json()["nodes"]} == {"团队卡"}
            assert team_resp.json()["edges"] == []
    finally:
        deps.reset_app_stores()
