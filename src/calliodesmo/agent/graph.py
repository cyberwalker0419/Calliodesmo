"""手写 ReAct StateGraph（P7 T10，v1 主链）+ 三重预算帽强制收敛。

结构：model 节点（适配器后端）→ ``should_continue`` 条件边（有 tool_calls →
工具节点；预算超限 → 强制收敛节点；否则 END）→ 工具节点（注册表派发 + 轨迹
回写）→ 回 model。不用已弃用 ``create_react_agent``（LangGraph 2.0 移除），
不引 ``create_agent`` / middleware；StateGraph 原语 1.0 GA 后稳定。

**AccessContext 经 config ``configurable`` 带外传参，不入 checkpoint 状态**
（防密级快照序列化漂移；每回合由 worker 重建，T13）。
"""

from __future__ import annotations

import time
from typing import TypedDict

from calliodesmo.agent.budget import BudgetLimits
from calliodesmo.agent.extras import require_langgraph
from calliodesmo.agent.history import truncate_history
from calliodesmo.agent.registry import DefaultToolRegistry
from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.agent import (
    AgentEngine,
    AgentMode,
    ToolCall,
    ToolResult,
    TurnResult,
)
from calliodesmo.interfaces.llm import LLMProvider
from calliodesmo.providers.langgraph_adapter import build_langgraph_chat_model

_CONVERGE_TEXT = "预算超限：以下为部分结果与说明（工具轨迹见 trace）。"


class ReActAgentEngine(AgentEngine):
    """ReAct 两节点环：model <-> tools，三重预算帽超限强制收敛。"""

    mode = AgentMode.REACT

    def __init__(
        self,
        provider: LLMProvider,
        registry: DefaultToolRegistry,
        *,
        checkpointer=None,
        limits: BudgetLimits | None = None,
        history_window: int = 8,
    ) -> None:
        require_langgraph()
        from typing import Annotated

        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.graph.message import add_messages

        # 函数式 TypedDict：注解值即时求值（add_messages reducer 真挂上；
        # 类体语法在 future-annotations 下会字符串化导致 reducer 丢失）
        agent_state = TypedDict(  # noqa: UP013
            "AgentState",
            {
                "messages": Annotated[list, add_messages],
                "steps": int,
                "tokens": int,
                "warnings": list,
                "status": str,
                "trace": list,
            },
        )

        self.provider = provider
        self.registry = registry
        self.limits = limits or BudgetLimits()
        self.history_window = history_window
        self.model = build_langgraph_chat_model(provider)
        self._turn_started = 0.0

        engine = self

        async def model_node(state, config) -> dict:
            access: AccessContext = config["configurable"]["access"]
            specs = engine.registry.list_for(access)
            bound = engine.model.bind_tools(specs)
            # 历史滑动窗口（系统提示恒留 + 最近 N 回合，T12）
            history, truncated = truncate_history(
                list(state["messages"]), window=engine.history_window
            )
            warnings = state["warnings"]
            if truncated and "history_truncated" not in warnings:
                warnings = [*warnings, "history_truncated"]
            ai = await bound.ainvoke(history)
            usage = ai.additional_kwargs.get("usage") or {}
            return {
                "messages": [ai],
                "steps": state["steps"] + 1,
                "tokens": state["tokens"] + int(usage.get("total_tokens", 0)),
                "warnings": warnings,
            }

        def should_continue(state, config) -> str:
            last = state["messages"][-1]
            if not getattr(last, "tool_calls", None):
                return END
            if engine._budget_exceeded(state) is not None:
                return "converge"
            return "tools"

        async def tools_node(state, config) -> dict:
            access: AccessContext = config["configurable"]["access"]
            last = state["messages"][-1]
            trace = list(state["trace"])
            tool_messages = []
            for tc in last.tool_calls:
                call = ToolCall(id=tc["id"], name=tc["name"], arguments=dict(tc["args"] or {}))
                result = await engine.registry.dispatch(call, access=access)
                trace.append(
                    {
                        "call": {"id": call.id, "name": call.name, "arguments": call.arguments},
                        "result": {"ok": result.ok, "output": result.output, "error": result.error},
                    }
                )
                from langchain_core.messages import ToolMessage

                tool_messages.append(
                    ToolMessage(content=result.output or result.error or "", tool_call_id=call.id)
                )
            return {"messages": tool_messages, "trace": trace}

        async def converge_node(state, config) -> dict:
            from langchain_core.messages import AIMessage

            return {
                "messages": [AIMessage(content=_CONVERGE_TEXT)],
                "warnings": [*state["warnings"], "budget_exceeded"],
                "status": "budget_exceeded",
            }

        graph = StateGraph(agent_state)
        graph.add_node("model", model_node)
        graph.add_node("tools", tools_node)
        graph.add_node("converge", converge_node)
        graph.add_edge(START, "model")
        graph.add_conditional_edges(
            "model", should_continue, {"tools": "tools", "converge": "converge", END: END}
        )
        graph.add_edge("tools", "model")
        graph.add_edge("converge", END)
        self._app = graph.compile(checkpointer=checkpointer or InMemorySaver())

    def _budget_exceeded(self, state) -> str | None:
        """三重帽：步数 / token（state 累计）+ 挂钟（回合起点，带外）。"""
        if state["steps"] >= self.limits.max_steps:
            return "steps"
        if state["tokens"] > self.limits.token_budget:
            return "tokens"
        if time.monotonic() - self._turn_started > self.limits.wall_clock_seconds:
            return "wall_clock"
        return None

    async def run_turn(
        self,
        *,
        question: str,
        thread_id: str,
        access: AccessContext,
        system: str | None = None,
    ) -> TurnResult:
        self._turn_started = time.monotonic()
        config = {"configurable": {"thread_id": thread_id, "access": access}}
        seed: list = ([_system(system)] if system else []) + [_human(question)]
        result = await self._app.ainvoke(
            {
                "messages": seed,
                "steps": 0,
                "tokens": 0,
                "warnings": [],
                "status": "ok",
                "trace": [],
            },
            config,
        )
        answer = ""
        for m in reversed(result["messages"]):
            if getattr(m, "type", "") == "ai":
                answer = m.content
                break
        trace = tuple(
            (
                ToolCall(
                    id=t["call"]["id"],
                    name=t["call"]["name"],
                    arguments=t["call"]["arguments"],
                ),
                ToolResult(
                    tool_call_id=t["call"]["id"],
                    name=t["call"]["name"],
                    ok=t["result"]["ok"],
                    output=t["result"]["output"],
                    error=t["result"]["error"],
                ),
            )
            for t in result["trace"]
        )
        return TurnResult(
            answer=answer,
            tool_trace=trace,
            steps=result["steps"],
            usage={"total_tokens": result["tokens"]},
            warnings=list(result["warnings"]),
            status=result["status"],
        )


def _human(content: str):
    from langchain_core.messages import HumanMessage

    return HumanMessage(content=content)


def _system(content: str):
    from langchain_core.messages import SystemMessage

    return SystemMessage(content=content)
