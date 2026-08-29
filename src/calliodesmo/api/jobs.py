"""/jobs 端点：异步任务进度查询（摄入 / 分析共用）。

P4.5 Task 5：前端轮询 ``GET /jobs/{id}`` 取进度（progress/stage）与终态
（succeeded + result / failed + error）。鉴权：仅 job 所属用户可查（他人 ->
404，不泄漏存在性）。

P6 Task 11：Job 表泛化（``task_type`` / ``task_payload``），本端点过滤与鉴权逻辑
不变，仅补两出参透传——``task_type`` 直传；``report_id`` 仅 analyze 任务自
``Job.result`` 最小指针（``{report_id, status}``，Task 13 worker 写入）解析，
ingest 恒 None（防透传破坏旧消费方 useIngest.ts）。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.api.deps import get_current_context
from calliodesmo.api.schemas import JobOut
from calliodesmo.auth.context import AccessContext
from calliodesmo.db.models_job import Job
from calliodesmo.db.session import get_session

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: uuid.UUID,
    ctx: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    """查询单个异步任务：仅所属用户可见（他人 -> 404）。"""
    job = (
        await session.execute(select(Job).where(Job.id == job_id, Job.user_id == ctx.user_id))
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"任务不存在: {job_id}")
    # P6 Task 11：analyze 任务自 result 最小指针解析 report_id；ingest 恒 None
    report_id: uuid.UUID | None = None
    if job.task_type != "ingest" and isinstance(job.result, dict):
        raw_report_id = job.result.get("report_id")
        if raw_report_id is not None:
            report_id = uuid.UUID(str(raw_report_id))
    return JobOut(
        id=job.id,
        filename=job.filename,
        status=job.status.value,
        progress=job.progress,
        progress_stage=job.progress_stage,
        result=job.result,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        task_type=job.task_type,
        report_id=report_id,
    )
