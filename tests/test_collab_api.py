"""Task 5：/collab 端点 × 角色 × 状态码矩阵。"""

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
from calliodesmo.auth.service import (
    assign_role,
    create_user,
    seed_default_roles,
)
from calliodesmo.config import get_settings
from calliodesmo.db.session import get_session
from calliodesmo.interfaces.graph_store import EntityRecord
from calliodesmo.interfaces.vector_store import ChunkRecord


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


async def _project(session) -> Project:
    """建真实 Team+Project（PG 强制 FK，Contribution.target_project_id 须引用已存在行）。"""
    team = Team(name=f"team-{uuid.uuid4().hex[:8]}", description="")
    session.add(team)
    await session.flush()
    project = Project(name=f"proj-{uuid.uuid4().hex[:8]}", description="", team_id=team.id)
    session.add(project)
    await session.flush()
    return project


def _create_body(target_project_id=None):
    return {
        "source_scope": "personal",
        "target_scope": "project",
        "target_project_id": str(target_project_id) if target_project_id else None,
        "title": "推送",
        "doc_ids": ["d"],
        "description": "",
    }


async def test_create_requires_auth(session):
    async with _make_client(session) as c:
        resp = await c.post("/collab", json=_create_body(uuid.uuid4()))
    assert resp.status_code == 401


async def test_create_push_guard(session):
    """有 PUSH 建 201；无 PUSH 403。"""
    _, t_a = await _seed_actor(session, "analyst", {Permission.PUSH})
    _, t_r = await _seed_actor(session, "reviewer", {Permission.PUSH, Permission.APPROVE})
    _, t_n = await _seed_actor(session, "noperm", {Permission.QUERY})
    pid = (await _project(session)).id
    async with _make_client(session) as c:
        assert (
            await c.post("/collab", json=_create_body(pid), headers=_auth(t_a))
        ).status_code == 201
        assert (
            await c.post("/collab", json=_create_body(pid), headers=_auth(t_r))
        ).status_code == 201
        assert (
            await c.post("/collab", json=_create_body(pid), headers=_auth(t_n))
        ).status_code == 403


async def test_create_invalid_scope_direction(session):
    """降向推送 400。"""
    _, t = await _seed_actor(session, "analyst2", {Permission.PUSH})
    async with _make_client(session) as c:
        body = {"source_scope": "project", "target_scope": "personal", "title": "x", "doc_ids": []}
        resp = await c.post("/collab", json=body, headers=_auth(t))
    assert resp.status_code == 400


async def test_submit_flow(session):
    _, t = await _seed_actor(session, "analyst3", {Permission.PUSH})
    pid = (await _project(session)).id
    async with _make_client(session) as c:
        r = await c.post("/collab", json=_create_body(pid), headers=_auth(t))
        cid = r.json()["id"]
        resp = await c.post(f"/collab/{cid}/submit", headers=_auth(t))
    assert resp.status_code == 200
    assert resp.json()["status"] == "submitted"


async def test_approve_guard_and_self_review(session):
    """reviewer（APPROVE）可 approve；analyst 403；源用户自审 403。"""
    _, t_s = await _seed_actor(session, "src", {Permission.PUSH})
    _, t_r = await _seed_actor(session, "rev", {Permission.PUSH, Permission.APPROVE})
    _, t_a = await _seed_actor(session, "analyst4", {Permission.PUSH})
    pid = (await _project(session)).id
    async with _make_client(session) as c:
        r = await c.post("/collab", json=_create_body(pid), headers=_auth(t_s))
        cid = r.json()["id"]
        await c.post(f"/collab/{cid}/submit", headers=_auth(t_s))
        assert (await c.post(f"/collab/{cid}/approve", headers=_auth(t_a))).status_code == 403
        assert (await c.post(f"/collab/{cid}/approve", headers=_auth(t_s))).status_code == 403
        resp = await c.post(f"/collab/{cid}/approve", headers=_auth(t_r))
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


