"""Agent 会话与执行端点（P7 T14，job 范式 + 审计 + 401/403/404 矩阵）。

契约（计划「API 契约」表）：

- ``POST /agent/sessions``：QUERY 门控；未注册 mode 400；审计 ``agent_session_create``。
- ``GET /agent/sessions``：visible_to 三维过滤 + 密级不洗白（列表侧复检）。
- ``POST /agent/sessions/{id}/runs``：QUERY + 会话可见（不可见/不存在 -> 404 同一文案）；
  ``Job(task_type="agent")`` + BackgroundTasks 排入 ``run_agent_job``；引擎构建
  ``RuntimeError`` -> 503（同 ingest / analyze 惯例）。
- ``GET /agent/sessions/{id}/messages``：不可见 -> 404（不泄漏存在性）。

根 + ``/api`` 前缀双挂（app.py 既有范式）。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.agent.access import verify_session_access
from calliodesmo.agent.job_worker import run_agent_job
from calliodesmo.api.deps import get_current_context, get_job_session_factory
from calliodesmo.api.schemas import (
    AgentMessageOut,
    AgentRunAccepted,
    AgentRunOut,
    AgentRunRequest,
    AgentSessionCreate,
    AgentSessionListOut,
    AgentSessionOut,
)
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import Permission
from calliodesmo.db.models_agent import AgentMessageORM, AgentRunORM, AgentSessionORM
from calliodesmo.db.models_job import Job
from calliodesmo.db.session import get_session
from calliodesmo.utils.json import json_safe

router = APIRouter(prefix="/agent", tags=["agent"])

_SESSION_GONE = "会话不存在或不可见"
_V1_MODES = {"react"}  # plan_execute 为批 2 可选（T20）；rewoo 预留不注册


def _session_out(s: AgentSessionORM) -> AgentSessionOut:
    return AgentSessionOut(
        id=s.id,
        mode=s.mode,
        label=s.label,
        access_level=s.access_level.name,
        library_scope=s.library_scope.value,
        created_at=s.created_at,
    )


@router.post("/sessions", response_model=AgentSessionOut, status_code=201)
async def create_session(
    req: AgentSessionCreate,
    context: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> AgentSessionOut:
    if not context.has_permission(Permission.QUERY):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无 query 权限")
    if req.mode not in _V1_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"未注册的 agent 模式：{req.mode}（可选：{', '.join(sorted(_V1_MODES))}）",
        )
    sess = AgentSessionORM(
        owner_id=context.user_id,
        mode=req.mode,
        label=req.label,
        clearance_at_create=context.clearance,
    )
    session.add(sess)
    await record_audit(
        session,
        user_id=context.user_id,
        action="agent_session_create",
        resource_type="agent_session",
        detail={"mode": req.mode},
        source="api",
    )
    await session.commit()
    return _session_out(sess)


@router.get("/sessions", response_model=AgentSessionListOut)
async def list_sessions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    context: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> AgentSessionListOut:
    if not context.has_permission(Permission.QUERY):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无 query 权限")
    rows = (
        (await session.execute(select(AgentSessionORM).order_by(AgentSessionORM.created_at.desc())))
        .scalars()
        .all()
    )
    visible = [s for s in rows if verify_session_access(s, access=context)]
    total = len(visible)
    page = visible[offset : offset + limit]
    return AgentSessionListOut(items=[_session_out(s) for s in page], total=total)


@router.post("/sessions/{session_id}/runs", response_model=AgentRunAccepted, status_code=202)
async def submit_run(
    session_id: uuid.UUID,
    req: AgentRunRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    context: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
    session_factory=Depends(get_job_session_factory),
) -> AgentRunAccepted:
    if not context.has_permission(Permission.QUERY):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无 query 权限")
    sess = await session.get(AgentSessionORM, session_id)
    if sess is None or not verify_session_access(sess, access=context):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_SESSION_GONE)

    # 引擎构建（缺 extra / 缺 key 的 RuntimeError -> 503，同 ingest / analyze 惯例）
    from calliodesmo.agent.factory import build_agent_engine
    from calliodesmo.api.deps import get_app_stores
    from calliodesmo.config import get_settings

    settings = get_settings()
    try:
        engine = build_agent_engine(
            settings,
            get_app_stores(),
            checkpointer=getattr(request.app.state, "agent_checkpointer", None),
            session=session,
            session_factory=session_factory,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    job = Job(
        user_id=context.user_id,
        task_type="agent",
        task_payload=json_safe(
            {"session_id": str(session_id), "question": req.question, "system": None}
        ),
    )
    session.add(job)
    await session.commit()
    job_id = job.id
    background_tasks.add_task(run_agent_job, job_id, engine=engine, session_factory=session_factory)
    return AgentRunAccepted(job_id=job_id, status="pending")


@router.get("/sessions/{session_id}/messages", response_model=list[AgentMessageOut])
async def list_messages(
    session_id: uuid.UUID,
    context: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> list[AgentMessageOut]:
    if not context.has_permission(Permission.QUERY):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无 query 权限")
    sess = await session.get(AgentSessionORM, session_id)
    if sess is None or not verify_session_access(sess, access=context):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_SESSION_GONE)
    rows = (
        (
            await session.execute(
                select(AgentMessageORM)
                .where(AgentMessageORM.session_id == session_id)
                .order_by(AgentMessageORM.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        AgentMessageOut(
            id=m.id,
            session_id=m.session_id,
            role=m.role,
            content=m.content,
            run_id=m.run_id,
            created_at=m.created_at,
        )
        for m in rows
    ]


@router.get("/sessions/{session_id}/runs", response_model=list[AgentRunOut])
async def list_runs(
    session_id: uuid.UUID,
    context: AccessContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_session),
) -> list[AgentRunOut]:
    """执行列表：轨迹 JSON 供前端 ToolTrace 折叠展示（不可见 -> 404 同语义）。"""
    if not context.has_permission(Permission.QUERY):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无 query 权限")
    sess = await session.get(AgentSessionORM, session_id)
    if sess is None or not verify_session_access(sess, access=context):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_SESSION_GONE)
    rows = (
        (
            await session.execute(
                select(AgentRunORM)
                .where(AgentRunORM.session_id == session_id)
                .order_by(AgentRunORM.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        AgentRunOut(
            id=r.id,
            session_id=r.session_id,
            status=r.status,
            steps=r.steps,
            usage=r.usage or {},
            tool_trace=r.tool_trace or [],
            error=r.error,
            created_at=r.created_at,
        )
        for r in rows
    ]
