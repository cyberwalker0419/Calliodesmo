"""/analysis 端点：分析任务提交 202 + 报告历史 / 详情 + 可见文档清单（P6 Task 14）。

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
- ``GET /analysis/documents`` 为 Task 19 MaterialPicker 数据源：``list_chunks`` +
  ``visible_to`` 按 ``doc_id`` 聚合（红线一：逐条复核可见性，不凭客户端 ID 直取）。

错误码一览（计划「API 契约」）：401 未认证；403 缺 ``analyze``；400 未注册
task_type / qa 缺 question / custom 缺 instruction / doc_ids 含不可见项；
422 请求体 pydantic 校验失败；503 模型缺 key（``RuntimeError``）；404 报告不可见或不存在。

审计点：``analyze_submit``（本模块，提交侧，``resource_type="job"``）；``analyze``
（worker 终态，``analysis/job_worker.py``）；``report_export`` 留 Task 15。

**回滚方式**：摘除 ``create_app`` 中本 router 挂载即整体下线，零数据影响。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
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
