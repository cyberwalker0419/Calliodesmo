"""/analysis 端点：分析任务提交 202 + 报告历史 / 详情 + 导出 + 可见文档清单（P6 Task 14/15）。

提交侧 1:1 复刻 ingest 范式（``api/ingest.py``）：

```text
require_permission(ANALYZE) → 请求边界校验（400 类）→ build_analysis_engine
（RuntimeError→503 / ValueError→400，同 ingest 惯例）→ Job(pending,
task_type="analyze", task_payload=json_safe(spec)) → record_audit(analyze_submit,
resource_type="job") → commit → BackgroundTasks.add_task(run_analysis_job) → 202
```

- **无中央分发器**：直接排入 ``analysis/job_worker.run_analysis_job``（经
  ``Depends(get_job_session_factory)`` 取工厂，测试可 override 指向测试 schema）；
- QA 类 ``SearchEngine`` 经 ``Depends(get_search_engine)`` 注入后随
  ``build_analysis_engine`` 构造注入引擎（不得在引擎内直调 ``api/deps``，
  见 ``analysis/factory.py`` 模块注记）；
- 报告历史 / 详情经 ``AnalysisReportStore`` + ``visible_to`` 三维过滤：
  报告固定 personal scope（owner=提交者，决策 2/4）——他人不可见（含 admin）；
  低 clearance 连本人报告也不可见（密级不洗白）；不可见 / 不存在一律 404（不泄漏存在性）；
- 报告导出（Task 15）**首次消费 ``export`` 权限**（守卫仅 EXPORT，不复用 analyze）：
  默认 json 附件（全量信封直出）；``?format=md`` 按信封 JSON 分节渲染
  （``render_report_markdown`` 纯函数：结构化映射，不重写为大段自由文本，
  证据列表渲染为 ``[chunk_id] 「引文」（置信 x.xx）`` 引用标注）；审计 ``report_export``；
  文件名 ASCII 稳定（``analysis_report_<task_type>_<report_id>.<ext>``，
  不落中文文件名，免 RFC 5987 ``filename*`` 转义）；
- ``GET /analysis/documents`` 为 Task 19 MaterialPicker 数据源：``list_chunks`` +
  ``visible_to`` 按 ``doc_id`` 聚合（红线一：逐条复核可见性，不凭客户端 ID 直取）。

错误码一览（计划「API 契约」）：401 未认证；403 缺 ``analyze``（导出缺 ``export``）；
400 未注册 task_type / qa 缺 question / custom 缺 instruction / doc_ids 含不可见项；
422 请求体 pydantic 校验失败（含导出 ``format`` 越出 json / md）；
503 模型缺 key（``RuntimeError``）；404 报告不可见或不存在。

审计点：``analyze_submit``（本模块，提交侧，``resource_type="job"``）；``analyze``
（worker 终态，``analysis/job_worker.py``）；``report_export``（本模块，导出侧，
``resource_type="analysis_report"``）。

**回滚方式**：摘除 ``create_app`` 中本 router 挂载即整体下线，零数据影响。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.analysis.factory import build_analysis_engine
from calliodesmo.analysis.job_worker import run_analysis_job
from calliodesmo.analysis.report_store import AnalysisReportStore
from calliodesmo.analysis.schemas import AnalysisEnvelope, AnalysisType
from calliodesmo.analysis.specs import get_spec
from calliodesmo.api.deps import (
    get_app_stores,
    get_current_context,
    get_job_session_factory,
    get_search_engine,
    require_permission,
)
from calliodesmo.api.schemas import (
    AnalysisAcceptedOut,
    AnalysisDocumentOut,
    AnalysisJobRequest,
    AnalysisReportListItem,
    AnalysisReportListOut,
)
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import Permission
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.models_analysis import AnalysisReportORM
from calliodesmo.db.models_job import Job, JobStatus
from calliodesmo.db.session import get_session
from calliodesmo.interfaces.retriever import SearchEngine
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.stores.visibility import visible_to
from calliodesmo.utils.json import json_safe

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/tasks", response_model=AnalysisAcceptedOut, status_code=status.HTTP_202_ACCEPTED)
async def submit_analysis_task(
    req: AnalysisJobRequest,
    background_tasks: BackgroundTasks,
    ctx: AccessContext = Depends(get_current_context),
    stores=Depends(get_app_stores),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    session_factory=Depends(get_job_session_factory),
    search_engine: SearchEngine = Depends(get_search_engine),
) -> AnalysisAcceptedOut:
    """提交分析任务 -> 建 analyze job（pending）-> BackgroundTasks 异步执行 -> 202。

    请求边界校验（400 类，先于建 job）：task_type 未注册 / qa 缺 question /
    custom 缺 instruction / doc_ids 含不可见项（不泄漏不可见文档存在性细节）。
    引擎在请求边界构建：``RuntimeError``（LLM 缺 key 等）-> 503、``ValueError`` -> 400
    （同 ingest 惯例）；``task_payload`` 写入前过 ``json_safe``。
    """
    require_permission(ctx, Permission.ANALYZE)

    # -- 请求边界校验（400 类）--
    try:
        task_type = AnalysisType(req.task_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"未注册的分析类型：{req.task_type}",
        ) from None
    if task_type is AnalysisType.QA and not (req.question or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="qa 分析需要 question（不得为空）",
        )
    if task_type is AnalysisType.CUSTOM:
        if req.custom is None or not req.custom.instruction.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="custom 分析需要 custom.instruction（不得为空）",
            )
        # TODO(P6 Task 22, 2026-W44)：custom 分支——sanitize_user_schema（拒 $ref / 递归 /
        # 超深 / 超大）+ build_custom_spec 注册 + 指令注入防御；此前一律 400 未交付。
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="自定义分析尚未交付（P6 Task 22，2026-W44：sanitize 与注入防御先行）",
        )
    try:
        get_spec(task_type)  # 注册表校验：未交付类型天然不可提交（KeyError -> 400）
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"未注册的分析类型：{task_type.value}",
        ) from None
    if req.doc_ids:
        # 红线一：逐条过 visible_to（不凭客户端 ID 直取）；报错不点名、不泄漏存在性细节
        chunks = await stores.vector_store.list_chunks(access=ctx)
        visible_docs = {c.doc_id for c in chunks if visible_to(c, ctx)}
        if any(doc_id not in visible_docs for doc_id in req.doc_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="doc_ids 含不可见文档，请核对选择范围",
            )

    # -- 引擎请求边界构建：同 ingest 惯例（503 / 400 判定留在请求侧）--
    try:
        engine = build_analysis_engine(settings, search_engine=search_engine)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    # -- 建 job 行（pending）+ 审计受理，再排后台任务（顺序：先落库后调度，同 ingest）--
    payload = json_safe(
        {
            "task_type": task_type.value,
            "doc_ids": list(req.doc_ids),
            "question": req.question or "",
            "custom_instruction": req.custom.instruction if req.custom else "",
            "custom_schema": req.custom.schema_ if req.custom else None,
            "top_k": req.top_k,
        }
    )
    job = Job(user_id=ctx.user_id, task_type="analyze", task_payload=payload)
    session.add(job)
    await session.flush()
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="analyze_submit",
        resource_type="job",
        resource_id=str(job.id),
        detail={"task_type": task_type.value, "doc_ids_count": len(req.doc_ids)},
        source="api",
    )
    await session.commit()
    job_id: uuid.UUID = job.id
    background_tasks.add_task(
        run_analysis_job, job_id, engine=engine, session_factory=session_factory
    )
    return AnalysisAcceptedOut(
        job_id=job_id, status=JobStatus.PENDING.value, task_type=task_type.value
    )


@router.get("/reports", response_model=AnalysisReportListOut)
async def list_reports(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> AnalysisReportListOut:
    """报告历史：ANALYZE 门控 + ``visible_to`` 三维过滤 + limit/offset 分页。

    报告固定 personal scope：仅本人可见（含 admin 亦不可读他人报告）；
    ``total`` 为过滤后全部可见行数（供前端分页器）。
    """
    require_permission(ctx, Permission.ANALYZE)
    items, total = await AnalysisReportStore().list_visible(
        session, access=ctx, limit=limit, offset=offset
    )
    return AnalysisReportListOut(items=[_report_item(r) for r in items], total=total)


@router.get("/reports/{report_id}", response_model=AnalysisEnvelope)
async def get_report(
    report_id: uuid.UUID,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> AnalysisEnvelope:
    """报告详情：不可见 / 不存在一律 404（不泄漏存在性）；出参直接取信封。"""
    require_permission(ctx, Permission.ANALYZE)
    report = await AnalysisReportStore().get(session, report_id, access=ctx)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"报告不存在或不可见: {report_id}"
        )
    return AnalysisEnvelope.model_validate(report.payload)


@router.get("/reports/{report_id}/export")
async def export_report(
    report_id: uuid.UUID,
    format: Literal["json", "md"] = Query(
        default="json", description="导出格式：json（默认，全量信封）/ md（按 JSON 分节渲染）"
    ),
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """报告导出（附件下载）：``export`` 权限首次消费（守卫仅 EXPORT）。

    可见性与详情同口径：不可见 / 不存在一律 404（不泄漏存在性）。先审计
    ``report_export``（``resource_type="analysis_report"``，detail 含 format /
    task_type）再落响应。默认 json 附件直出全量信封；``format=md`` 经
    ``render_report_markdown`` 按信封 JSON 分节渲染（不返回大段自由文本，
    含证据引用标注）。文件名 ASCII 稳定：
    ``analysis_report_<task_type>_<report_id>.<ext>``。
    """
    require_permission(ctx, Permission.EXPORT)
    report = await AnalysisReportStore().get(session, report_id, access=ctx)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"报告不存在或不可见: {report_id}"
        )
    # 提交前先取字段（避免 commit 后属性过期的隐式刷新）
    report_task_type = report.task_type
    subject_label = report.subject_label
    payload = report.payload
    await record_audit(
        session,
        user_id=ctx.user_id,
        action="report_export",
        resource_type="analysis_report",
        resource_id=str(report_id),
        detail={"format": format, "task_type": report_task_type},
        source="api",
    )
    await session.commit()
    filename = f"analysis_report_{report_task_type}_{report_id}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if format == "md":
        body = render_report_markdown(
            report_id=report_id, subject_label=subject_label, envelope=payload
        )
        return Response(content=body, media_type="text/markdown; charset=utf-8", headers=headers)
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers=headers,
    )


@router.get("/documents", response_model=list[AnalysisDocumentOut])
async def list_documents(
    ctx: AccessContext = Depends(get_current_context),
    stores=Depends(get_app_stores),
) -> list[AnalysisDocumentOut]:
    """可见文档清单（Task 19 MaterialPicker 数据源）：按 ``doc_id`` 聚合。

    ``list_chunks`` 全量拉取 + ``visible_to`` 逐条复核（红线一）；``label`` 取
    metadata 标题或回退 doc_id；``access_level`` 取该文档全部可见块密级最大值
    （``ClearanceLevel.name``）；``chunk_count`` 为可见块数。
    """
    require_permission(ctx, Permission.ANALYZE)
    chunks = [c for c in await stores.vector_store.list_chunks(access=ctx) if visible_to(c, ctx)]
    by_doc: dict[str, list[ChunkRecord]] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.doc_id, []).append(chunk)
    return [
        AnalysisDocumentOut(
            doc_id=doc_id,
            label=_document_label(doc_id, by_doc[doc_id]),
            access_level=max(c.access_level for c in by_doc[doc_id]).name,
            chunk_count=len(by_doc[doc_id]),
        )
        for doc_id in sorted(by_doc)
    ]


# ---------------------------------------------------------------------------
# Markdown 导出渲染（Task 15）：按信封 JSON 分节的纯函数
# ---------------------------------------------------------------------------

#: 报告信息节中无值占位（与证据缺失占位区分：后者为「无证据引用」）
_EXPORT_EMPTY = "（无）"


def render_report_markdown(*, report_id: uuid.UUID, subject_label: str, envelope: dict) -> str:
    """按信封 JSON 分节渲染 Markdown（导出 ``?format=md`` 用，纯函数离线可测）。

    纪律：**结构化映射，不重写为大段自由文本**——报告信息取信封元字段为列表项，
    报告内容按 ``payload`` 顶层键逐节展开（``### <键名>``）；证据列表（键名
    ``evidence``）渲染为引用标注 ``[chunk_id] 「引文」（置信 x.xx）``。

    参数:
        report_id: 报告行 ID（写入报告信息节与调用方文件名一致）。
        subject_label: 分析对象描述（报告行 ``subject_label``）。
        envelope: 完整信封 dict（报告行 ``payload`` 列，json_safe 形态）。
    """
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    lines: list[str] = [
        f"# 分析报告（{envelope.get('task_type', '未知类型')}）",
        "",
        "## 报告信息",
        "",
        f"- 报告 ID：{report_id}",
        f"- 分析对象：{subject_label}",
        f"- 报告状态：{envelope.get('status', '未知')}",
        f"- 生成时间：{envelope.get('generated_at', _EXPORT_EMPTY)}",
        f"- 模型：{envelope.get('model', _EXPORT_EMPTY)}",
        f"- 提示词版本：{envelope.get('prompt_version', _EXPORT_EMPTY)}",
        f"- Token 用量：{_usage_text(envelope.get('usage'))}",
        f"- 告警：{_list_join(envelope.get('warnings'))}",
        f"- 材料块：{_list_join(envelope.get('source_chunk_ids'))}",
        "",
        "## 报告内容",
        "",
    ]
    if not payload:
        lines.append(_EXPORT_EMPTY)
    for key, value in payload.items():
        lines.append(f"### {key}")
        lines.append("")
        if key == "evidence":
            lines.extend(_render_evidence(value))
        else:
            lines.extend(_render_value(value))
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _usage_text(usage: Any) -> str:
    """token 用量 dict -> ``k=v`` 空格串；空 / 非 dict 占位。"""
    if not isinstance(usage, dict) or not usage:
        return _EXPORT_EMPTY
    return " ".join(f"{key}={value}" for key, value in usage.items())


def _list_join(values: Any) -> str:
    """列表 -> ``；`` 串接；空 / 非列表占位。"""
    if not isinstance(values, list) or not values:
        return _EXPORT_EMPTY
    return "；".join(str(value) for value in values)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _scalar_text(value: Any) -> str:
    """标量 -> 展示文本（None 占位 / bool 中文化 / 其余 str）。"""
    if value is None:
        return _EXPORT_EMPTY
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _confidence_text(value: Any) -> str:
    """置信度 -> 两位小数文本；非数值原样转串（容错，不崩渲染）。"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.2f}"
    return str(value)