async def test_reject_with_reason(session):
    _, t_s = await _seed_actor(session, "src2", {Permission.PUSH})
    _, t_r = await _seed_actor(session, "rev2", {Permission.PUSH, Permission.APPROVE})
    pid = (await _project(session)).id
    async with _make_client(session) as c:
        r = await c.post("/collab", json=_create_body(pid), headers=_auth(t_s))
        cid = r.json()["id"]
        await c.post(f"/collab/{cid}/submit", headers=_auth(t_s))
        resp = await c.post(
            f"/collab/{cid}/reject", json={"reason": "证据不足"}, headers=_auth(t_r)
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


async def test_get_invisible_404(session):
    """别人看不到源用户的贡献 -> 404。"""
    _, t_s = await _seed_actor(session, "src3", {Permission.PUSH})
    _, t_o = await _seed_actor(session, "other", {Permission.PUSH})
    pid = (await _project(session)).id
    async with _make_client(session) as c:
        r = await c.post("/collab", json=_create_body(pid), headers=_auth(t_s))
        cid = r.json()["id"]
        resp = await c.get(f"/collab/{cid}", headers=_auth(t_o))
    assert resp.status_code == 404


async def test_merge_flow(session):
    """reviewer merge：stores 灌源数据，合并后 status MERGED + 目标 scope 可见。"""
    reset_app_stores()
    stores = get_app_stores()
    source, t_s = await _seed_actor(session, "msrc", {Permission.PUSH})
    reviewer, t_r = await _seed_actor(session, "mrev", {Permission.PUSH, Permission.APPROVE})
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
    await stores.vector_store.upsert_chunks(
        [
            ChunkRecord(
                chunk_id="d#0",
                doc_id="d",
                content="c",
                vector=[1.0],
                library_scope=LibraryScope.PERSONAL,
                owner_id=source.id,
            ),
        ]
    )
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="OpenAI",
                type="organization",
                description="",
                source_chunk_ids=["d#0"],
                library_scope=LibraryScope.PERSONAL,
                owner_id=source.id,
            ),
        ],
        [],
    )
    assert "OpenAI" in stores.graph_store._entities  # 源数据在 store
    async with _make_client(session) as c:
        r = await c.post("/collab", json=_create_body(project.id), headers=_auth(t_s))
        cid = r.json()["id"]
        await c.post(f"/collab/{cid}/submit", headers=_auth(t_s))
        await c.post(f"/collab/{cid}/approve", headers=_auth(t_r))
        resp = await c.post(f"/collab/{cid}/merge", headers=_auth(t_r))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "merged"
    ent = stores.graph_store._entities.get("OpenAI")
    assert ent is not None, list(stores.graph_store._entities)
    assert ent.library_scope == LibraryScope.PROJECT, ent.library_scope
    reset_app_stores()


async def test_template_types_endpoints(session, monkeypatch, tmp_path):
    """GET /collab/template-types + POST .../approve（approve 守卫 + 写回 YAML）。"""
    from calliodesmo.config import get_settings
    from calliodesmo.ecl.extraction_template import ExtractionTemplateRegistry

    yaml_path = tmp_path / "templates.yaml"
    yaml_path.write_text(
        "templates:\n  - team: team-a\n    preferred_entity_types: []\n", encoding="utf-8"
    )
    monkeypatch.setenv("CALLIODESMO_EXTRACTION_TEMPLATE_FILE", str(yaml_path))
    get_settings.cache_clear()
    reviewer, t_r = await _seed_actor(session, "trev", {Permission.APPROVE})
    reset_app_stores()
    stores = get_app_stores()
    await stores.graph_store.upsert_graph(
        [
            EntityRecord(
                name="X",
                type="company",
                description="",
                template_conforming=False,
                library_scope=LibraryScope.PERSONAL,
                owner_id=reviewer.id,
            ),
        ],
        [],
    )
    async with _make_client(session) as c:
        resp = await c.get("/collab/template-types", headers=_auth(t_r))
        assert resp.status_code == 200
        assert any(it["type"] == "company" for it in resp.json())
        resp = await c.post(
            "/collab/template-types/approve",
            json={"team": "team-a", "type": "company"},
            headers=_auth(t_r),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "approved"
    get_settings.cache_clear()
    reg = ExtractionTemplateRegistry.from_yaml(yaml_path)
    assert "company" in reg.get("team-a").preferred_entity_types
    reset_app_stores()
    get_settings.cache_clear()
