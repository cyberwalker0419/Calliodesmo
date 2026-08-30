"""P7 T13：回合编排 worker（job 范式 + AccessContext 重建 + 审计 + 预算失败语义）。"""

import asyncio
import uuid

from sqlalchemy import select

from calliodesmo.agent.budget import BudgetLimits
from calliodesmo.agent.graph import ReActAgentEngine
from calliodesmo.agent.job_worker import run_agent_job
from calliodesmo.audit.models import AuditLog
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.auth.service import assign_role, create_user, seed_default_roles
from calliodesmo.db.models_agent import AgentMessageORM, AgentRunORM, AgentSessionORM
from calliodesmo.db.models_job import Job, JobStatus
from calliodesmo.eval.agent_harness import build_eval_registry
from calliodesmo.providers.stub_llm import StubLLMProvider


async def _make_user(session, clearance=ClearanceLevel.SECRET, username="agent-u"):
    await seed_default_roles(session)
    user = await create_user(session, username=username, password="pw", clearance=clearance)
    await assign_role(session, user=user, role_name="analyst", scope=LibraryScope.TEAM)
    await session.commit()
    return user


def _factory(_pg_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(_pg_engine, expire_on_commit=False)


def _engine(**kw):
    return ReActAgentEngine(StubLLMProvider(), build_eval_registry(), limits=kw.get("limits"))


async def _run_job(session, factory, engine, user, system, question="问题"):
    sess = AgentSessionORM(
        owner_id=user.id,
        access_level=ClearanceLevel.INTERNAL,
        clearance_at_create=user.clearance,
    )
    session.add(sess)
    await session.commit()
    job = Job(
        user_id=user.id,
        task_type="agent",
        task_payload={"session_id": str(sess.id), "question": question, "system": system},
    )
    session.add(job)
    await session.commit()
    barrier = asyncio.Event()
    await asyncio.wait_for(
        run_agent_job(job.id, engine=engine, session_factory=factory, barrier=barrier), 60
    )
    assert barrier.is_set()
    return sess, job


async def test_run_agent_job_success_pipeline(session, _pg_engine):
    """一轮跑完：答案落 AgentMessage + Job.result 最小指针 + 审计 agent_run。"""
    factory = _factory(_pg_engine)
    user = await _make_user(session)
    engine = _engine()
    sess, job = await _run_job(session, factory, engine, user, "[AGENT:two_step_search]")

    async with factory() as s:
        got_job = await s.get(Job, job.id)
        assert got_job.status == JobStatus.SUCCEEDED
        assert got_job.progress == 100
        pointer = got_job.result
        assert pointer["session_id"] == str(sess.id)

        run = await s.get(AgentRunORM, uuid.UUID(pointer["run_id"]))
        assert run.status == "succeeded"
        assert run.steps == 2
        assert [t["call"]["name"] for t in run.tool_trace] == ["search_knowledge"]

        msgs = (
            (await s.execute(select(AgentMessageORM).where(AgentMessageORM.session_id == sess.id)))
            .scalars()
            .all()
        )
        assert [m.role for m in msgs] == ["user", "assistant"]
        assert "OpenAI" in msgs[1].content

        audits = (
            (await s.execute(select(AuditLog).where(AuditLog.action == "agent_run")))
            .scalars()
            .all()
        )
        assert audits and audits[0].detail["steps"] == 2


async def test_run_agent_job_budget_exceeded_graceful(session, _pg_engine):
    """预算超限：run failed 保留部分轨迹 + job succeeded（优雅失败非黑洞）。"""

    factory = _factory(_pg_engine)
    user = await _make_user(session, username="budget-u")
    engine = _engine(limits=BudgetLimits(max_steps=2))
    _, job = await _run_job(session, factory, engine, user, "[AGENT:loop_forever]")

    async with factory() as s:
        got_job = await s.get(Job, job.id)
        assert got_job.status == JobStatus.SUCCEEDED  # job  graceful 完成
        run = await s.get(AgentRunORM, uuid.UUID(got_job.result["run_id"]))
        assert run.status == "failed"
        assert run.error == "budget_exceeded"
        assert run.tool_trace  # 部分轨迹保留
        msgs = (
            (
                await s.execute(
                    select(AgentMessageORM).where(AgentMessageORM.session_id == run.session_id)
                )
            )
            .scalars()
            .all()
        )
        assert [m.role for m in msgs] == ["user", "assistant"]  # 部分答案落消息


async def test_run_agent_job_clearance_downgrade_denied(session, _pg_engine):
    """密级不洗白：建时 SECRET 会话 + INTERNAL 用户 -> job failed + 审计。"""
    factory = _factory(_pg_engine)
    user = await _make_user(session, clearance=ClearanceLevel.INTERNAL, username="low-u")
    engine = _engine()

    sess = AgentSessionORM(
        owner_id=user.id,
        access_level=ClearanceLevel.INTERNAL,
        clearance_at_create=ClearanceLevel.SECRET,  # 建时高密，现用户已降级
    )
    session.add(sess)
    await session.commit()
    job = Job(
        user_id=user.id,
        task_type="agent",
        task_payload={"session_id": str(sess.id), "question": "q", "system": "[AGENT:x]"},
    )
    session.add(job)
    await session.commit()

    barrier = asyncio.Event()
    await asyncio.wait_for(
        run_agent_job(job.id, engine=engine, session_factory=factory, barrier=barrier), 60
    )
    async with factory() as s:
        got_job = await s.get(Job, job.id)
        assert got_job.status == JobStatus.FAILED
        runs = (
            (await s.execute(select(AgentRunORM).where(AgentRunORM.session_id == sess.id)))
            .scalars()
            .all()
        )
        assert runs == []  # 复检不通过不产 run
