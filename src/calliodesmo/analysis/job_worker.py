"""分析 job worker：后台异步跑 analyze 任务，写进度分段与终态到 jobs 表。

P6 Task 13：``task_type="analyze"`` 执行体，1:1 对齐 ``ecl/job_worker.py``
``run_ingest_job`` 注入范式：

- ``run_analysis_job(job_id, *, engine, session_factory, barrier=None)`` 用注入的
  ``session_factory`` 自建会话（背景任务无请求上下文，与请求解耦）；测试直接以
  ``_pg_engine`` 构造的 ``async_sessionmaker`` 传入，或经端点
  ``dependency_overrides[get_job_session_factory]`` 指向测试 schema（Task 14 范式）。
- **无中央分发器**：提交端点（Task 14）经 ``BackgroundTasks.add_task`` 直接排入本
  worker；spec 自 ``Job.task_payload`` 读取（写入侧在 Task 14 端点）。
- 权限上下文自库重建（``get_access_context``）——提交后权限变化的二次把关依据；
  材料获取仍全程经 ``gather_materials`` 的 ``visible_to`` 红线（``analysis/materials.py``）。
- 材料经 ``get_app_stores()`` 单例取 vector / graph store：worker 与端点同进程
  （BackgroundTasks），共享同一 AppStores 单例；生产路由（postgres / neo4j）下跨
  请求可见性经 DB 成立。域模块不顶层导入 api 层，函数内懒加载。

执行链（材料装配不进引擎，见架构节）：

```text
gather_materials（含 visible_to 二次把关）→ 空材料拦为失败
→ compute_report_access_level（密级继承）→ engine.run
→ 报告落库（仅 ok / partial；AnalysisReportStore 拒 failed）+ 信封装配（补 generated_at）
→ Job.result = {report_id, status} 最小指针（决策 2）→ 终态审计
```

**进度分段**（带 ``progress_stage``）：gather 10 → prompt 25 → llm 60 → verify 80 →
persist 95 → done 100。引擎内部（prompt/llm/verify）无阶段回调，llm/verify 两档为
引擎返回后的近似推进（仿 ingest worker「结束后置档再进终态」惯例）；真阶段级回调留
后续（无锚点：与 ECL 真阶段进度同批评估）。

**报告落库口径**（计划「报告落库口径」）：引擎返回 ``failed``（解析预算耗尽等完全
失败）或执行异常 → job failed + ``error`` 可读 + 审计记 failed，不落空报告；
``ok`` / ``partial`` 落报告行，``partial`` 如实落库且 job succeeded（用户可见降级
原因而非黑洞）。

**终态审计**（``record_audit``，action=analyze）：成功 ``resource_type="analysis_report"``
+ report_id（detail 含 status / model / prompt_version）；失败 ``resource_type="job"``
+ error（detail 含 status / error）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.analysis.access import compute_report_access_level
from calliodesmo.analysis.materials import GatheredMaterials, gather_materials
from calliodesmo.analysis.report_store import AnalysisReportStore
from calliodesmo.analysis.schemas import AnalysisEnvelope, AnalysisStatus, AnalysisType
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.service import get_access_context
from calliodesmo.config import get_settings
from calliodesmo.db.models_job import Job, JobStatus
from calliodesmo.interfaces.analysis import AnalysisEngine, AnalysisReport, AnalysisSpec


async def run_analysis_job(
    job_id: uuid.UUID,
    *,
    engine: AnalysisEngine,
    session_factory: async_sessionmaker,
    barrier: object | None = None,
) -> None:
    """执行单个分析 job：建 session -> running(gather) -> 采集 -> 引擎 -> 落库 -> 终态。

    - ``engine``：请求侧按 settings 构建（``build_analysis_engine``）后注入；settings
      依赖注入与 ``RuntimeError``（LLM 缺 key 等）-> 503 的判定留在请求边界（Task 14）
    - 独立 session 落状态 / 报告 / 审计（背景任务无请求上下文）；任何异常 -> failed 终态
    - ``barrier`` 若提供（须有 ``set()``，测试同步等待用），完成（含失败）后置位
    """
    try:
        async with session_factory() as job_session:
            job = (await job_session.execute(select(Job).where(Job.id == job_id))).scalar_one()
            user_id = job.user_id
            await _update_job(job_session, job_id, JobStatus.RUNNING, stage="gather", progress=10)
            # 权限上下文自库重建（提交后权限变化的二次把关；用户被停用 / 删 -> 失败终态）
            access = await get_access_context(job_session, user_id)
            if access is None:
                raise RuntimeError(f"提交者上下文不可用（用户不存在或已停用）: user_id={user_id}")
            spec = _spec_from_payload(job.task_payload)
            # 材料经 AppStores 单例（与端点同进程共享；生产路由下跨请求经 DB 可见）
            from calliodesmo.api.deps import get_app_stores  # 懒加载：域模块不顶层依赖 api 层

            stores = get_app_stores()
            settings = get_settings()
            gathered = await gather_materials(
                vector_store=stores.vector_store,
                graph_store=stores.graph_store,
                access=access,
                task_type=spec.task_type,
                doc_ids=spec.doc_ids,
                max_chunks=settings.analysis_max_chunks,
                max_input_chars=settings.analysis_max_input_chars,
            )
            if not gathered.materials:
                raise ValueError("无可见材料（提交范围为空或权限已变化）")
            await _update_job(job_session, job_id, JobStatus.RUNNING, stage="prompt", progress=25)
            report = await engine.run(spec, gathered.materials, access)
            # 进度近似推进（引擎内部无阶段回调，仿 ingest worker 惯例）
            await _update_job(job_session, job_id, JobStatus.RUNNING, stage="llm", progress=60)
            await _update_job(job_session, job_id, JobStatus.RUNNING, stage="verify", progress=80)
            if report.status == AnalysisStatus.FAILED.value:
                # 完全失败：不落空报告（落库口径），job failed + 审计 failed
                message = "; ".join(w for w in report.warnings if w) or "分析失败（无可读原因）"
                await _finish_failed_message(job_session, job_id, message)
                return
            await _update_job(job_session, job_id, JobStatus.RUNNING, stage="persist", progress=95)
            await _finish_succeeded(
                job_session, job_id, access=access, spec=spec, report=report, gathered=gathered
            )
    except Exception as exc:
        try:
            async with session_factory() as job_session:
                await _finish_failed(job_session, job_id, exc)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("analyze job %s 失败状态落库异常", job_id)
    finally:
        if barrier is not None:
            barrier.set()


async def _update_job(
    session, job_id: uuid.UUID, status: JobStatus, *, stage: str, progress: int
) -> None:
    """更新 job 状态（每进度点一 commit，前端轮询可见中间态）。"""
    job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()
    job.status = status
    job.progress_stage = stage
    job.progress = progress
    if status is JobStatus.RUNNING and job.started_at is None:
        job.started_at = func.now()
    await session.commit()


async def _finish_succeeded(
    session,
    job_id: uuid.UUID,
    *,
    access: AccessContext,
    spec: AnalysisSpec,
    report: AnalysisReport,
    gathered: GatheredMaterials,
) -> None:
    """终态落账：报告行（信封装配）+ succeeded + result 指针 + 审计（action=analyze）。"""
    # 信封装配：引擎产出 AnalysisReport，此处补 generated_at（UTC now）装配为契约信封
    envelope = AnalysisEnvelope(
        task_type=report.task_type,
        status=report.status,
        generated_at=datetime.now(UTC),
        model=report.model,
        prompt_version=report.prompt_version,
        usage=report.usage,
        warnings=report.warnings,
        source_chunk_ids=report.source_chunk_ids,
        payload=report.payload,
    )
    report_row = await AnalysisReportStore().create(
        session,
        job_id=job_id,
        user_id=access.user_id,
        task_type=report.task_type,
        status=report.status,
        subject_label=_subject_label(spec, gathered),
        payload=envelope.model_dump(),
        source_doc_ids=_source_doc_ids(gathered),
        source_chunk_count=len(gathered.materials),
        access_level=compute_report_access_level(gathered.materials),  # 密级继承（决策 4）
        model=report.model,
        prompt_version=report.prompt_version,
        usage=report.usage,
    )
    job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()
    job.status = JobStatus.SUCCEEDED
    job.progress = 100
    job.progress_stage = "done"
    # result 最小指针（决策 2）：报告全文在 analysis_reports 表
    job.result = {"report_id": str(report_row.id), "status": report.status}
    job.finished_at = func.now()
    await session.commit()
    await record_audit(
        session,
        user_id=access.user_id,
        action="analyze",
        resource_type="analysis_report",
        resource_id=str(report_row.id),
        detail={
            "status": report.status,
            "model": report.model,
            "prompt_version": report.prompt_version,
            "job_id": str(job_id),
        },
        source="api",
    )
    await session.commit()


async def _finish_failed(session, job_id: uuid.UUID, exc: Exception) -> None:
    """终态落账（异常路径）：failed + error + 审计（action=analyze，resource_type=job）。"""
    await _finish_failed_message(session, job_id, f"{type(exc).__name__}: {exc}")


async def _finish_failed_message(session, job_id: uuid.UUID, message: str) -> None:
    """终态落账（可读失败消息）：不落空报告（落库口径），审计记 failed。"""
    job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()
    job.status = JobStatus.FAILED
    job.error = message
    job.finished_at = func.now()
    await session.commit()
    await record_audit(
        session,
        user_id=job.user_id,
        action="analyze",
        resource_type="job",
        resource_id=str(job.id),
        detail={"status": "failed", "error": message},
        source="api",
    )
    await session.commit()


def _spec_from_payload(payload: dict | None) -> AnalysisSpec:
    """自 ``Job.task_payload`` 反序列化 ``AnalysisSpec``（写入侧见 Task 14 提交端点）。

    非法载荷抛 ``ValueError``（可读消息进 ``Job.error`` 与审计）。
    """
    if not isinstance(payload, dict) or not payload:
        raise ValueError("分析任务载荷缺失：task_payload 为空（analyze job 须携带 spec 序列化）")
    raw_type = payload.get("task_type")
    try:
        task_type = AnalysisType(raw_type)
    except ValueError as exc:
        raise ValueError(f"task_payload.task_type 非法: {raw_type!r}") from exc
    raw_doc_ids = payload.get("doc_ids")
    doc_ids = tuple(str(d) for d in raw_doc_ids) if raw_doc_ids else None
    raw_schema = payload.get("custom_schema")
    return AnalysisSpec(
        task_type=task_type,
        doc_ids=doc_ids,
        question=str(payload.get("question") or ""),
        custom_instruction=str(payload.get("custom_instruction") or ""),
        custom_schema=raw_schema if isinstance(raw_schema, dict) else None,
        top_k=int(payload.get("top_k") or 10),
        model_override=payload.get("model_override") or None,
    )


def _subject_label(spec: AnalysisSpec, gathered: GatheredMaterials) -> str:
    """分析对象描述：QA 取问题；其余取材料文档标题去重拼接（截断 512 字符）。"""
    if spec.task_type is AnalysisType.QA and spec.question.strip():
        return spec.question.strip()[:512]
    labels: list[str] = []
    for material in gathered.materials:
        if material.source_label and material.source_label not in labels:
            labels.append(material.source_label)
    return "、".join(labels)[:512] or spec.task_type.value


def _source_doc_ids(gathered: GatheredMaterials) -> list[str]:
    """报告源文档列表：材料块按采集序去重（提交序 / 字典序见 gather_materials）。"""
    doc_ids: list[str] = []
    for material in gathered.materials:
        if material.doc_id not in doc_ids:
            doc_ids.append(material.doc_id)
    return doc_ids
