"""POST /ingest（202 异步 job）+ GET /jobs/{id}：上传 -> 轮询 -> 终态。

P4.5 Task 5。StubLLM + Hash 嵌入 + OCR/识图桩（零网络）；BackgroundTasks 经
httpx ASGITransport 在响应后同步执行，断言终态直接成立。worker 落库走测试
schema 的 session 工厂（override get_job_session_factory）。
"""

from collections.abc import AsyncIterator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
    """离线 settings：test/stub LLM + hash 嵌入 + OCR/识图桩 + example 模板（零网络）。"""
    base = get_settings()
    return base.model_copy(
        update={
            "llm_model": "test/stub",
            "embedding_provider": "hash",
            "extraction_template_file": "config/extraction_templates.example.yaml",
            "llm_api_key": "test",
            "ocr_provider": "stub",
            "vision_model": "test/stub-vision",
        }
    )


def _make_client(session: AsyncSession) -> httpx.AsyncClient:
    """ASGI 客户端：复用 session 夹具 + job worker 落库走同一测试 engine。

    ``_pg_engine`` 经 ``session`` 的 bind 链取（session fixture 的工厂即测试 engine）。
    """
    from calliodesmo.api.app import create_app
    from calliodesmo.api.deps import get_job_session_factory

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    job_factory = async_sessionmaker(_engine_of(session), expire_on_commit=False)

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = _test_settings
    app.dependency_overrides[get_job_session_factory] = lambda: job_factory
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _engine_of(session: AsyncSession):
    """取 session 背后的 AsyncEngine（测试专用 schema 的 engine）。"""
    return session.bind  # type: ignore[return-value]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_ingest_job_succeeds(session):
    """202 + job_id -> 轮询 succeeded + result 统计；chunk 落个人库（owner=用户）。"""
    reset_app_stores()
    user, token = await _seed_actor(session, "analyst1", {Permission.INGEST})
    content = "# 测试文档\n\nOpenAI 是 AI 公司。GPT-4 是大模型。".encode()
    async with _make_client(session) as c:
        resp = await c.post(
            "/ingest",
            files={"file": ("test.md", content, "text/markdown")},
            headers=_auth(token),
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        job_id = body["job_id"]
        assert body["status"] == "pending"
        # BackgroundTasks 已随响应执行完毕 -> 终态可查
        job = (await c.get(f"/jobs/{job_id}", headers=_auth(token))).json()
        assert job["status"] == "succeeded", job
        assert job["progress"] == 100
        assert job["result"]["chunks"] > 0
        assert job["result"]["entities"] >= 1  # StubLLM 返回 OpenAI/GPT-4
    # chunk 落个人库：owner=用户 + scope=personal
    stores = get_app_stores()
    chunks = list(stores.vector_store._records.values())
    assert any(c.library_scope == LibraryScope.PERSONAL and c.owner_id == user.id for c in chunks)


async def test_ingest_clearance_prefix_preserved(session):
    """文件名密级前缀（public__）经临时文件保留 -> chunk access_level 生效。"""
    reset_app_stores()
    _, token = await _seed_actor(session, "analyst-prefix", {Permission.INGEST})
    content = "# 公开材料\n\nOpenAI 是 AI 公司。".encode()
    async with _make_client(session) as c:
        resp = await c.post(
            "/ingest",
            files={"file": ("public__openai.md", content, "text/markdown")},
            headers=_auth(token),
        )
        assert resp.status_code == 202, resp.text
        job = (await c.get(f"/jobs/{resp.json()['job_id']}", headers=_auth(token))).json()
        assert job["status"] == "succeeded", job
    stores = get_app_stores()
    chunks = list(stores.vector_store._records.values())
    assert chunks, "应有摄入的 chunk"
    assert all(c.access_level == ClearanceLevel.PUBLIC for c in chunks), [
        c.access_level for c in chunks
    ]


async def test_ingest_job_owner_isolation(session):
    """他人 job 不可见 -> 404（不泄漏存在性）。"""
    reset_app_stores()
    _, token_a = await _seed_actor(session, "ownerA", {Permission.INGEST})
    _, token_b = await _seed_actor(session, "ownerB", {Permission.INGEST})
    content = "# 测试\n\nOpenAI 是 AI 公司。".encode()
    async with _make_client(session) as c:
        resp = await c.post(
            "/ingest", files={"file": ("a.md", content, "text/markdown")}, headers=_auth(token_a)
        )
        job_id = resp.json()["job_id"]
        resp_b = await c.get(f"/jobs/{job_id}", headers=_auth(token_b))
    assert resp_b.status_code == 404


async def test_ingest_requires_ingest_permission(session):
    """无 INGEST 权限 -> 403。"""
    reset_app_stores()
    _, token = await _seed_actor(session, "noperm", {Permission.QUERY})
    async with _make_client(session) as c:
        resp = await c.post(
            "/ingest", files={"file": ("test.md", b"x", "text/markdown")}, headers=_auth(token)
        )
    assert resp.status_code == 403


async def test_ingest_requires_auth(session):
    """无 token -> 401。"""
    reset_app_stores()
    async with _make_client(session) as c:
        resp = await c.post("/ingest", files={"file": ("test.md", b"x", "text/markdown")})
    assert resp.status_code == 401


async def test_ingest_unknown_suffix_400(session):
    """未注册后缀 -> 400（引擎构建期 ValueError）。"""
    reset_app_stores()
    _, token = await _seed_actor(session, "badtype", {Permission.INGEST})
    async with _make_client(session) as c:
        resp = await c.post(
            "/ingest",
            files={"file": ("doc.zzz", b"x", "application/octet-stream")},
            headers=_auth(token),
        )
    assert resp.status_code == 400


async def test_ingest_llm_missing_key_503(session):
    """非豁免 LLM 缺 key -> 503（引擎构建期 RuntimeError -> 请求侧判定）。"""
    reset_app_stores()
    _, token = await _seed_actor(session, "nokey", {Permission.INGEST})
    base = get_settings()
    nokey_settings = base.model_copy(
        update={
            "llm_model": "openai/gpt-4o-mini",
            "llm_api_key": None,
            "llm_api_base": "https://api.openai.com/v1",
            "embedding_provider": "hash",
            "extraction_template_file": "config/extraction_templates.example.yaml",
            "ocr_provider": "none",
        }
    )
    from calliodesmo.api.app import create_app
    from calliodesmo.api.deps import get_job_session_factory

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    job_factory = async_sessionmaker(_engine_of(session), expire_on_commit=False)
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = lambda: nokey_settings
    app.dependency_overrides[get_job_session_factory] = lambda: job_factory
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        resp = await c.post(
            "/ingest", files={"file": ("t.md", b"x", "text/markdown")}, headers=_auth(token)
        )
    assert resp.status_code == 503, resp.text


async def test_ingest_png_with_stub_ocr_job(session):
    """上传 PNG -> 202 -> job succeeded + chunk（StubOCR 转文本 -> StubLLM 抽取）。"""
    reset_app_stores()
    user, token = await _seed_actor(session, "pnguser", {Permission.INGEST})
    # 1x1 透明 PNG（合法最小）
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffffff8455a17c0000000049454e44ae426082"
    )
    async with _make_client(session) as c:
        resp = await c.post(
            "/ingest", files={"file": ("scan.png", png, "image/png")}, headers=_auth(token)
        )
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        job = (await c.get(f"/jobs/{job_id}", headers=_auth(token))).json()
        assert job["status"] == "succeeded", job
        assert job["result"]["chunks"] > 0
    # 落库：OCR 文本进入 chunk（StubLLM 抽取实体）
    stores = get_app_stores()
    chunks = list(stores.vector_store._records.values())
    assert any(c.owner_id == user.id for c in chunks)


