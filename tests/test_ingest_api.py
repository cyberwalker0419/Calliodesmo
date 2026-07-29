"""POST /ingest：文件上传 -> ECL ingest 到当前用户个人库（StubLLM + Hash 嵌入）。"""

from collections.abc import AsyncIterator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.api.deps import get_app_stores, reset_app_stores
from calliodesmo.auth.models import (
    ClearanceLevel,
    LibraryScope,
    Permission,
    Role,
    RolePermission,
)
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import assign_role, create_user, seed_default_roles
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.session import get_session


async def _seed_actor(session, username, permissions, clearance=ClearanceLevel.SECRET):
    await seed_default_roles(session)
    role = Role(name=f"role-{username}", description="test")
    session.add(role)
    await session.flush()
    for p in permissions:
        session.add(RolePermission(role_id=role.id, permission=p))
    user = await create_user(session, username=username, password="pw-123456", clearance=clearance)
    await assign_role(session, user=user, role_name=f"role-{username}", scope=LibraryScope.PERSONAL)
    await session.commit()
    settings = get_settings()
    token = create_access_token(
        subject=str(user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )
    return user, token


def _test_settings() -> Settings:
    """离线 settings：test/stub LLM + hash 嵌入 + example 模板（零网络）。"""
    base = get_settings()
    return base.model_copy(
        update={
            "llm_model": "test/stub",
            "embedding_provider": "hash",
            "extraction_template_file": "config/extraction_templates.example.yaml",
            "llm_api_key": "test",
        }
    )


def _make_client(session: AsyncSession) -> httpx.AsyncClient:
    from calliodesmo.api.app import create_app

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = _test_settings
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_ingest_writes_personal_library(session):
    """有 INGEST 权限上传 .md -> 201 + chunk 落个人库（owner=用户, scope=personal）。"""
    reset_app_stores()
    user, token = await _seed_actor(session, "analyst1", {Permission.INGEST})
    content = "# 测试文档\n\nOpenAI 是 AI 公司。GPT-4 是大模型。".encode()
    async with _make_client(session) as c:
        resp = await c.post(
            "/ingest",
            files={"file": ("test.md", content, "text/markdown")},
            headers=_auth(token),
        )
    assert resp.status_code == 201, resp.text
    stats = resp.json()
    assert stats["chunks"] > 0
    assert stats["entities"] >= 1  # StubLLM 返回 OpenAI/GPT-4
    # chunk 落个人库：owner=用户 + scope=personal
    stores = get_app_stores()
    chunks = list(stores.vector_store._records.values())
    assert any(c.library_scope == LibraryScope.PERSONAL and c.owner_id == user.id for c in chunks)


async def test_ingest_requires_ingest_permission(session):
    """无 INGEST 权限 -> 403。"""
    reset_app_stores()
    _, token = await _seed_actor(session, "noperm", {Permission.QUERY})
    async with _make_client(session) as c:
        resp = await c.post(
            "/ingest",
            files={"file": ("test.md", b"x", "text/markdown")},
            headers=_auth(token),
        )
    assert resp.status_code == 403


async def test_ingest_requires_auth(session):
    """无 token -> 401。"""
    reset_app_stores()
    async with _make_client(session) as c:
        resp = await c.post("/ingest", files={"file": ("test.md", b"x", "text/markdown")})
    assert resp.status_code == 401
