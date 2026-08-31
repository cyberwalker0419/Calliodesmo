"""三重预算帽：步数 / token / 挂钟（纯函数 + 策略；超限强制收敛，P7 决策）。

成本失控风险当场拆掉：ReAct 每步一次 LLM 调用，步数与 token 不可预测——
任一帽超限即强制收敛为「部分结果 + 说明」+ ``warning("budget_exceeded")``。
挂钟经 ``now`` 注入可测（纯函数纪律）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BudgetLimits:
    max_steps: int = 6
    token_budget: int = 32000
    wall_clock_seconds: int = 120


@dataclass
class BudgetState:
    steps: int = 0
    tokens: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def exceeded(self, limits: BudgetLimits, *, now: float | None = None) -> str | None:
        """任一帽超限回原因（steps / tokens / wall_clock），否则 None。"""
        if self.steps >= limits.max_steps:
            return "steps"
        if self.tokens > limits.token_budget:
            return "tokens"
        now = time.monotonic() if now is None else now
        if now - self.started_at > limits.wall_clock_seconds:
            return "wall_clock"
        return None
