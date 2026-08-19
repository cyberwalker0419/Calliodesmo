"""/jobs 端点：摄入任务进度查询。

P4.5 Task 5：前端轮询 ``GET /jobs/{id}`` 取进度（progress/stage）与终态
（succeeded + result / failed + error）。鉴权：仅 job 所属用户可查（他人 ->
404，不泄漏存在性）。
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
    """查询单个摄入 job：仅所属用户可见（他人 -> 404）。"""
    job = (
        await session.execute(select(Job).where(Job.id == job_id, Job.user_id == ctx.user_id))
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"任务不存在: {job_id}")
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
    )
