"""进程内 job worker：后台异步跑 ECL ingest，写进度与终态到 jobs 表。

P4.5 Task 5：``POST /ingest`` 改为建 job + ``BackgroundTasks`` 触发本 worker，
请求立即返回 ``202 + job_id``；worker 经独立 session 落库（与请求解耦），进度按
阶段近似推进（running 5 -> extract 30 -> cognify 60 -> load 90 -> done 100），
终态写 ``succeeded + result`` 或 ``failed + error``，另记审计（source=api）。

分层：ECL 引擎由请求侧（api/ingest.py）构建后传入——settings 依赖注入与
``RuntimeError``（LLM 缺 key 等）-> 503 的判定留在请求边界；本模块只负责执行
与状态机。ECLIndexingEngine 一次 ``ingest()`` 跑完整链（无阶段回调），进度为
拆点近似值；真阶段级进度回调留 v2（见 P4.5 计划 Task 5）。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.db.models_job import Job, JobStatus
from calliodesmo.interfaces.indexing_engine import IndexingEngine, IngestStats


async def run_ingest_job(
    job_id: uuid.UUID,
    source_path: str | Path,
    *,
    engine: IndexingEngine,
    access: AccessContext,
    session_factory: async_sessionmaker,
    request_id: str = "",
    barrier: object | None = None,
) -> None:
    """执行单个摄入 job：建 session -> running -> engine.ingest -> 终态。

    - ``engine``：请求侧按 settings + AppStores 单例构建（与 query/browse 同进程
      共享，ingest 结果即时可查）
    - 独立 session 落状态/审计（背景任务无请求上下文）；任何异常 -> failed 终态
    - ``barrier`` 若提供（须有 ``set()``，测试同步等待用），完成（含失败）后置位
    """
    source_path = Path(source_path)
    assert source_path.exists(), f"ingest 临时文件丢失: {source_path}"
    try:
        async with session_factory() as job_session:
            await _update_job(job_session, job_id, JobStatus.RUNNING, stage="extract", progress=5)
            stats = await engine.ingest(source_path, access=access)
            # 进度近似推进（engine 无阶段回调）：结束后置 cognify/load 档再进终态
            await _update_job(job_session, job_id, JobStatus.RUNNING, stage="cognify", progress=60)
            await _update_job(job_session, job_id, JobStatus.RUNNING, stage="load", progress=90)
            await _finish_succeeded(job_session, job_id, stats, source_path, request_id=request_id)
    except Exception as exc:
        try:
            async with session_factory() as job_session:
                await _finish_failed(job_session, job_id, exc)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("job %s 失败状态落库异常", job_id)
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
    session, job_id: uuid.UUID, stats: IngestStats, source_path: Path, *, request_id: str
) -> None:
    """终态落账：succeeded + result + 审计（action=ingest）。"""
    job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()
    job.status = JobStatus.SUCCEEDED
    job.progress = 100
    job.progress_stage = "done"
    job.result = stats.as_dict()
    job.finished_at = func.now()
    await session.commit()
    await record_audit(
        session,
        user_id=job.user_id,
        action="ingest",
        resource_type="document",
        resource_id=str(source_path.name),
        detail={**stats.as_dict(), "job_id": str(job_id), "request_id": request_id},
        source="api",
    )
    await session.commit()


async def _finish_failed(session, job_id: uuid.UUID, exc: Exception) -> None:
    """终态落账：failed + error + 审计。"""
    job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()
    job.status = JobStatus.FAILED
    job.error = f"{type(exc).__name__}: {exc}"
    job.finished_at = func.now()
    await session.commit()
    await record_audit(
        session,
        user_id=job.user_id,
        action="ingest",
        resource_type="job",
        resource_id=str(job.id),
        detail={"status": "failed", "error": str(exc)},
        source="api",
    )
    await session.commit()


def reset_stale_running_jobs(session_factory: async_sessionmaker) -> None:
    """serve 重启恢复：把遗留 running/pending job 标记 failed（进程内 worker 已丢）。

    P4.5 Task 5 以 BackgroundTasks 进程内 worker 承载异步 ingest；serve 重启即丢
    running 任务（无持久队列）。启动时调用本函数把陈旧非终态 job 置
    ``failed("服务重启，任务中断")``，前端轮询即时得到终态而非永挂。持
    久队列（Celery+Redis）留 roadmap P9。
    """
    import asyncio
    import logging

    logger = logging.getLogger(__name__)

    async def _reset() -> int:
        async with session_factory() as s:
            result = await s.execute(
                select(Job).where(Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
            )
            stale = result.scalars().all()
            for job in stale:
                job.status = JobStatus.FAILED
                job.error = "服务重启，任务中断（请重新上传）"
                job.finished_at = func.now()
            await s.commit()
            return len(stale)

    try:
        count = asyncio.run(_reset())
        if count:
            logger.warning("启动清理：%d 个中断 job 置 failed", count)
    except Exception:
        logger.exception("中断 job 清理失败（不阻启动）")
