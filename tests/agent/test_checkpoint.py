"""P7 T11：build_checkpointer 双轨 + AsyncPostgresSaver 集成（@pytest.mark.db）。

检查单（决策 2）：setup() 幂等 / autocommit / dict_row / 独立池 / 同 thread 状态互通。
"""

import pytest

from calliodesmo.agent.checkpoint import build_checkpointer, conninfo_from_database_url
from calliodesmo.agent.graph import ReActAgentEngine
from calliodesmo.config import get_settings
from calliodesmo.eval.agent_harness import build_eval_access, build_eval_registry
from calliodesmo.providers.stub_llm import StubLLMProvider


def test_conninfo_strips_driver_scheme():
    assert (
        conninfo_from_database_url("postgresql+asyncpg://u:p@h:5432/d")
        == "postgresql://u:p@h:5432/d"
    )
    assert conninfo_from_database_url("postgresql://u:p@h/d") == "postgresql://u:p@h/d"


def test_build_checkpointer_memory_offline():
    from langgraph.checkpoint.memory import InMemorySaver

    assert isinstance(build_checkpointer(None), InMemorySaver)


async def _pg_checkpointer_scenario():
    settings = get_settings()
    checkpointer = build_checkpointer(settings.database_url, schema="calliodesmo_test")
    pool = checkpointer.conn
    await pool.open()
    try:
        await checkpointer.setup()
        await checkpointer.setup()  # 幂等（checkpoint_migrations 版本表驱动）

        engine = ReActAgentEngine(
            StubLLMProvider(), build_eval_registry(), checkpointer=checkpointer
        )
        access = build_eval_access(["query", "analyze"])
        tid = "t11-pg-checkpoint"
        await engine.run_turn(
            question="一轮", thread_id=tid, access=access, system="[AGENT:two_step_search]"
        )
        turn2 = await engine.run_turn(
            question="二轮", thread_id=tid, access=access, system="[AGENT:two_step_search]"
        )
        assert turn2.status == "ok"

        state = await engine._app.aget_state({"configurable": {"thread_id": tid, "access": access}})
        human_count = sum(1 for m in state.values["messages"] if m.type == "human")
        assert human_count == 2  # 跨 ainvoke 的执行态经 AsyncPostgresSaver 续接
    finally:
        await pool.close()


@pytest.mark.db
def test_pg_checkpointer_setup_idempotent_and_thread_state():
    """真 PG：setup 双跑幂等；同 thread_id 两轮状态互通。

    psycopg 异步在 Windows 需 SelectorEventLoop（Proactor 不支持）——sync 包装
    切策略跑独立 loop，跑完还原（CI Linux 默认 selector，不受影响）。
    """
    import asyncio
    import sys

    old = None
    if sys.platform == "win32":
        old = asyncio.get_event_loop_policy()
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(_pg_checkpointer_scenario())
    finally:
        if old is not None:
            asyncio.set_event_loop_policy(old)