def _evidence_entry_text(entry: Any) -> str:
    """单条证据 -> 引用标注 ``[chunk_id] 「引文」（置信 x.xx）``；异形条目转 JSON。"""
    if isinstance(entry, dict) and entry.get("chunk_id"):
        confidence = _confidence_text(entry.get("confidence", 1.0))
        return f"[{entry['chunk_id']}] 「{entry.get('quote', '')}」（置信 {confidence}）"
    return json.dumps(entry, ensure_ascii=False)


def _render_evidence(value: Any) -> list[str]:
    """证据节（顶层 ``### evidence``）：编号引用标注列表；空 -> 「无证据引用」。"""
    if not isinstance(value, list) or not value:
        return ["（无证据引用）"]
    return [f"{index}. {_evidence_entry_text(entry)}" for index, entry in enumerate(value, 1)]


def _render_value(value: Any) -> list[str]:
    """payload 值 -> 分节行（非证据键通用路径）。

    - 标量：直接文本；
    - 标量列表：``- 项`` 要点行；
    - 条目列表（dict）：``#### 条目 N`` 逐条展开（字段 ``- k: v``，
      条目内 ``evidence`` 内联为引用标注）；
    - dict：``- k: v`` 字段行（嵌套非标量值内联 JSON，保确定性）。
    """
    if _is_scalar(value):
        return [_scalar_text(value)]
    if isinstance(value, list):
        if not value:
            return [_EXPORT_EMPTY]
        if all(_is_scalar(item) for item in value):
            return [f"- {_scalar_text(item)}" for item in value]
        lines: list[str] = []
        for index, item in enumerate(value, 1):
            lines.extend([f"#### 条目 {index}", ""])
            if isinstance(item, dict):
                lines.extend(_render_entry(item))
            else:
                lines.append(json.dumps(item, ensure_ascii=False))
            lines.append("")
        while lines and lines[-1] == "":
            lines.pop()
        return lines
    if isinstance(value, dict):
        if not value:
            return [_EXPORT_EMPTY]
        return _render_entry(value)
    return [json.dumps(value, ensure_ascii=False)]


