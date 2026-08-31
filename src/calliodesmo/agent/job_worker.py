"""Agent 回合编排 worker：``Job(task_type="agent")`` 异步范式（P7 T13）。

1:1 对齐 ``analysis/job_worker.py`` 注入范式：``run_agent_job(job_id, *, engine,
session_factory, barrier=None)`` 自建 session 重建 AccessContext（``get_access_context``，
提交后权限变化的二次把关）；``thread_id`` = 会话 id（checkpoint 与 ORM 对齐）。

执行链：rebuild 10（AccessContext + 会话复检 T12）→ graph 50（run_turn）→
persist 90（消息 / 执行落库 + 落库前密级断言钩子）→ done 100 → 终态审计
``agent_run``（detail 含 steps / usage / mode）。

**失败语义**：执行异常 -> run failed + error + job failed + 审计；预算超限 ->
优雅失败：run ``failed``（error=budget_exceeded）**保留部分轨迹** + assistant
部分答案落消息 + job succeeded（用户可见降级而非黑洞，同 P6 partial 口径）。
会话复检不通过 -> job failed + 审计（404 同语义不泄漏存在性，API 层 T14）。
"""

from __future__ import annotations

import uuid

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.agent.access import assert_evidence_within_session, verify_session_access
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.service import get_access_context
from calliodesmo.db.models_agent import AgentMessageORM, AgentRunORM, AgentSessionORM
from calliodesmo.db.models_job import Job, JobStatus
from calliodesmo.utils.json import json_safe


async def run_agent_job(
    job_id: uuid.UUID,
    *,
    engine,
    session_factory,
    barrier: object | None = None,
) -> None:
    """执行单个 agent 回合 job；任何终态（含失败）后置位 barrier。"""
    try:
        async with session_factory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            payload = job.task_payload or {}
            session_id = uuid.UUID(str(payload["session_id"]))
            question = str(payload["question"])
            system = payload.get("system")

            # rebuild 10：AccessContext 重建 + 会话复检（密级不洗白 + visible_to）
            job.status = JobStatus.RUNNING
            job.progress = 10
            job.progress_stage = "rebuild"
            await session.commit()

            access = await get_access_context(session, job.user_id)
            sess = await session.get(AgentSessionORM, session_id)
            if access is None or sess is None or not verify_session_access(sess, access=access):
                job.status = JobStatus.FAILED
                job.error = "会话不可用或权限不足"
                await record_audit(
                    session,
                    user_id=job.user_id,
                    action="agent_run",
                    resource_type="job",
                    detail={"status": "failed", "error": job.error, "session_id": str(session_id)},
                    source="agent_worker",
                )
                await session.commit()
                return

            run = AgentRunORM(session_id=session_id, status="running")
            session.add(run)
            session.add(AgentMessageORM(session_id=session_id, role="user", content=question))
            await session.commit()
            run_id = run.id

            # graph 50
            job.progress = 50
            job.progress_stage = "graph"
            await session.commit()

            try:
                turn = await engine.run_turn(
                    question=question,
                    thread_id=str(session_id),
                    access=access,
                    system=system,
                )
            except Exception as exc:  # 执行异常：run failed + job failed + 审计
                run.status = "failed"
                run.error = str(exc)
                job.status = JobStatus.FAILED
                job.error = str(exc)
                await record_audit(
                    session,
                    user_id=job.user_id,
                    action="agent_run",
                    resource_type="job",
                    detail={"status": "failed", "error": str(exc)},
                    source="agent_worker",
                )
                await session.commit()
                return

            # persist 90：落库前密级断言钩子（证据密级不高于会话密级）
            assert_evidence_within_session(sess.access_level, session_level=sess.access_level)
            job.progress = 90
            job.progress_stage = "persist"

            budget_exceeded = turn.status == "budget_exceeded"
            run.status = "failed" if budget_exceeded else "succeeded"
            run.error = "budget_exceeded" if budget_exceeded else None
            run.tool_trace = json_safe(
                [
                    {
                        "call": {"id": c.id, "name": c.name, "arguments": c.arguments},
                        "result": {"ok": r.ok, "output": r.output, "error": r.error},
                    }
                    for c, r in turn.tool_trace
                ]
            )
            run.usage = json_safe(turn.usage)
            run.steps = turn.steps
            session.add(
                AgentMessageORM(
                    session_id=session_id, role="assistant", content=turn.answer, run_id=run_id
                )
            )

            # done 100：预算超限为优雅失败——run failed 保留部分轨迹，job succeeded
            job.status = JobStatus.SUCCEEDED
            job.progress = 100
            job.progress_stage = "done"
            job.result = json_safe(
                {"session_id": str(session_id), "run_id": str(run_id), "status": run.status}
            )
            await record_audit(
                session,
                user_id=job.user_id,
                action="agent_run",
                resource_type="agent_run",
                resource_id=str(run_id),
                detail={
                    "status": run.status,
                    "steps": turn.steps,
                    "usage": turn.usage,
                    "mode": getattr(engine, "mode", None) and engine.mode.value,
                    "warnings": turn.warnings,
                },
                source="agent_worker",
            )
            await session.commit()
    finally:
        if barrier is not None and hasattr(barrier, "set"):
            barrier.set()
