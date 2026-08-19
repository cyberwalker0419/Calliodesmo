"""Task 6 Step 4：/collab 对齐复核端点 × 角色 × 状态码矩阵。"""

import uuid
from collections.abc import AsyncIterator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

import calliodesmo.models  # noqa: F401
from calliodesmo.api.deps import get_app_stores, reset_app_stores
from calliodesmo.auth.models import (
    ClearanceLevel,
    LibraryScope,
    Permission,
    Project,
    ProjectMember,
    Role,
    RolePermission,
    Team,
)
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import assign_role, create_user, seed_default_roles
from calliodesmo.config import get_settings
from calliodesmo.db.session import get_session
from calliodesmo.interfaces.graph_store import EntityRecord


def _pair(**kw):
    p = dict(
        pair_id="pair-a",
        source_name="OpenAI",
        target_name="OpenAI Inc",
        score=0.9,
        type="organization",
        source_type="organization",
        target_type="organization",
        source_description="AI 研究",
        target_description="AI 研究实验室",
    )
    p.update(kw)
    return p


async def _seed_actor(session, username, permissions, clearance=ClearanceLevel.SECRET):
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


async def _project(session, team=None) -> Project:
    team = team or Team(name=f"team-{uuid.uuid4().hex[:8]}", description="")
    session.add(team)
    await session.flush()
    project = Project(name=f"proj-{uuid.uuid4().hex[:8]}", description="", team_id=team.id)
    session.add(project)
    await session.flush()
    return project


async def _create_contribution(client, token, project_id) -> str:
    resp = await client.post(
        "/collab",
        json={
            "source_scope": "personal",
            "target_scope": "project",
            "target_project_id": str(project_id),
            "title": "推送",
            "doc_ids": ["d"],
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _seed_target_entity(session, reviewer, project_id):
    await session.commit()  # 让 reviewer 可见 project
    stores = get_app_stores()
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="OpenAI Inc",
                type="organization",
                description="AI 研究实验室",
                source_chunk_ids=["t#0"],
                library_scope=LibraryScope.PROJECT,
                owner_id=None,
                project_id=project_id,
            ),
        ],
        [],
    )


async def _set_manifest(session, cid, pairs):
    from calliodesmo.collab.models import Contribution

    c = await session.get(Contribution, cid)
    c.manifest = {"alignment_pending": pairs}
    await session.commit()


async def test_alignment_review_requires_approve(session):
    reset_app_stores()
    _, t_s = await _seed_actor(session, "src", {Permission.PUSH})
    _, t_a = await _seed_actor(session, "anlt", {Permission.PUSH})  # 无 APPROVE
    project_id = (await _project(session)).id
    async with _make_client(session) as c:
        cid = await _create_contribution(c, t_s, project_id)
        await _set_manifest(session, cid, [_pair()])
        resp = await c.get(f"/collab/{cid}/alignment-review", headers=_auth(t_a))
    assert resp.status_code == 403
    reset_app_stores()


