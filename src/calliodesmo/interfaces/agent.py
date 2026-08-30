"""Agent 域对外契约：引擎无关可插拔（LangGraph 仅为实现细节，边界集中在
``agent/graph.py`` + ``providers/langgraph_adapter.py``，本模块不导入 langgraph）。

P7 T5 冻结：``AgentMode``（预留 ``rewoo`` 值，⏸ 暂缓锚点 2026-W49）/
``ToolResult`` / ``TurnResult`` frozen 结构 / ``AgentTool`` 协议 / ``AgentEngine`` ABC。
``ToolSpec`` / ``ToolCall`` 与 LLM 层共用同一份（``interfaces.llm`` 重导出）。
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import Permission
from calliodesmo.interfaces.llm import ToolCall, ToolSpec

__all__ = [
    "AgentEngine",
    "AgentMode",
    "AgentTool",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "TurnResult",
]


class AgentMode(enum.StrEnum):
    REACT = "react"
    PLAN_EXECUTE = "plan_execute"
    REWOO = "rewoo"  # 预留值（⏸ 暂缓，锚点 2026-W49 随 P9 模型层清单重评，见决策 3）


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    name: str
    ok: bool
    output: str  # 截断 + 引注口径，入 prompt 前沿用 P6 sanitize 纪律
    error: str | None  # 越权与不存在同一文案（契约测试锁定不可区分）


@dataclass(frozen=True)
class TurnResult:
    answer: str
    tool_trace: tuple[tuple[ToolCall, ToolResult], ...]
    steps: int
    usage: dict[str, int]
    warnings: list[str]  # budget_exceeded / history_truncated ...
    status: str  # ok | budget_exceeded | failed


@runtime_checkable
class AgentTool(Protocol):
    spec: ToolSpec
    required_permission: Permission

    async def run(self, arguments: dict, *, access: AccessContext) -> str: ...


class AgentEngine(ABC):
    mode: AgentMode

    @abstractmethod
    async def run_turn(self, *, question: str, thread_id: str, access: AccessContext) -> TurnResult:
        """执行一个对话回合；``thread_id`` = 会话 id（checkpoint 与 ORM 对齐）。"""
