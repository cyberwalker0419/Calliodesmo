"""P7 T8：分析桥工具——P6 报告契约直消费（reports_*）+ run_analysis 异步指针。

- reports_list / reports_get 复用 AnalysisReportStore 可见语义（personal scope，
  owner 可见；他人 404 同语义）。
- run_analysis 需 analyze 权限（自定义无 ANALYZE 的 AccessContext——三标准角色均含）；
  gather_materials 材料红线 + compute_report_access_level 复用；job_id 指针不内联明文。
"""

import uuid

import pytest

from calliodesmo.agent.errors import tool_unavailable_error
from calliodesmo.agent.registry import DefaultToolRegistry
from calliodesmo.agent.tools.analysis import ReportsGetTool, ReportsListTool, RunAnalysisTool
from calliodesmo.analysis.report_store import AnalysisReportStore
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.interfaces.agent import ToolCall
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore

OWNER = uuid.uuid4()


def _ctx(perms=frozenset({Permission.QUERY}), clearance=ClearanceLevel.SECRET):
    return AccessContext(
        user_id=OWNER,
        username="u",
        clearance=clearance,
        permissions=perms,
        library_scopes=frozenset({LibraryScope.PERSONAL}),
    )


# ---- reports_*（DB）----


async def _make_report(session, access_level=ClearanceLevel.INTERNAL, owner=OWNER):
    store = AnalysisReportStore()
    report = await store.create(
        session,
        job_id=None,
        user_id=owner,
        task_type="summary",
        status="ok",
        subject_label="全可见范围 · 摘要",
        payload={"summary": "离线桩占位摘要"},
        source_doc_ids=[],
        source_chunk_count=0,
        access_level=access_level,
        model="test/stub",
        prompt_version="v1",
        usage={},
    )
    await session.commit()
    return report


@pytest.mark.db
async def test_reports_list_and_get_visible_to_owner(session):
    report = await _make_report(session)
    access = _ctx()

    out = await ReportsListTool(session).run({}, access=access)
    assert str(report.id) in out and "summary" in out

    got = await ReportsGetTool(session).run({"report_id": str(report.id)}, access=access)
    assert "摘要" in got


@pytest.mark.db
async def test_reports_get_other_user_unified_semantics(session):
    """personal scope：他人不可见 = 不存在语义（LookupError -> 注册表统一消息）。"""
    report = await _make_report(session)
    other = AccessContext(
        user_id=uuid.uuid4(),
        username="other",
        clearance=ClearanceLevel.SECRET,
        permissions=frozenset({Permission.QUERY}),
        library_scopes=frozenset({LibraryScope.PERSONAL}),
    )
    reg = DefaultToolRegistry([ReportsGetTool(session)])

    denied = await reg.dispatch(
        ToolCall(id="c1", name="reports_get", arguments={"report_id": str(report.id)}),
        access=other,
    )
    missing = await reg.dispatch(
        ToolCall(id="c2", name="reports_get", arguments={"report_id": str(uuid.uuid4())}),
        access=other,
    )
    assert denied.error == missing.error == tool_unavailable_error()


# ---- run_analysis（离线）----


def _chunk(cid, level):
    return ChunkRecord(
        chunk_id=cid,
        doc_id=f"doc-{cid}",
        content="OpenAI 开发了 GPT-4。",
        vector=[0.0],
        access_level=level,
        library_scope=LibraryScope.PERSONAL,
        owner_id=OWNER,
    )


async def test_run_analysis_pointer_and_material_redline():
    """job_id 指针不内联明文；材料红线：INTERNAL 提交预计密级不含 SECRET 材料。"""
    store = InMemoryVectorStore()
    await store.upsert_chunks(
        [_chunk("p1", ClearanceLevel.PUBLIC), _chunk("s1", ClearanceLevel.SECRET)]
    )
    seen: dict = {}

    async def submit(task_type, doc_ids, level, access):
        seen.update(task_type=task_type, level=level, access=access)
        return "job-1"

    tool = RunAnalysisTool(store, submit=submit)

    # INTERNAL 提交：SECRET 材料被 gather_materials 剔除 -> 预计密级 INTERNAL
    out = await tool.run({"task_type": "summary"}, access=_ctx(clearance=ClearanceLevel.INTERNAL))
    assert "job_id=job-1" in out and "不内联明文" in out
    assert seen["level"] == ClearanceLevel.INTERNAL

    # SECRET 提交：材料含 SECRET -> 预计密级 SECRET（密级不洗白）
    await tool.run({"task_type": "summary"}, access=_ctx(clearance=ClearanceLevel.SECRET))
    assert seen["level"] == ClearanceLevel.SECRET


async def test_run_analysis_requires_analyze_permission():
    """无 ANALYZE 权限（自定义 ctx；三标准角色均含 ANALYZE）-> 统一消息。"""
    store = InMemoryVectorStore()

    async def submit(task_type, doc_ids, level, access):
        return "job-x"

    reg = DefaultToolRegistry([RunAnalysisTool(store, submit=submit)])
    result = await reg.dispatch(
        ToolCall(id="c1", name="run_analysis", arguments={"task_type": "summary"}),
        access=_ctx(perms=frozenset({Permission.QUERY})),
    )
    assert result.ok is False and result.error == tool_unavailable_error()


async def test_run_analysis_bad_task_type_via_param_gate():
    """参数门：task_type 枚举外拒收（schema enum）。"""
    store = InMemoryVectorStore()

    async def submit(task_type, doc_ids, level, access):
        return "job-x"

    reg = DefaultToolRegistry([RunAnalysisTool(store, submit=submit)])
    result = await reg.dispatch(
        ToolCall(id="c1", name="run_analysis", arguments={"task_type": "nope"}),
        access=_ctx(perms=frozenset({Permission.QUERY, Permission.ANALYZE})),
    )
    assert result.ok is False and "task_type" in result.error