async def test_delete_doc_removes_from_personal_library(session):
    """DELETE /ingest/{doc_id}：删除文档及其派生（chunk 清）。"""
    reset_app_stores()
    _, token = await _seed_actor(session, "del1", {Permission.INGEST})
    content = "# 测试文档\n\nOpenAI 是 AI 公司。GPT-4 是大模型。".encode()
    async with _make_client(session) as c:
        resp = await c.post(
            "/ingest", files={"file": ("test.md", content, "text/markdown")}, headers=_auth(token)
        )
        assert resp.status_code == 202
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
    _, token_a = await _seed_actor(session, "ownerA2", {Permission.INGEST})
    _, token_b = await _seed_actor(session, "ownerB2", {Permission.INGEST})
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


async def test_job_worker_failure_marks_failed(session):
    """worker 执行异常（引擎 ingest 抛错）-> job failed + error 落库。"""
    reset_app_stores()
    _, token = await _seed_actor(session, "failcase", {Permission.INGEST})
    from calliodesmo.api.app import create_app
    from calliodesmo.api.deps import get_job_session_factory

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    # 引擎构建成功，但 ingest 抛错：monkeypatch build_default_indexing_engine 返回坏引擎
    import calliodesmo.api.ingest as ingest_mod

    class _BadEngine:
        loader = None

        async def ingest(self, source, *, access):  # type: ignore[no-untyped-def]
            raise RuntimeError("ECL 炸了（测试注入）")

    _orig = ingest_mod.build_default_indexing_engine
    ingest_mod.build_default_indexing_engine = lambda *a, **kw: _BadEngine()  # type: ignore[assignment]
    try:
        job_factory = async_sessionmaker(_engine_of(session), expire_on_commit=False)
        app.dependency_overrides[get_session] = _override_session
        app.dependency_overrides[get_settings] = _test_settings
        app.dependency_overrides[get_job_session_factory] = lambda: job_factory
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            resp = await c.post(
                "/ingest",
                files={"file": ("boom.md", "# x\n\nOpenAI 是 AI 公司。".encode(), "text/markdown")},
                headers=_auth(token),
            )
            assert resp.status_code == 202, resp.text
            job_id = resp.json()["job_id"]
            job = (await c.get(f"/jobs/{job_id}", headers=_auth(token))).json()
            assert job["status"] == "failed"
            assert "ECL 炸了" in job["error"]
    finally:
        ingest_mod.build_default_indexing_engine = _orig  # type: ignore[assignment]
        app.dependency_overrides.clear()
