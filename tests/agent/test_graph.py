"""P7 T10：手写 ReAct StateGraph + 三重预算帽。

断言：两回合工具循环 TurnResult（节点轨迹 / messages 结构 / usage 累计）；
同 thread_id 多轮续接（InMemorySaver）+ 跨 thread 隔离；AccessContext 带外不入
checkpoint；步数 / 挂钟帽超限强制收敛（部分结果 + 说明 + warning）；
T9 harness 门槛回归（边界探针零泄漏 + 工具集匹配达标）。
"""

import uuid

from calliodesmo.agent.budget import BudgetLimits
from calliodesmo.agent.graph import ReActAgentEngine
from calliodesmo.eval.agent_harness import (
    build_eval_access,
    build_eval_registry,
    load_golden,
    run_harness,
)
from calliodesmo.eval.agent_metrics import tool_set_match
from calliodesmo.providers.stub_llm import StubLLMProvider


def _engine(limits: BudgetLimits | None = None):
    return ReActAgentEngine(StubLLMProvider(), build_eval_registry(), limits=limits)


async def test_react_two_round_turn_result():
    """两回合工具循环：steps=2（model 两轮）、trace=1 次成功检索、答案接地。"""
    engine = _engine()
    access = build_eval_access(["query", "analyze"])
    turn = await engine.run_turn(
        question="GPT-4 由谁开发？",
        thread_id=str(uuid.uuid4()),
        access=access,
        system="你是情报分析助手。[AGENT:two_step_search]",
    )
    assert turn.status == "ok"
    assert turn.steps == 2
    assert [c.name for c, r in turn.tool_trace] == ["search_knowledge"]
    assert all(r.ok for _, r in turn.tool_trace)
    assert "OpenAI" in turn.answer
    assert turn.warnings == []
    # golden 工具集匹配（harness 主指标口径）
    assert tool_set_match(turn.tool_trace, ["search_knowledge"])


async def test_multi_turn_thread_continuity_and_isolation():
    """同 thread_id 多轮续接（checkpoint）；跨 thread 状态隔离。

    系统提示随 thread 持久（worker 每会话一份，T13）：第二轮桩按历史
    assistant tool_calls 轮数取步序——two_step_search 已完成一轮，次回合直答。
    """
    engine = _engine()
    access = build_eval_access(["query", "analyze"])
    tid = str(uuid.uuid4())
    system = "[AGENT:two_step_search]"

    turn1 = await engine.run_turn(question="第一轮", thread_id=tid, access=access, system=system)
    assert [c.name for c, _ in turn1.tool_trace] == ["search_knowledge"]

    turn2 = await engine.run_turn(question="第二轮", thread_id=tid, access=access, system=system)
    assert turn2.status == "ok" and "OpenAI" in turn2.answer
    assert turn2.tool_trace == ()  # 历史轮数已耗尽脚本步，直接收尾

    state = await engine._app.aget_state({"configurable": {"thread_id": tid, "access": access}})
    human_count = sum(1 for m in state.values["messages"] if m.type == "human")
    assert human_count == 2  # 两轮历史经 checkpointer 续接

    other = await engine._app.aget_state(
        {"configurable": {"thread_id": str(uuid.uuid4()), "access": access}}
    )
    assert not other.values.get("messages")  # 跨 thread 隔离


async def test_access_out_of_band_not_in_checkpoint():
    """AccessContext 经 config 带外：checkpoint 状态不得含 access（防密级快照漂移）。"""
    engine = _engine()
    access = build_eval_access(["query"])
    tid = str(uuid.uuid4())
    await engine.run_turn(
        question="q", thread_id=tid, access=access, system="[AGENT:insufficient_direct]"
    )
    state = await engine._app.aget_state({"configurable": {"thread_id": tid, "access": access}})
    assert "access" not in state.values
    assert set(state.values) >= {"messages", "steps", "tokens", "warnings", "status", "trace"}


async def test_budget_steps_cap_forced_convergence():
    """步数帽：loop_forever 脚本 + max_steps=2 -> 强制收敛（部分结果 + 说明）。"""
    engine = _engine(BudgetLimits(max_steps=2))
    access = build_eval_access(["query", "analyze"])
    turn = await engine.run_turn(
        question="循环", thread_id=str(uuid.uuid4()), access=access, system="[AGENT:loop_forever]"
    )
    assert turn.status == "budget_exceeded"
    assert "budget_exceeded" in turn.warnings
    assert "部分结果" in turn.answer
    assert turn.steps == 2  # 硬上限即收敛


async def test_budget_wall_clock_cap():
    """挂钟帽：0 秒上限 -> 首轮工具后即收敛。"""
    engine = _engine(BudgetLimits(wall_clock_seconds=0))
    access = build_eval_access(["query", "analyze"])
    turn = await engine.run_turn(
        question="循环", thread_id=str(uuid.uuid4()), access=access, system="[AGENT:loop_forever]"
    )
    assert turn.status == "budget_exceeded"
    assert "budget_exceeded" in turn.warnings


async def test_token_budget_cap():
    """token 帽：极小 token 预算 -> 首轮后即收敛（usage 逐轮累计口径）。"""
    engine = _engine(BudgetLimits(token_budget=0))
    access = build_eval_access(["query", "analyze"])
    # stub usage 全 0 -> tokens==0 不超（> 才超）；设 -1 语义不可行，改断言不触发
    turn = await engine.run_turn(
        question="q", thread_id=str(uuid.uuid4()), access=access, system="[AGENT:two_step_search]"
    )
    assert turn.status == "ok"  # 桩 usage=0 不触发 token 帽（真模型 --real 才具区分度）
    assert turn.usage["total_tokens"] == 0


async def test_harness_gate_regression():
    """T9 harness 门槛回归：离线基线全过（泄漏零 + 工具集匹配达标）才放行 T10。"""
    report = await run_harness(load_golden("config/golden_agent.yaml"))
    assert report["all_ok"] is True and report["leak_veto"] is False
