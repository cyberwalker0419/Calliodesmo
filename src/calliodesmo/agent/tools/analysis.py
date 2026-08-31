"""分析桥工具：reports_list / reports_get / run_analysis（P6 报告契约直消费、零返工）。

- reports_*：复用 ``AnalysisReportStore`` 可见语义（不可见返回 None -> LookupError
  由注册表收统一消息，不泄漏存在性）；``query`` 权限。
- run_analysis：``analyze`` 权限；``gather_materials`` 材料红线（全程 visible_to）+
  ``compute_report_access_level`` 纯函数复用（经工具装配，不直调 api/deps）；走 job
  范式异步返回 ``job_id`` 指针、**不内联明文**（P6 移交承诺兑现）。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from calliodesmo.agent.tools._common import join_lines, truncate
from calliodesmo.analysis.access import compute_report_access_level
from calliodesmo.analysis.materials import gather_materials
from calliodesmo.analysis.report_store import AnalysisReportStore
from calliodesmo.analysis.schemas import AnalysisType
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, Permission
from calliodesmo.interfaces.graph_store import GraphStore
from calliodesmo.interfaces.llm import ToolSpec
from calliodesmo.interfaces.vector_store import VectorStore

REPORTS_LIST_SPEC = ToolSpec(
    name="reports_list",
    description="枚举当前可见的分析报告历史（类型/状态/主题/密级）",
    parameters={
        "type": "object",
        "properties": {"limit": {"type": "integer"}, "offset": {"type": "integer"}},
        "required": [],
    },
)

REPORTS_GET_SPEC = ToolSpec(
    name="reports_get",
    description="按 report_id 取分析报告信封（不可见/不存在同一语义）",
    parameters={
        "type": "object",
        "properties": {"report_id": {"type": "string"}},
        "required": ["report_id"],
    },
)

RUN_ANALYSIS_SPEC = ToolSpec(
    name="run_analysis",
    description="提交 LLM 分析任务（九类），异步返回 job_id 指针，不内联明文",
    parameters={
        "type": "object",
        "properties": {
            "task_type": {"type": "string", "enum": [t.value for t in AnalysisType]},
            "doc_ids": {"type": "array", "items": {"type": "string"}},
            "subject_label": {"type": "string"},
        },
        "required": ["task_type"],
    },
)

#: 提交钩子：(task_type, doc_ids, 预计密级, access) -> job_id（API/worker 装配真 Job 创建）
AnalysisSubmitHook = Callable[[str, list[str], ClearanceLevel, AccessContext], Awaitable[str]]


class ReportsListTool:
    spec = REPORTS_LIST_SPEC
    required_permission = Permission.QUERY

    def __init__(self, session, *, store: AnalysisReportStore | None = None) -> None:
        self.session = session
        self.store = store or AnalysisReportStore()

    async def run(self, arguments: dict, *, access: AccessContext) -> str:
        items, total = await self.store.list_visible(
            self.session,
            access=access,
            limit=int(arguments.get("limit", 10)),
            offset=int(arguments.get("offset", 0)),
        )
        lines = [f"共 {total} 份可见报告："]
        lines += [
            f"- {r.id} [{r.task_type}/{r.status}] {r.subject_label}"
            f"（{r.access_level.name if hasattr(r.access_level, 'name') else r.access_level}）"
            for r in items
        ]
        return join_lines(lines)


class ReportsGetTool:
    spec = REPORTS_GET_SPEC
    required_permission = Permission.QUERY

    def __init__(self, session, *, store: AnalysisReportStore | None = None) -> None:
        self.session = session
        self.store = store or AnalysisReportStore()

    async def run(self, arguments: dict, *, access: AccessContext) -> str:
        try:
            report_id = uuid.UUID(arguments["report_id"])
        except ValueError:
            raise LookupError(arguments["report_id"]) from None
        report = await self.store.get(self.session, report_id, access=access)
        if report is None:
            # 不可见 / 不存在同一语义（不泄漏存在性）
            raise LookupError(arguments["report_id"])
        return join_lines(
            [
                f"报告 {report.id} [{report.task_type}/{report.status}]",
                f"主题：{report.subject_label}",
                f"信封：{truncate(str(report.payload), 2000)}",
            ]
        )


class RunAnalysisTool:
    spec = RUN_ANALYSIS_SPEC
    required_permission = Permission.ANALYZE

    def __init__(
        self,
        vector_store: VectorStore,
        *,
        submit: AnalysisSubmitHook,
        graph_store: GraphStore | None = None,
    ) -> None:
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.submit = submit

    async def run(self, arguments: dict, *, access: AccessContext) -> str:
        task_type = arguments["task_type"]
        doc_ids = list(arguments.get("doc_ids") or [])
        # 材料红线：gather_materials 全程 visible_to；预计密级经纯函数复用
        materials = await gather_materials(
            vector_store=self.vector_store,
            access=access,
            task_type=task_type,
            doc_ids=doc_ids or None,
            graph_store=self.graph_store,
        )
        level = compute_report_access_level(materials.materials)
        job_id = await self.submit(task_type, doc_ids, level, access)
        return (
            f"已提交分析任务：job_id={job_id}，类型={task_type}，"
            f"预计密级={level.name}。分析异步执行，完成后经 reports_get 取回；不内联明文。"
        )
