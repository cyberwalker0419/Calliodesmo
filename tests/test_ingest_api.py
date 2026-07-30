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


async def test_delete_doc_removes_from_personal_library(session):
    """DELETE /ingest/{doc_id}：删除文档及其派生（chunk 清）。"""
    reset_app_stores()
    _, token = await _seed_actor(session, "del1", {Permission.INGEST})
    content = "# 测试文档\n\nOpenAI 是 AI 公司。GPT-4 是大模型。".encode()
    async with _make_client(session) as c:
        resp = await c.post(
            "/ingest", files={"file": ("test.md", content, "text/markdown")}, headers=_auth(token)
        )
        assert resp.status_code == 201
        # 从 stores 读实际 doc_id（ingest 用临时文件名作 doc_id）
        stores = get_app_stores()
        chunks = list(stores.vector_store._records.values())
        assert chunks, "ingest 应已落 chunk"
        doc_id = chunks[0].doc_id
        del_resp = await c.delete(f"/ingest/{doc_id}", headers=_auth(token))
        assert del_resp.status_code == 204
    # chunk 已清
    stores = get_app_stores()
    chunks_after = list(stores.vector_store._records.values())
    assert not any(c.doc_id == doc_id for c in chunks_after)


async def test_delete_nonexistent_404(session):
    """删不存在的文档 -> 404。"""
    reset_app_stores()
    _, token = await _seed_actor(session, "del2", {Permission.INGEST})
    async with _make_client(session) as c:
        resp = await c.delete("/ingest/nope.md", headers=_auth(token))
    assert resp.status_code == 404


async def test_delete_other_users_doc_404(session):
    """别人的 personal doc 不可见 -> 删除返回 404（不泄漏存在性）。"""
    reset_app_stores()
    _, token_a = await _seed_actor(session, "ownerA", {Permission.INGEST})
    _, token_b = await _seed_actor(session, "ownerB", {Permission.INGEST})
    content = "# 机密\n\nOpenAI 是 AI 公司。GPT-4 是大模型。".encode()
    async with _make_client(session) as c:
        await c.post(
            "/ingest",
            files={"file": ("secret.md", content, "text/markdown")},
            headers=_auth(token_a),
        )
        # B 尝试删 A 的文档 -> 404（list_chunks 经 visible_to 过滤，B 看不到 A 的 doc）
        resp = await c.delete("/ingest/secret.md", headers=_auth(token_b))
    assert resp.status_code == 404