async def test_alignment_review_flow(session):
    """reviewer：collect -> approve -> 待审清空 + 目标库并入；重复 approve 幂等。"""
    reset_app_stores()
    source, t_s = await _seed_actor(session, "src2", {Permission.PUSH})
    reviewer, t_r = await _seed_actor(session, "rev2", {Permission.PUSH, Permission.APPROVE})
    team = Team(name=f"t-{uuid.uuid4().hex[:6]}", description="")
    session.add(team)
    await session.flush()
    project = Project(name=f"p-{uuid.uuid4().hex[:6]}", description="", team_id=team.id)
    session.add(project)
    reviewer_role = Role(name=f"rev-{uuid.uuid4().hex[:6]}", description="")
    session.add(reviewer_role)
    await session.flush()
    session.add(RolePermission(role_id=reviewer_role.id, permission=Permission.APPROVE))
    session.add(ProjectMember(user_id=reviewer.id, project_id=project.id, role_id=reviewer_role.id))
    await session.commit()
    stores = get_app_stores()
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="OpenAI",
                type="organization",
                description="AI 研究",
                source_chunk_ids=["d#0"],
                library_scope=LibraryScope.PERSONAL,
                owner_id=source.id,
            ),
        ],
        [],
    )
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="OpenAI Inc",
                type="organization",
                description="AI 研究实验室",
                source_chunk_ids=["t#0"],
                library_scope=LibraryScope.PROJECT,
                owner_id=None,
                project_id=project.id,
            ),
        ],
        [],
    )
    async with _make_client(session) as c:
        cid = await _create_contribution(c, t_s, project.id)
        await _set_manifest(session, cid, [_pair()])
        # collect
        resp = await c.get(f"/collab/{cid}/alignment-review", headers=_auth(t_r))
        assert resp.status_code == 200, resp.text
        assert len(resp.json()) == 1
        assert resp.json()[0]["source_name"] == "OpenAI"
        # approve
        resp = await c.post(
            f"/collab/{cid}/alignment-review/approve",
            json={"pair_id": "pair-a"},
            headers=_auth(t_r),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "approved"
        # 待审清空
        resp = await c.get(f"/collab/{cid}/alignment-review", headers=_auth(t_r))
        assert resp.json() == []
        # 目标库并入
        ent = stores.graph_store._entities.get("OpenAI Inc")
        assert ent is not None
        assert ent.metadata["merge_decision"] == "auto_merged"
        assert ent.source_chunk_ids == ["t#0", "d#0"]
        # 重复 approve 幂等
        resp = await c.post(
            f"/collab/{cid}/alignment-review/approve",
            json={"pair_id": "pair-a"},
            headers=_auth(t_r),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
    reset_app_stores()


async def test_alignment_review_self_review_blocked(session):
    reset_app_stores()
    _, t_s = await _seed_actor(session, "src3", {Permission.PUSH, Permission.APPROVE})
    project_id = (await _project(session)).id
    async with _make_client(session) as c:
        cid = await _create_contribution(c, t_s, project_id)
        await _set_manifest(session, cid, [_pair()])
        resp = await c.post(
            f"/collab/{cid}/alignment-review/approve",
            json={"pair_id": "pair-a"},
            headers=_auth(t_s),
        )
    assert resp.status_code == 403
    assert "自审" in resp.json()["detail"]
    reset_app_stores()


async def test_alignment_review_reject_and_unknown(session):
    reset_app_stores()
    _, t_s = await _seed_actor(session, "src4", {Permission.PUSH})
    reviewer, t_r = await _seed_actor(session, "rev4", {Permission.PUSH, Permission.APPROVE})
    project_id = (await _project(session)).id
    reviewer_role = Role(name=f"rr-{uuid.uuid4().hex[:6]}", description="")
    session.add(reviewer_role)
    await session.flush()
    session.add(RolePermission(role_id=reviewer_role.id, permission=Permission.APPROVE))
    session.add(ProjectMember(user_id=reviewer.id, project_id=project_id, role_id=reviewer_role.id))
    await session.commit()
    async with _make_client(session) as c:
        cid = await _create_contribution(c, t_s, project_id)
        await _set_manifest(session, cid, [_pair()])
        # reject
        resp = await c.post(
            f"/collab/{cid}/alignment-review/reject",
            json={"pair_id": "pair-a"},
            headers=_auth(t_r),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "rejected"
        # 待审清空
        resp = await c.get(f"/collab/{cid}/alignment-review", headers=_auth(t_r))
        assert resp.json() == []
        # 未知 pair -> 404
        resp = await c.post(
            f"/collab/{cid}/alignment-review/approve",
            json={"pair_id": "nope"},
            headers=_auth(t_r),
        )
        assert resp.status_code == 404
    reset_app_stores()


async def test_diff_returns_alignment_pending(session):
    """manifest 带 alignment_pending 时 diff 返回待审对。"""
    reset_app_stores()
    _, t_s = await _seed_actor(session, "src5", {Permission.PUSH})
    reviewer, t_r = await _seed_actor(session, "rev5", {Permission.PUSH, Permission.APPROVE})
    project_id = (await _project(session)).id
    reviewer_role = Role(name=f"rr5-{uuid.uuid4().hex[:6]}", description="")
    session.add(reviewer_role)
    await session.flush()
    session.add(RolePermission(role_id=reviewer_role.id, permission=Permission.APPROVE))
    session.add(ProjectMember(user_id=reviewer.id, project_id=project_id, role_id=reviewer_role.id))
    await session.commit()
    async with _make_client(session) as c:
        cid = await _create_contribution(c, t_s, project_id)
        await _set_manifest(session, cid, [_pair()])
        resp = await c.get(f"/collab/{cid}/diff", headers=_auth(t_r))
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["alignment_pending"]) == 1
        assert resp.json()["alignment_pending"][0]["source_name"] == "OpenAI"
    reset_app_stores()