def _render_entry(entry: dict) -> list[str]:
    """dict 条目 -> ``- k: v`` 字段行；``evidence`` 内联引用标注；嵌套非标量内联 JSON。"""
    lines: list[str] = []
    for key, value in entry.items():
        if key == "evidence":
            if isinstance(value, list) and value:
                joined = "；".join(_evidence_entry_text(item) for item in value)
            else:
                joined = "（无证据引用）"
            lines.append(f"- evidence: {joined}")
        elif _is_scalar(value):
            lines.append(f"- {key}: {_scalar_text(value)}")
        else:
            lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False)}")
    return lines


def _report_item(report: AnalysisReportORM) -> AnalysisReportListItem:
    """报告行 -> 列表出参（与前端 ReportListItem 逐字段对齐）。"""
    return AnalysisReportListItem(
        id=report.id,
        task_type=report.task_type,
        status=report.status,
        subject_label=report.subject_label,
        access_level=report.access_level.name,
        library_scope=report.library_scope.value,
        model=report.model,
        created_at=report.created_at,
        source_chunk_count=report.source_chunk_count,
    )


def _document_label(doc_id: str, doc_chunks: list[ChunkRecord]) -> str:
    """文档展示标签：任一可见块的 metadata 标题 -> source_path -> 回退 doc_id。

    与 ``analysis/materials._source_label`` 约定一致（计划「前端数据契约」：
    label 取 metadata 标题或回退 doc_id）；跨块取值，不随块序漂移。
    """
    for chunk in doc_chunks:
        title = (chunk.metadata or {}).get("title")
        if isinstance(title, str) and title.strip():
            return title
    for chunk in doc_chunks:
        source_path = (chunk.metadata or {}).get("source_path")
        if isinstance(source_path, str) and source_path.strip():
            return source_path
    return doc_id
