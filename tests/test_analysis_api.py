"""分析 API 测试（P6 Task 14/15）：提交 202 + 历史 / 详情 + 导出 + 可见文档清单 + 双挂。

仿 ``tests/test_ingest_job_api.py`` 范式：``_test_settings()`` 离线配置（test/stub
LLM + hash 嵌入，零网络）+ ``dependency_overrides[get_job_session_factory]`` 指向
测试 schema + ``_seed_actor`` 自定义角色。BackgroundTasks 经 httpx ASGITransport
在响应后同步执行，终态断言直接成立（与 ingest e2e 同机制）。

覆盖（对齐计划 Task 14 Step 1 与「错误码一览」）：

- 401 未认证 / 403 缺 analyze（提交与读取两侧）；
- 合法提交 -> 202 + job_id + 审计 ``analyze_submit``（resource_type="job"）；
- 400：未注册 task_type（未交付二类 / 非法字符串）/ qa 缺 question / custom 缺
  instruction / doc_ids 含不可见项（不泄漏存在性细节）；
- 422 请求体 pydantic 校验失败；503 模型缺 key（RuntimeError -> 503，同 ingest 惯例）；
- ``GET /analysis/reports`` 三维过滤（personal 隔离 + clearance）+ 分页；
- ``GET /analysis/reports/{id}`` 他人不可见 / 不存在 / 低 clearance -> 404（不暴露存在性）；
- ``GET /analysis/documents`` 按 doc_id 聚合可见文档（label 回退 / 密级取 max / 块数）；
- 端到端：POST -> worker -> GET /jobs/{id} 见 task_type / report_id -> 报告详情可见
  （模板类 + QA 类各一；QA 经 dependency_overrides[get_search_engine] 注桩）；
- 三角色提交 / 读取矩阵：analyst / reviewer / admin 均可提交（决策 1），
  报告 personal 隔离（含 admin 亦不可读他人报告）；
- 导出端点（Task 15）：无 export 权限 -> 403（守卫仅 EXPORT）；不可见 / 不存在 -> 404；
  200 时 Content-Disposition 附件文件名（json 默认 / md）+ 内容与报告一致 +
  md 按 JSON 分节含证据引用标注 + 审计 ``report_export``；渲染纯函数离线可测；
- 根 + /api 前缀双挂。

桩对生成质量零区分度：本文件只承诺状态机 / 契约 / 权限 / 审计结构，不承诺分析质量。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.analysis.report_store import AnalysisReportStore
from calliodesmo.analysis.schemas import AnalysisEnvelope
from calliodesmo.api.analysis import render_report_markdown
from calliodesmo.api.deps import get_app_stores, reset_app_stores
from calliodesmo.audit.models import AuditLog
from calliodesmo.auth.models import (
    ClearanceLevel,
    LibraryScope,
    Permission,
    Role,
    RolePermission,
    User,
)
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import assign_role, create_user, seed_default_roles
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.models_analysis import AnalysisReportORM
from calliodesmo.db.session import get_session
from calliodesmo.interfaces.retriever import Answer
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.utils.json import json_safe

_DIM = get_settings().embedding_dimension


def _v() -> list[float]:
    """构造 _DIM 维向量（首位填 1，其余 0；内存库不校验维度，仅保形态）。"""
    vec = [0.0] * _DIM
    vec[0] = 1.0
    return vec


def _chunk(
    chunk_id: str,
    owner,
    *,
    doc_id: str,
    content: str,
    access_level=ClearanceLevel.INTERNAL,
    metadata=None,
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id=doc_id,
        content=content,
        vector=_v(),
        metadata=metadata if metadata is not None else {},
        access_level=access_level,
        library_scope=LibraryScope.PERSONAL,
        owner_id=owner,
        project_id=None,
        team_id=None,
    )


def _test_settings() -> Settings:
    """离线 settings：test/stub LLM + hash 嵌入（零网络零重依赖）。"""
    base = get_settings()
    return base.model_copy(
        update={
            "llm_model": "test/stub",
            "embedding_provider": "hash",
            "llm_api_key": "test",
        }
    )


def _token(user) -> str:
    settings = get_settings()
    return create_access_token(
        subject=str(user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )


async def _seed_actor(
    session: AsyncSession, username, permissions, clearance=ClearanceLevel.SECRET
):
    """自定义角色用户（仿 test_ingest_job_api._seed_actor）：权限集可任意定制。"""
    await seed_default_roles(session)
    role = Role(name=f"role-{username}", description="test")
    session.add(role)
    await session.flush()
    for p in permissions:
        session.add(RolePermission(role_id=role.id, permission=p))
    user = await create_user(session, username=username, password="pw-123456", clearance=clearance)
    await assign_role(session, user=user, role_name=f"role-{username}", scope=LibraryScope.PERSONAL)
    await session.commit()
    return user, _token(user)


async def _seed_role_user(session: AsyncSession, username, role_name, clearance):
    """内置角色用户（三角色矩阵用：analyst / reviewer / admin 走种子角色）。"""
    await seed_default_roles(session)
    user = await create_user(session, username=username, password="pw-123456", clearance=clearance)
    await assign_role(session, user=user, role_name=role_name, scope=LibraryScope.PERSONAL)
    await session.commit()
    return user, _token(user)


class _StubSearchEngine:
    """QA 桩检索引擎（克隆 test_query_api._StubEngine）：供 QA e2e 经依赖覆盖注入。"""

    async def query(self, question, *, mode, top_k, access):
        return Answer(
            text=f"Answer to: {question}",
            source_chunk_ids=["alpha.md#0"],
            mode=mode,
            context_chunks=[{"chunk_id": "alpha.md#0", "content": "ctx", "score": 0.9}],
            model="test/stub",
            usage={"total_tokens": 10},
        )


def _make_client(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    search_engine: object | None = None,
) -> httpx.AsyncClient:
    """ASGI 客户端：session 夹具复用 + worker 落库走同一测试 engine。

    ``search_engine`` 非 None 时覆盖 ``get_search_engine``（QA e2e 注桩，
    同 test_query_api 范式）。
    """
    from calliodesmo.api.app import create_app
    from calliodesmo.api.deps import get_job_session_factory, get_search_engine

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    job_factory = async_sessionmaker(session.bind, expire_on_commit=False)  # type: ignore[arg-type]
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = lambda: settings or _test_settings()
    app.dependency_overrides[get_job_session_factory] = lambda: job_factory
    if search_engine is not None:
        app.dependency_overrides[get_search_engine] = lambda: search_engine
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _envelope_payload(task_type: str = "summary", evidence: list[dict] | None = None) -> dict:
    """构造合法信封 dict（报告行直建用例用；与 worker 落库形态一致）。

    ``evidence`` 供导出 md 分节渲染用例注入证据条目（默认空证据列表）。
    """
    return AnalysisEnvelope(
        task_type=task_type,
        status="ok",
        generated_at=datetime.now(UTC),
        model="test/stub",
        prompt_version=f"{task_type}.v1",
        usage={"total_tokens": 3},
        warnings=[],
        source_chunk_ids=["alpha.md#0"],
        payload={
            "summary": "桩摘要",
            "key_points": ["要点甲"],
            "confidence": 1.0,
            "evidence": evidence or [],
        },
    ).model_dump()


async def _create_report_row(
    session: AsyncSession,
    *,
    user_id,
    task_type: str = "summary",
    access_level=ClearanceLevel.INTERNAL,
    subject_label: str = "Alpha 文档",
    evidence: list[dict] | None = None,
) -> AnalysisReportORM:
    """经 AnalysisReportStore 直建报告行（读取矩阵 / 分页 / 密级 / 导出用例用）。"""
    report = await AnalysisReportStore().create(
        session,
        job_id=None,
        user_id=user_id,
        task_type=task_type,
        status="ok",
        subject_label=subject_label,
        payload=_envelope_payload(task_type, evidence=evidence),
        source_doc_ids=["alpha.md"],
        source_chunk_count=1,
        access_level=access_level,
        model="test/stub",
        prompt_version=f"{task_type}.v1",
        usage={"total_tokens": 3},
    )
    await session.commit()
    return report


@pytest.fixture(autouse=True)
def _fresh_stores():
    """每用例重置 AppStores 单例（内存向量库隔离）。"""
    reset_app_stores()
    yield
    reset_app_stores()


# ---------------------------------------------------------------------------
# 提交侧：202 + 审计；401 / 403 / 400 / 422 / 503 错误码全集
# ---------------------------------------------------------------------------


async def test_submit_requires_auth(session):
    """无 token -> 401。"""
    async with _make_client(session) as c:
        resp = await c.post("/analysis/tasks", json={"task_type": "summary"})
    assert resp.status_code == 401


async def test_submit_requires_analyze_permission(session):
    """无 analyze 权限（仅 query）-> 403。"""
    _, token = await _seed_actor(session, "noperm", {Permission.QUERY})
    async with _make_client(session) as c:
        resp = await c.post("/analysis/tasks", json={"task_type": "summary"}, headers=_auth(token))
    assert resp.status_code == 403


async def test_submit_summary_accepted_and_e2e(session):
    """合法提交 -> 202 + job_id + 审计 analyze_submit；e2e 到报告详情可见。"""
    user, token = await _seed_actor(session, "analyst-e2e", {Permission.ANALYZE})
    await get_app_stores().vector_store.upsert_chunks(
        [
            _chunk(
                "alpha.md#0",
                user.id,
                doc_id="alpha.md",
                content="阿尔法文档第一块。",
                metadata={"title": "Alpha 文档"},
            ),
            _chunk(
                "alpha.md#1",
                user.id,
                doc_id="alpha.md",
                content="阿尔法文档第二块。",
                metadata={"title": "Alpha 文档"},
            ),
        ]
    )
    async with _make_client(session) as c:
        resp = await c.post("/analysis/tasks", json={"task_type": "summary"}, headers=_auth(token))
        assert resp.status_code == 202, resp.text
        body = resp.json()
        job_id = body["job_id"]
        assert body["status"] == "pending"
        assert body["task_type"] == "summary"

        # BackgroundTasks 已随响应执行完毕 -> 终态可查（见 task_type / report_id 透传）
        job = (await c.get(f"/jobs/{job_id}", headers=_auth(token))).json()
        assert job["status"] == "succeeded", job
        assert job["task_type"] == "analyze"
        assert job["progress"] == 100
        assert job["report_id"] is not None
        report_id = job["report_id"]

        # 历史列表见该报告
        listing = (await c.get("/analysis/reports", headers=_auth(token))).json()
        assert listing["total"] == 1
        item = listing["items"][0]
        assert item["id"] == report_id
        assert item["task_type"] == "summary"
        assert item["status"] == "ok"
        assert item["subject_label"] == "Alpha 文档"
        assert item["access_level"] == "INTERNAL"  # max(材料各级, INTERNAL)
        assert item["library_scope"] == "personal"
        assert item["model"] == "test/stub"
        assert item["source_chunk_count"] == 2

        # 详情 = 完整信封（出参直接取信封）
        detail = (await c.get(f"/analysis/reports/{report_id}", headers=_auth(token))).json()
        assert detail["task_type"] == "summary"
        assert detail["status"] == "ok"
        assert detail["generated_at"]
        assert detail["prompt_version"] == "summary.v1"
        assert detail["payload"]["summary"]  # SummaryReport 载荷落位
        assert set(detail["source_chunk_ids"]) == {"alpha.md#0", "alpha.md#1"}

    # 审计：提交侧 analyze_submit（resource_type=job）+ worker 终态 analyze
    submit_logs = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "analyze_submit")))
        .scalars()
        .all()
    )
    assert len(submit_logs) == 1
    assert submit_logs[0].resource_type == "job"
    assert submit_logs[0].resource_id == job_id
    assert submit_logs[0].user_id == user.id
    assert submit_logs[0].detail["task_type"] == "summary"


async def test_submit_unregistered_task_type_400(session):
    """未注册 task_type -> 400：未交付二类（relation_mapping）与非法字符串均拦在边界。"""
    _, token = await _seed_actor(session, "badtype", {Permission.ANALYZE})
    async with _make_client(session) as c:
        resp = await c.post(
            "/analysis/tasks", json={"task_type": "relation_mapping"}, headers=_auth(token)
        )
        assert resp.status_code == 400, resp.text
        resp2 = await c.post(
            "/analysis/tasks", json={"task_type": "nonsense"}, headers=_auth(token)
        )
        assert resp2.status_code == 400, resp2.text


async def test_submit_qa_without_question_400(session):
    """qa 缺 question（或空白）-> 400。"""
    user, token = await _seed_actor(session, "qa-noq", {Permission.ANALYZE})
    await get_app_stores().vector_store.upsert_chunks(
        [_chunk("a.md#0", user.id, doc_id="a.md", content="材料。", metadata={})]
    )
    async with _make_client(session) as c:
        resp = await c.post("/analysis/tasks", json={"task_type": "qa"}, headers=_auth(token))
        assert resp.status_code == 400, resp.text
        resp2 = await c.post(
            "/analysis/tasks",
            json={"task_type": "qa", "question": "   "},
            headers=_auth(token),
        )
        assert resp2.status_code == 400, resp2.text


async def test_submit_custom_requires_instruction_400(session):
    """custom 缺 instruction -> 400；带 instruction 亦 400（交付留 Task 22，2026-W44）。"""
    _, token = await _seed_actor(session, "custom", {Permission.ANALYZE})
    async with _make_client(session) as c:
        resp = await c.post("/analysis/tasks", json={"task_type": "custom"}, headers=_auth(token))
        assert resp.status_code == 400, resp.text
        resp2 = await c.post(
            "/analysis/tasks",
            json={"task_type": "custom", "custom": {"instruction": "  "}},
            headers=_auth(token),
        )
        assert resp2.status_code == 400, resp2.text
        resp3 = await c.post(
            "/analysis/tasks",
            json={"task_type": "custom", "custom": {}},
            headers=_auth(token),
        )
        assert resp3.status_code == 400, resp3.text
        # 完整合法的 custom 请求：类型未注册（交付留 Task 22）-> 400 可读
        resp4 = await c.post(
            "/analysis/tasks",
            json={"task_type": "custom", "custom": {"instruction": "提取风险点"}},
            headers=_auth(token),
        )
        assert resp4.status_code == 400, resp4.text


async def test_submit_doc_ids_invisible_400_no_existence_leak(session):
    """doc_ids 含不可见项 -> 400，且报错不泄漏不可见文档的存在性细节。"""
    user_a, _token_a = await _seed_actor(session, "ownerA", {Permission.ANALYZE})
    _, token_b = await _seed_actor(session, "readerB", {Permission.ANALYZE})
    await get_app_stores().vector_store.upsert_chunks(
        [
            _chunk("alpha.md#0", user_a.id, doc_id="alpha.md", content="甲。", metadata={}),
        ]
    )
    async with _make_client(session) as c:
        # B 提交 A 的 personal 文档 -> 400
        resp = await c.post(
            "/analysis/tasks",
            json={"task_type": "summary", "doc_ids": ["alpha.md"]},
            headers=_auth(token_b),
        )
        assert resp.status_code == 400, resp.text
        assert "alpha.md" not in resp.json()["detail"]  # 不泄漏存在性细节
        # 不存在的文档同样 400（与不可见同口径，不暴露存在性差异）
        resp2 = await c.post(
            "/analysis/tasks",
            json={"task_type": "summary", "doc_ids": ["ghost.md"]},
            headers=_auth(token_b),
        )
        assert resp2.status_code == 400, resp2.text
        assert "ghost.md" not in resp2.json()["detail"]


async def test_submit_malformed_body_422(session):
    """请求体 pydantic 校验失败 -> 422（字段类型错误 / 缺 task_type）。"""
    _, token = await _seed_actor(session, "malformed", {Permission.ANALYZE})
    async with _make_client(session) as c:
        resp = await c.post(
            "/analysis/tasks",
            json={"task_type": "summary", "top_k": "abc"},
            headers=_auth(token),
        )
        assert resp.status_code == 422, resp.text
        resp2 = await c.post("/analysis/tasks", json={}, headers=_auth(token))
        assert resp2.status_code == 422, resp2.text


async def test_submit_llm_missing_key_503(session):
    """非豁免 LLM 缺 key -> 503（引擎构建期 RuntimeError -> 请求侧判定，同 ingest 惯例）。"""
    _, token = await _seed_actor(session, "nokey", {Permission.ANALYZE})
    base = get_settings()
    nokey_settings = base.model_copy(
        update={
            "llm_model": "openai/gpt-4o-mini",
            "llm_api_key": None,
            "llm_api_base": "https://api.openai.com/v1",
            "embedding_provider": "hash",
            "analysis_model": "",
        }
    )
    async with _make_client(session, settings=nokey_settings) as c:
        resp = await c.post("/analysis/tasks", json={"task_type": "summary"}, headers=_auth(token))
    assert resp.status_code == 503, resp.text


# ---------------------------------------------------------------------------
# 端到端：QA 类经桩 SearchEngine（依赖覆盖注入）
# ---------------------------------------------------------------------------


async def test_submit_qa_e2e_via_stub_search_engine(session):
    """QA 提交 -> 202 -> succeeded -> 报告详情含 question / answer / citations。"""
    user, token = await _seed_actor(session, "qa-e2e", {Permission.ANALYZE})
    await get_app_stores().vector_store.upsert_chunks(
        [_chunk("alpha.md#0", user.id, doc_id="alpha.md", content="材料。", metadata={})]
    )
    async with _make_client(session, search_engine=_StubSearchEngine()) as c:
        resp = await c.post(
            "/analysis/tasks",
            json={"task_type": "qa", "question": "什么是 OpenAI？", "top_k": 3},
            headers=_auth(token),
        )
        assert resp.status_code == 202, resp.text
        job = (await c.get(f"/jobs/{resp.json()['job_id']}", headers=_auth(token))).json()
        assert job["status"] == "succeeded", job
        detail = (await c.get(f"/analysis/reports/{job['report_id']}", headers=_auth(token))).json()
        assert detail["task_type"] == "qa"
        assert detail["prompt_version"] == "qa.v1"
        assert detail["payload"]["question"] == "什么是 OpenAI？"
        assert "Answer to" in detail["payload"]["answer"]
        assert detail["payload"]["citations"] == ["alpha.md#0"]


# ---------------------------------------------------------------------------
# 历史列表：三维过滤 + 分页；读取侧 401 / 403
# ---------------------------------------------------------------------------


async def test_reports_listing_requires_auth_and_permission(session):
    """读取侧守卫：无 token -> 401；无 analyze -> 403。"""
    _, token = await _seed_actor(session, "readnoperm", {Permission.QUERY})
    async with _make_client(session) as c:
        assert (await c.get("/analysis/reports")).status_code == 401
        assert (await c.get("/analysis/reports", headers=_auth(token))).status_code == 403


async def test_reports_listing_owner_isolation_and_pagination(session):
    """三维过滤：personal 报告他人不可见；limit/offset 分页 + total 恒为可见总数。"""
    user_a, token_a = await _seed_actor(session, "histA", {Permission.ANALYZE})
    user_b, token_b = await _seed_actor(session, "histB", {Permission.ANALYZE})
    for task_type in ("summary", "timeline", "qa"):
        await _create_report_row(session, user_id=user_a.id, task_type=task_type)
    await _create_report_row(session, user_id=user_b.id, task_type="summary")
    async with _make_client(session) as c:
        page_all = (await c.get("/analysis/reports", headers=_auth(token_a))).json()
        assert page_all["total"] == 3
        assert {i["task_type"] for i in page_all["items"]} == {"summary", "timeline", "qa"}

        page1 = (await c.get("/analysis/reports?limit=2&offset=0", headers=_auth(token_a))).json()
        page2 = (await c.get("/analysis/reports?limit=2&offset=2", headers=_auth(token_a))).json()
        assert len(page1["items"]) == 2 and page1["total"] == 3
        assert len(page2["items"]) == 1 and page2["total"] == 3
        ids_all = {i["id"] for i in page_all["items"]}
        assert {i["id"] for i in page1["items"]} | {i["id"] for i in page2["items"]} == ids_all

        # B 只见自己的报告（personal 隔离）
        page_b = (await c.get("/analysis/reports", headers=_auth(token_b))).json()
        assert page_b["total"] == 1
        assert page_b["items"][0]["task_type"] == "summary"


# ---------------------------------------------------------------------------
# 报告详情：不可见 / 不存在 / 低 clearance -> 404（不暴露存在性）
# ---------------------------------------------------------------------------


async def test_report_detail_other_user_404(session):
    """他人报告详情 -> 404（不泄漏存在性）；随机 UUID 亦 404。"""
    user_a, token_a = await _seed_actor(session, "detailA", {Permission.ANALYZE})
    _, token_b = await _seed_actor(session, "detailB", {Permission.ANALYZE})
    report = await _create_report_row(session, user_id=user_a.id)
    async with _make_client(session) as c:
        assert (
            await c.get(f"/analysis/reports/{report.id}", headers=_auth(token_b))
        ).status_code == 404
        assert (
            await c.get(f"/analysis/reports/{uuid.uuid4()}", headers=_auth(token_a))
        ).status_code == 404
        # 本人可见
        assert (
            await c.get(f"/analysis/reports/{report.id}", headers=_auth(token_a))
        ).status_code == 200


async def test_report_detail_low_clearance_404(session):
    """低 clearance 连本人报告也不可见（密级不洗白）-> 404；列表同步不可见。"""
    user, token = await _seed_actor(session, "lowclr", {Permission.ANALYZE})
    report = await _create_report_row(session, user_id=user.id, access_level=ClearanceLevel.SECRET)
    # 提交后降级：模拟权限变化的二次把关
    row = await session.get(User, user.id)
    row.clearance = ClearanceLevel.PUBLIC
    await session.commit()
    async with _make_client(session) as c:
        assert (
            await c.get(f"/analysis/reports/{report.id}", headers=_auth(token))
        ).status_code == 404
        listing = (await c.get("/analysis/reports", headers=_auth(token))).json()
        assert listing["total"] == 0


# ---------------------------------------------------------------------------
# 可见文档清单：按 doc_id 聚合（label 回退 / 密级取 max / 块数）
# ---------------------------------------------------------------------------


async def test_documents_requires_auth_and_permission(session):
    """文档清单守卫：无 token -> 401；无 analyze -> 403。"""
    _, token = await _seed_actor(session, "docsnoperm", {Permission.QUERY})
    async with _make_client(session) as c:
        assert (await c.get("/analysis/documents")).status_code == 401
        assert (await c.get("/analysis/documents", headers=_auth(token))).status_code == 403


async def test_documents_aggregates_visible_docs(session):
    """按 doc_id 聚合：仅本人可见文档；label 取标题或回退；密级取 max；块数正确。"""
    user_a, token_a = await _seed_actor(session, "docsA", {Permission.ANALYZE})
    user_b, token_b = await _seed_actor(session, "docsB", {Permission.ANALYZE})
    await get_app_stores().vector_store.upsert_chunks(
        [
            _chunk(
                "alpha.md#0",
                user_a.id,
                doc_id="alpha.md",
                content="甲一。",
                metadata={"title": "Alpha 文档"},
            ),
            _chunk(
                "alpha.md#1",
                user_a.id,
                doc_id="alpha.md",
                content="甲二。",
                metadata={"title": "Alpha 文档"},
            ),
            _chunk(
                "beta.md#0",
                user_a.id,
                doc_id="beta.md",
                content="乙（高密块）。",
                access_level=ClearanceLevel.CONFIDENTIAL,
                metadata={},  # 无标题 -> label 回退 doc_id
            ),
            _chunk("gamma.md#0", user_b.id, doc_id="gamma.md", content="他人块。", metadata={}),
        ]
    )
    async with _make_client(session) as c:
        docs_a = (await c.get("/analysis/documents", headers=_auth(token_a))).json()
        assert docs_a == [
            {
                "doc_id": "alpha.md",
                "label": "Alpha 文档",
                "access_level": "INTERNAL",
                "chunk_count": 2,
            },
            {
                "doc_id": "beta.md",
                "label": "beta.md",
                "access_level": "CONFIDENTIAL",
                "chunk_count": 1,
            },
        ]
        docs_b = (await c.get("/analysis/documents", headers=_auth(token_b))).json()
        assert docs_b == [
            {
                "doc_id": "gamma.md",
                "label": "gamma.md",
                "access_level": "INTERNAL",
                "chunk_count": 1,
            }
        ]


# ---------------------------------------------------------------------------
# 三角色提交 / 读取矩阵（决策 1：analyst / reviewer / admin 均持 analyze）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role_name", ["analyst", "reviewer", "admin"])
async def test_three_role_submit_matrix(session, role_name):
    """三角色均可提交（决策 1）-> 202 + succeeded；报告 personal 隔离（含 admin）。"""
    user, token = await _seed_role_user(
        session, f"user-{role_name}", role_name, ClearanceLevel.SECRET
    )
    await get_app_stores().vector_store.upsert_chunks(
        [_chunk("a.md#0", user.id, doc_id="a.md", content="材料。", metadata={})]
    )
    async with _make_client(session) as c:
        resp = await c.post("/analysis/tasks", json={"task_type": "summary"}, headers=_auth(token))
        assert resp.status_code == 202, resp.text
        job = (await c.get(f"/jobs/{resp.json()['job_id']}", headers=_auth(token))).json()
        assert job["status"] == "succeeded", job
        listing = (await c.get("/analysis/reports", headers=_auth(token))).json()
        assert listing["total"] == 1


async def test_admin_cannot_read_others_personal_reports(session):
    """personal 报告隔离对 admin 同样生效：列表不含、详情 404。"""
    user_a, token_a = await _seed_actor(session, "matrixA", {Permission.ANALYZE})
    _admin, token_admin = await _seed_role_user(
        session, "matrix-admin", "admin", ClearanceLevel.SECRET
    )
    report = await _create_report_row(session, user_id=user_a.id)
    async with _make_client(session) as c:
        listing = (await c.get("/analysis/reports", headers=_auth(token_admin))).json()
        assert listing["total"] == 0
        assert (
            await c.get(f"/analysis/reports/{report.id}", headers=_auth(token_admin))
        ).status_code == 404
        # A 自己仍可见
        assert (
            await c.get(f"/analysis/reports/{report.id}", headers=_auth(token_a))
        ).status_code == 200


# ---------------------------------------------------------------------------
# 报告导出：EXPORT 权限首次消费（P6 Task 15）
# ---------------------------------------------------------------------------


async def test_export_requires_auth_and_export_permission(session):
    """导出守卫：无 token -> 401；有 analyze 无 export -> 403；守卫仅 EXPORT。"""
    user_a, token_a = await _seed_actor(session, "export-analyze", {Permission.ANALYZE})
    report_a = await _create_report_row(session, user_id=user_a.id)
    user_e, token_e = await _seed_actor(session, "export-only", {Permission.EXPORT})
    report_e = await _create_report_row(session, user_id=user_e.id)
    async with _make_client(session) as c:
        assert (await c.get(f"/analysis/reports/{report_a.id}/export")).status_code == 401
        # 缺 export：即使报告本人可见亦 403（权限门控先于可见性）
        assert (
            await c.get(f"/analysis/reports/{report_a.id}/export", headers=_auth(token_a))
        ).status_code == 403
        # 无 analyze 但持 export：守卫仅 EXPORT，可见报告可导出
        assert (
            await c.get(f"/analysis/reports/{report_e.id}/export", headers=_auth(token_e))
        ).status_code == 200


async def test_export_invisible_or_missing_404(session):
    """不可见 / 不存在 -> 404（不泄漏存在性）：他人报告 / 随机 UUID / 低 clearance 本人报告。"""
    user_a, _ = await _seed_actor(session, "exportA", {Permission.ANALYZE, Permission.EXPORT})
    _, token_b = await _seed_actor(session, "exportB", {Permission.ANALYZE, Permission.EXPORT})
    report = await _create_report_row(session, user_id=user_a.id)
    async with _make_client(session) as c:
        assert (
            await c.get(f"/analysis/reports/{report.id}/export", headers=_auth(token_b))
        ).status_code == 404
        assert (
            await c.get(f"/analysis/reports/{uuid.uuid4()}/export", headers=_auth(token_b))
        ).status_code == 404
    # 低 clearance 连本人报告也不可导出（密级不洗白）
    row = await session.get(User, user_a.id)
    row.clearance = ClearanceLevel.PUBLIC
    await session.commit()
    async with _make_client(session) as c:
        assert (
            await c.get(f"/analysis/reports/{report.id}/export", headers=_auth(_token(user_a)))
        ).status_code == 404


async def test_export_json_default_attachment_and_audit(session):
    """默认 json：200 + Content-Disposition 附件文件名 + 内容与落库信封一致 + 审计。"""
    user, token = await _seed_actor(session, "export-json", {Permission.ANALYZE, Permission.EXPORT})
    report = await _create_report_row(session, user_id=user.id)
    report_id = report.id
    async with _make_client(session) as c:
        resp = await c.get(f"/analysis/reports/{report_id}/export", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert f'filename="analysis_report_summary_{report_id}.json"' in disposition
    assert resp.headers["content-type"].startswith("application/json")
    # 内容与落库信封一致（全量信封直出）
    stored = (
        (await session.execute(select(AnalysisReportORM).where(AnalysisReportORM.id == report_id)))
        .scalars()
        .one()
    )
    assert resp.json() == stored.payload
    # 审计：report_export（resource_type=analysis_report，detail 含 format / task_type）
    logs = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "report_export")))
        .scalars()
        .all()
    )
    assert len(logs) == 1
    log = logs[0]
    assert log.resource_type == "analysis_report"
    assert log.resource_id == str(report_id)
    assert log.user_id == user.id
    assert log.detail["format"] == "json"
    assert log.detail["task_type"] == "summary"


async def test_export_md_sectioned_with_evidence(session):
    """format=md：200 附件 .md；按 JSON 分节渲染（不返回大段自由文本）+ 证据引用标注 + 审计。"""
    user, token = await _seed_actor(session, "export-md", {Permission.ANALYZE, Permission.EXPORT})
    report = await _create_report_row(
        session,
        user_id=user.id,
        evidence=[{"chunk_id": "alpha.md#0", "quote": "阿尔法文档第一块。", "confidence": 0.9}],
    )
    report_id = report.id
    async with _make_client(session) as c:
        resp = await c.get(f"/analysis/reports/{report_id}/export?format=md", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert f'filename="analysis_report_summary_{report_id}.md"' in disposition
    assert resp.headers["content-type"].startswith("text/markdown")
    text = resp.text
    # 报告信息元数据节
    assert "# 分析报告（summary）" in text
    assert "## 报告信息" in text
    assert "- 分析对象：Alpha 文档" in text
    assert "- 报告状态：ok" in text
    assert "- 材料块：alpha.md#0" in text
    # 报告内容按 payload 顶层键分节（结构化映射，不重写为自由文本）
    assert "## 报告内容" in text
    assert "### summary" in text
    assert "桩摘要" in text
    assert "### key_points" in text
    assert "- 要点甲" in text
    # 证据引用标注（chunk_id + 原文引文 + 置信）
    assert "### evidence" in text
    assert "1. [alpha.md#0] 「阿尔法文档第一块。」（置信 0.90）" in text
    # 审计记 md 格式
    logs = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "report_export")))
        .scalars()
        .all()
    )
    assert len(logs) == 1
    assert logs[0].detail["format"] == "md"


async def test_export_invalid_format_422(session):
    """format 越出 json / md -> 422（查询参数 Literal 校验）。"""
    user, token = await _seed_actor(session, "export-fmt", {Permission.EXPORT})
    report = await _create_report_row(session, user_id=user.id)
    async with _make_client(session) as c:
        resp = await c.get(
            f"/analysis/reports/{report.id}/export?format=docx", headers=_auth(token)
        )
    assert resp.status_code == 422, resp.text


def test_render_report_markdown_sections_and_evidence():
    """渲染纯函数（无 db 夹具，CI 可跑）：元信息节 + payload 分节 + 证据引用标注 + 条目内联标注。"""
    report_id = uuid.uuid4()
    envelope = json_safe(
        AnalysisEnvelope(
            task_type="summary",
            status="partial",
            generated_at=datetime.now(UTC),
            model="test/stub",
            prompt_version="summary.v1",
            usage={"total_tokens": 3},
            warnings=["证据失配占比超阈值"],
            source_chunk_ids=["alpha.md#0", "alpha.md#1"],
            payload={
                "summary": "桩摘要",
                "key_points": ["要点甲", "要点乙"],
                "confidence": 0.3,
                "evidence": [
                    {"chunk_id": "alpha.md#0", "quote": "阿尔法文档第一块。", "confidence": 0.9}
                ],
            },
        ).model_dump()
    )
    md = render_report_markdown(report_id=report_id, subject_label="Alpha 文档", envelope=envelope)
    assert md.startswith("# 分析报告（summary）")
    assert f"- 报告 ID：{report_id}" in md
    assert "- 分析对象：Alpha 文档" in md
    assert "- 报告状态：partial" in md
    assert "- Token 用量：total_tokens=3" in md
    assert "- 告警：证据失配占比超阈值" in md
    assert "- 材料块：alpha.md#0；alpha.md#1" in md
    assert "## 报告内容" in md
    assert "### summary" in md
    assert "桩摘要" in md
    assert "### key_points" in md
    assert "- 要点甲" in md and "- 要点乙" in md
    assert "1. [alpha.md#0] 「阿尔法文档第一块。」（置信 0.90）" in md

    # 条目形态（key_information）：逐条 #### 分节 + 证据内联标注；空证据 -> 「（无证据引用）」
    envelope_items = json_safe(
        AnalysisEnvelope(
            task_type="key_information",
            status="ok",
            generated_at=datetime.now(UTC),
            model="test/stub",
            prompt_version="key_information.v1",
            usage={},
            warnings=[],
            source_chunk_ids=[],
            payload={
                "items": [
                    {
                        "label": "时间",
                        "value": "2026年8月29日",
                        "confidence": 0.8,
                        "evidence": [{"chunk_id": "a.md#0", "quote": "引文", "confidence": 1.0}],
                    },
                    {"label": "地点", "value": "北京", "confidence": 0.2, "evidence": []},
                ]
            },
        ).model_dump()
    )
    md2 = render_report_markdown(report_id=uuid.uuid4(), subject_label="X", envelope=envelope_items)
    assert "#### 条目 1" in md2 and "#### 条目 2" in md2
    assert "- label: 时间" in md2
    assert "- evidence: [a.md#0] 「引文」（置信 1.00）" in md2
    assert "- evidence: （无证据引用）" in md2
    assert "- Token 用量：（无）" in md2
    assert "- 材料块：（无）" in md2


# ---------------------------------------------------------------------------
# 双挂：根路径 + /api 前缀
# ---------------------------------------------------------------------------


async def test_api_prefix_dual_mount(session):
    """/api 前缀与根路径同权可用（前端 baseURL=/api）。"""
    user, token = await _seed_actor(session, "dualmount", {Permission.ANALYZE})
    await get_app_stores().vector_store.upsert_chunks(
        [_chunk("a.md#0", user.id, doc_id="a.md", content="材料。", metadata={})]
    )
    async with _make_client(session) as c:
        resp = await c.post(
            "/api/analysis/tasks", json={"task_type": "summary"}, headers=_auth(token)
        )
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        job = (await c.get(f"/api/jobs/{job_id}", headers=_auth(token))).json()
        assert job["status"] == "succeeded", job
        listing = (await c.get("/api/analysis/reports", headers=_auth(token))).json()
        assert listing["total"] == 1
        docs = (await c.get("/api/analysis/documents", headers=_auth(token))).json()
        assert [d["doc_id"] for d in docs] == ["a.md"]
