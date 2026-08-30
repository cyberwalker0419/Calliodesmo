"""Agent 引擎装配：build_agent_engine（P7 T13，复用既有工厂路由规则）。

- provider：``retrieval/factory.build_llm_provider`` 同套豁免规则；``agent_model``
  空回退 ``llm_model``（经 settings 浅拷贝路由，不旁落所有权）。
- registry：全工具集装配在 stores 单例上（读工具经 store 侧 visible_to；
  ``get_chunk`` 工具层自补）；reports 工具需 session；``run_analysis`` 提交钩子
  建 ``Job(task_type="analyze")`` 并经 ``asyncio.create_task`` 排入 P6 worker
  （嵌套 job 无请求 BackgroundTasks，进程内 worker 范式同 P4.5）。
- 缺依赖 / 缺 key 的 ``RuntimeError`` 留在请求边界转 503（T14），装配层不吞。
"""

from __future__ import annotations

import asyncio
import uuid

from calliodesmo.agent.graph import ReActAgentEngine
from calliodesmo.agent.registry import DefaultToolRegistry
from calliodesmo.agent.tools.analysis import ReportsGetTool, ReportsListTool, RunAnalysisTool
from calliodesmo.agent.tools.communities import ListCommunitiesTool
from calliodesmo.agent.tools.documents import GetChunkTool, ListDocumentsTool
from calliodesmo.agent.tools.entities import EntityProfileTool, ListEntitiesTool
from calliodesmo.agent.tools.graph import GraphNeighborsTool
from calliodesmo.agent.tools.search import SearchKnowledgeTool
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel
from calliodesmo.config import Settings
from calliodesmo.db.models_job import Job
from calliodesmo.retrieval.factory import build_llm_provider
from calliodesmo.utils.json import json_safe


def build_agent_provider(settings: Settings):
    """agent_model 空回退 llm_model；路由规则同 build_llm_provider。"""
    if settings.agent_model:
        settings = settings.model_copy(update={"llm_model": settings.agent_model})
    return build_llm_provider(settings)


def make_analysis_submit(settings: Settings, session_factory, *, search_engine=None):
    """run_analysis 提交钩子：建 analyze job + 排入 P6 worker，回 job_id 指针。"""

    async def submit(
        task_type: str, doc_ids: list[str], level: ClearanceLevel, access: AccessContext
    ) -> str:
        from calliodesmo.analysis.factory import build_analysis_engine
        from calliodesmo.analysis.job_worker import run_analysis_job

        async with session_factory() as session:
            job = Job(
                user_id=access.user_id,
                task_type="analyze",
                task_payload=json_safe(
                    {
                        "task_type": task_type,
                        "doc_ids": doc_ids,
                        "planned_access_level": level.name,
                        "submitted_by": "agent",
                    }
                ),
            )
            session.add(job)
            await session.commit()
            job_id = job.id

        async def _run():
            engine = build_analysis_engine(settings, search_engine=search_engine)
            await run_analysis_job(job_id, engine=engine, session_factory=session_factory)

        asyncio.get_running_loop().create_task(_run())
        return str(job_id)

    return submit


def build_agent_registry(
    settings: Settings,
    stores,
    *,
    session=None,
    session_factory=None,
    audit_hook=None,
) -> DefaultToolRegistry:
    """全工具集：读七件 + reports（需 session）+ run_analysis（需 session_factory）。"""
    from calliodesmo.retrieval.factory import build_default_search_engine, build_reranker

    search_engine = build_default_search_engine(
        settings,
        vector_store=stores.vector_store,
        graph_store=stores.graph_store,
        community_store=stores.community_store,
        sparse_index=stores.sparse_index,
        reranker=build_reranker(settings),
    )
    tools = [
        SearchKnowledgeTool(search_engine),
        GraphNeighborsTool(stores.graph_store),
        ListEntitiesTool(stores.graph_store),
        EntityProfileTool(stores.profile_card_store),
        ListDocumentsTool(stores.vector_store),
        ListCommunitiesTool(stores.community_store),
        GetChunkTool(stores.vector_store),
    ]
    if session is not None:
        tools.append(ReportsListTool(session))
        tools.append(ReportsGetTool(session))
    if session_factory is not None:
        tools.append(
            RunAnalysisTool(
                stores.vector_store,
                submit=make_analysis_submit(settings, session_factory, search_engine=search_engine),
                graph_store=stores.graph_store,
            )
        )
    return DefaultToolRegistry(tools, audit_hook=audit_hook)


def build_agent_engine(
    settings: Settings,
    stores,
    *,
    checkpointer=None,
    session=None,
    session_factory=None,
    audit_hook=None,
) -> ReActAgentEngine:
    """ReAct 主链引擎：预算帽 / 历史窗口经 settings（T10 六配置项）。"""
    from calliodesmo.agent.budget import BudgetLimits

    registry = build_agent_registry(
        settings, stores, session=session, session_factory=session_factory, audit_hook=audit_hook
    )
    return ReActAgentEngine(
        build_agent_provider(settings),
        registry,
        checkpointer=checkpointer,
        limits=BudgetLimits(
            max_steps=settings.agent_max_steps,
            token_budget=settings.agent_token_budget,
            wall_clock_seconds=settings.agent_wall_clock_seconds,
        ),
        history_window=settings.agent_history_window,
    )


def new_session_id() -> uuid.UUID:
    return uuid.uuid4()
