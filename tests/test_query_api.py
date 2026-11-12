"""Task 7 测试：API /query 端点。"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
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


# ---- /query/with-image 多模态（StubVision） ----


async def _stub_vision():
    from calliodesmo.providers.stub_vision import StubVisionProvider

    return StubVisionProvider()


def _make_app_with_vision(session, stub_engine=None, vision=None):
    """创建 app：覆盖 get_session + get_search_engine(+get_vision_provider)。"""
    from calliodesmo.api.app import create_app
    from calliodesmo.api.deps import get_search_engine, get_vision_provider
    from calliodesmo.db.session import get_session

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session

    if stub_engine is not None:

        async def _override_engine():
            return stub_engine

        app.dependency_overrides[get_search_engine] = _override_engine

    if vision is not None:

        async def _override_vision():
            return vision

        app.dependency_overrides[get_vision_provider] = _override_vision

    return app


async def test_query_with_image_multipart(session):
    """带图提问（multipart）-> 200 + 来源/审计透传，识图描述并入问题。"""
    import httpx
    from sqlalchemy import select

    from calliodesmo.audit.models import AuditLog

    calls = {}

    class _RecorderEngine(_StubEngine):
        async def query(self, question, *, mode, top_k, access):
            calls["question"] = question
            return await super().query(question, mode=mode, top_k=top_k, access=access)

    user = await _seed_user(session, username="imguser")
    app = _make_app_with_vision(session, _RecorderEngine(), await _stub_vision())
    settings = get_settings()
    token = create_access_token(
        subject=str(user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffffff8455a17c0000000049454e44ae426082"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/query/with-image",
            data={"question": "图里有什么？", "mode": "native_rag", "top_k": 5},
            files={"file": ("photo.png", png, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "Answer to" in data["answer"]
    # 识图描述已并入问题（[图片内容描述] 注入点）
    assert "[图片内容描述]" in calls["question"]
    assert "占位" in calls["question"]
    # 审计 has_image
    logs = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "query"))).scalars().all()
    )
    assert logs and any(hasattr(log.detail, "get") and log.detail.get("has_image") for log in logs)


async def test_query_with_image_rejects_oversize(session):
    """图片超上限 -> 413。"""
    import httpx

    user = await _seed_user(session, username="bigimg")
    app = _make_app_with_vision(session, _StubEngine(), await _stub_vision())
    settings = get_settings()
    token = create_access_token(
        subject=str(user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # 大 PNG（>默认上限 15MB）
        big = b"\x89PNG" + b"\x00" * (16 * 1024 * 1024)
        resp = await c.post(
            "/query/with-image",
            data={"question": "q"},
            files={"file": ("big.png", big, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 413


class _CitedStubEngine:
    """带引注答案的桩引擎：P8 接地度侧车字段断言用。"""

    async def query(self, question, *, mode, top_k, access):
        return Answer(
            text=(
                "稀土市场保持平稳 [c1]。"
                "APT28 的指挥部位于圣彼得堡 [c2]。"
                "这是一句没有引注的补充说明。"
            ),
            source_chunk_ids=["c1", "c2"],
            mode=mode,
            context_chunks=[
                {"chunk_id": "c1", "content": "本月稀土市场保持平稳。", "score": 0.9},
                {"chunk_id": "c2", "content": "APT28 是疑似源自俄罗斯的威胁组织。", "score": 0.8},
            ],
            model="test/stub",
            usage={"total_tokens": 10},
        )


@pytest.mark.asyncio
async def test_query_returns_verification_sidecar(session):
    """P8 T3：QA 响应带 verification（引注核验 / 未引注单列 / 复核标记）。"""
    import httpx

    from calliodesmo.audit.models import AuditLog

    user = await _seed_user(session, username="queryverify")
    app = _make_app(session, _CitedStubEngine())
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
            json={"question": "稀土与 APT28", "mode": "native_rag", "top_k": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    verification = resp.json()["verification"]
    assert verification is not None
    assert verification["source"] == "qa"
    assert verification["totals"]["claims"] == 3
    assert verification["totals"]["checkable"] == 2
    assert verification["totals"]["supported"] == 1
    assert verification["totals"]["unsupported"] == 1
    assert verification["totals"]["uncited"] == 1
    assert verification["metrics"]["citation_precision"] == 0.5
    assert verification["needs_review"] is True

    logs = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "evidence_verify")))
        .scalars()
        .all()
    )
    assert logs and logs[0].detail["claims"] == 3


@pytest.mark.asyncio
async def test_query_auto_routes_and_audits(session):
    """P8 T5：mode=auto 路由并回显 routed_mode + routing，审计 intent_route。"""
    import httpx

    from calliodesmo.audit.models import AuditLog

    user = await _seed_user(session, username="queryauto")
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
            json={"question": "总结本月稀土市场的整体趋势", "mode": "auto", "top_k": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "global"
    assert data["routed_mode"] == "global"
    assert data["routing"]["requested_mode"] == "auto"
    assert data["routing"]["executed_mode"] == "global"
    assert data["routing"]["fallback"] is False
    assert data["routing"]["reasons"]

    logs = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "intent_route")))
        .scalars()
        .all()
    )
    assert logs and logs[0].detail["routed_mode"] == "global"


@pytest.mark.asyncio
async def test_query_explicit_mode_unchanged(session):
    """显式模式零改写：routed_mode / routing 恒为 null。"""
    import httpx

    user = await _seed_user(session, username="queryexplicit")
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
            json={"question": "总结本月稀土市场的整体趋势", "mode": "local", "top_k": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "local"
    assert data["routed_mode"] is None
    assert data["routing"] is None


@pytest.mark.asyncio
async def test_query_auto_agent_falls_back_to_local(session):
    """路由到 agent 时 /query 回退 local 并留痕（Agent 需专用端点）。"""
    import httpx

    user = await _seed_user(session, username="queryagent")
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
            json={"question": "帮我调查 APT28 的组织结构并生成报告", "mode": "auto", "top_k": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["routed_mode"] == "agent"
    assert data["mode"] == "local"
    assert data["routing"]["fallback"] is True
    assert any("Agent 模式需专用端点" in reason for reason in data["routing"]["reasons"])
