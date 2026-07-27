"""Task 7 测试：API /query 端点。"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import calliodesmo.models  # noqa: F401
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import assign_role, create_user, seed_default_roles
from calliodesmo.config import get_settings
from calliodesmo.interfaces.retriever import Answer


class _StubEngine:
    async def query(self, question, *, mode, top_k, access):
        return Answer(
            text=f"Answer to: {question}",
            source_chunk_ids=["c1", "c2"],
            mode=mode,
            context_chunks=[
                {"chunk_id": "c1", "content": "ctx1", "score": 0.9},
                {"chunk_id": "c2", "content": "ctx2", "score": 0.8},
            ],
            model="test/stub",
            usage={"total_tokens": 10},
        )


async def _seed_user(session, username="queryuser", password="testpass123", permissions=None):
    from calliodesmo.auth.models import Role, RolePermission

    await seed_default_roles(session)
    if permissions is None:
        permissions = {Permission.QUERY}
    role = Role(name=f"role-{username}", description="test")
    session.add(role)
    await session.flush()
    for p in permissions:
        session.add(RolePermission(role_id=role.id, permission=p))
    user = await create_user(
        session, username=username, password=password, clearance=ClearanceLevel.SECRET
    )
    await assign_role(session, user=user, role_name=f"role-{username}", scope=LibraryScope.TEAM)
    await session.commit()
    return user


def _make_app(session, stub_engine=None):
    """创建 app 并覆盖 get_session + get_search_engine 依赖。"""
    from calliodesmo.api.app import create_app
    from calliodesmo.api.deps import get_search_engine
    from calliodesmo.db.session import get_session

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session

    if stub_engine is not None:

        async def _override_engine():
            return stub_engine

        app.dependency_overrides[get_search_engine] = _override_engine

    return app


@pytest.mark.asyncio
async def test_query_success(session):
    """认证 + QUERY 权限 -> 200 + 来源标注透传。"""
    import httpx
    from sqlalchemy import select

    from calliodesmo.audit.models import AuditLog

    user = await _seed_user(session)
    app = _make_app(session, _StubEngine())
    settings = get_settings()
    token = create_access_token(
        subject=str(user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/query",
            json={"question": "What is AI?", "mode": "native_rag", "top_k": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "Answer to" in data["answer"]
    assert data["mode"] == "native_rag"
    assert data["source_chunk_ids"] == ["c1", "c2"]
    assert len(data["context_chunks"]) == 2
    assert data["model"] == "test/stub"
    # 审计记录
    logs = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "query"))).scalars().all()
    )
    assert len(logs) >= 1


@pytest.mark.asyncio
async def test_query_invalid_mode(session):
    """非法 mode -> 400。"""
    import httpx

    user = await _seed_user(session, username="modeuser")
    app = _make_app(session, _StubEngine())
    settings = get_settings()
    token = create_access_token(
        subject=str(user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/query",
            json={"question": "q", "mode": "invalid", "top_k": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_query_no_permission(session):
    """缺 QUERY 权限 -> 403。"""
    import httpx

    user = await _seed_user(session, username="noperm", permissions={Permission.INGEST})
    app = _make_app(session, _StubEngine())
    settings = get_settings()
    token = create_access_token(
        subject=str(user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/query",
            json={"question": "q", "mode": "native_rag", "top_k": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 403
