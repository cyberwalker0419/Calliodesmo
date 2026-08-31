"""P7 T14：/agent sessions / runs / messages（job 范式 + 审计 + 401/403/404 矩阵）。

仿 test_analysis_api 范式：离线配置（test/stub + hash）+ dependency_overrides
session/job_factory；BackgroundTasks 经 ASGITransport 响应后同步执行。

覆盖：401 未认证；403 缺 query；201 建会话 + 审计 agent_session_create；未注册
mode 400；runs 202 -> job succeeded -> messages 两轮；他人会话 / 不存在 -> 404
同一文案（不泄漏存在性）；根 + /api 双挂。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import calliodesmo.models  # noqa: F401
from calliodesmo.audit.models import AuditLog
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission, Role, RolePermission
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import assign_role, create_user, seed_default_roles
from calliodesmo.config import Settings
from calliodesmo.db.models_job import Job, JobStatus
from calliodesmo.db.session import get_session


def _test_settings() -> Settings:
    return Settings(
        llm_model="test/stub",
        embedding_provider="hash",
        embedding_dimension=64,
        extraction_template_file="config/extraction_templates.example.yaml",
    )


def _make_client(session: AsyncSession) -> httpx.AsyncClient:
    from calliodesmo.api.app import create_app
    from calliodesmo.api.deps import get_job_session_factory

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    job_factory = async_sessionmaker(session.bind, expire_on_commit=False)
    app.dependency_overrides[get_session] = _override_session
    from calliodesmo.api.deps import get_settings

    app.dependency_overrides[get_settings] = _test_settings
    app.dependency_overrides[get_job_session_factory] = lambda: job_factory
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _actor(session, username="agent-api-u", perms=None, clearance=ClearanceLevel.SECRET):
    await seed_default_roles(session)
    user = await create_user(session, username=username, password="pw", clearance=clearance)
    if perms is None:
        await assign_role(session, user=user, role_name="analyst", scope=LibraryScope.TEAM)
    else:
        role = Role(name=f"custom-{username}", description="")
        session.add(role)
        await session.flush()
        for p in perms:
            session.add(RolePermission(role_id=role.id, permission=p))
        from calliodesmo.auth.models import UserRole

        session.add(UserRole(user_id=user.id, role_id=role.id, scope=LibraryScope.PERSONAL))
    await session.commit()
    settings = _test_settings()
    token = create_access_token(
        subject=str(user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.jwt_expire_minutes,
    )
    return user, token


async def test_agent_api_requires_auth(session):
    client = _make_client(session)
    r = await client.get("/agent/sessions")
    assert r.status_code == 401


async def test_agent_api_forbidden_without_query(session):
    client = _make_client(session)
    _, token = await _actor(session, username="noquery-u", perms={Permission.INGEST})
    r = await client.post("/agent/sessions", json={}, headers=_auth(token))
    assert r.status_code == 403


async def test_create_session_and_bad_mode(session):
    client = _make_client(session)
    user, token = await _actor(session)
    r = await client.post("/agent/sessions", json={"label": "会话一"}, headers=_auth(token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mode"] == "react"
    assert body["library_scope"] == "personal"

    audits = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "agent_session_create")))
        .scalars()
        .all()
    )
    assert audits and audits[0].user_id == user.id

    bad = await client.post("/agent/sessions", json={"mode": "rewoo"}, headers=_auth(token))
    assert bad.status_code == 400  # 预留值不注册


async def test_run_roundtrip_and_messages(session):
    """202 -> BackgroundTasks 同步执行 -> job succeeded -> messages 两轮。"""
    client = _make_client(session)
    _, token = await _actor(session)
    sid = (await client.post("/agent/sessions", json={}, headers=_auth(token))).json()["id"]

    r = await client.post(
        f"/agent/sessions/{sid}/runs",
        json={"question": "GPT-4 由谁开发？"},
        headers=_auth(token),
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    session.expire_all()  # 端点经同 session 建 job，身份映射缓存 PENDING，须过期重读

    # job 终态（worker 用 job_factory 同测试 engine）
    job = (await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))).scalar_one()
    assert job.status == JobStatus.SUCCEEDED
    assert job.task_type == "agent"

    msgs = await client.get(f"/agent/sessions/{sid}/messages", headers=_auth(token))
    assert msgs.status_code == 200
    roles = [m["role"] for m in msgs.json()]
    assert roles == ["user", "assistant"]
    assert "OpenAI" in msgs.json()[1]["content"]

    # 审计 agent_run 落库
    audits = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "agent_run")))
        .scalars()
        .all()
    )
    assert audits

    # /api 双挂
    via_api = await client.get(f"/api/agent/sessions/{sid}/messages", headers=_auth(token))
    assert via_api.status_code == 200


async def test_session_invisible_404_same_message(session):
    """他人会话与不存在会话同一 404 文案（不泄漏存在性）。"""
    client = _make_client(session)
    _, owner_token = await _actor(session, username="owner-u")
    _, stranger_token = await _actor(session, username="stranger-u")

    sid = (await client.post("/agent/sessions", json={}, headers=_auth(owner_token))).json()["id"]

    for path in ("runs", "messages"):
        url = f"/agent/sessions/{sid}/{path}"
        denied = (
            await client.post(url, json={"question": "q"}, headers=_auth(stranger_token))
            if path == "runs"
            else await client.get(url, headers=_auth(stranger_token))
        )
        ghost = (
            await client.post(
                f"/agent/sessions/{uuid.uuid4()}/{path}",
                json={"question": "q"},
                headers=_auth(stranger_token),
            )
            if path == "runs"
            else await client.get(
                f"/agent/sessions/{uuid.uuid4()}/{path}", headers=_auth(stranger_token)
            )
        )
        assert denied.status_code == 404 and ghost.status_code == 404
        assert denied.json()["detail"] == ghost.json()["detail"]

    # 列表：stranger 不见 owner 会话
    lst = (await client.get("/agent/sessions", headers=_auth(stranger_token))).json()
    assert lst["total"] == 0
    lst_own = (await client.get("/agent/sessions", headers=_auth(owner_token))).json()
    assert lst_own["total"] == 1
