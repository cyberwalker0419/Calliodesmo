"""P8 Task 5：确定性意图路由（查询 → native / local / global / agent）。

口径（P8 关键决策 6）：
- **显式模式绝不改写**：路由只在 ``mode="auto"`` 时被调用；
- 规则打分基于查询特征（动作词、全局词、实体关系词、事实疑问词、长度、问句数），
  输出 ``IntentDecision(mode, confidence, reasons, fallback)``；
- 低置信（最高分 < ``MIN_TOP_SCORE`` 或归一化置信 < ``MIN_CONFIDENCE``）回退
  ``native_rag`` 并标记 ``fallback=True``（回退用户默认模式）；
- 决策可解释：``reasons`` 列出命中的规则标签，供审计与前端展示；
- 不做端到端小模型（训练分类器需标注集，先由 golden 语料积累）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from calliodesmo.interfaces.retriever import SearchMode

__all__ = ["IntentDecision", "resolve_query_mode", "route_intent"]

#: 允许的路由目标（agent 需专用端点执行，/query 侧回退见 api 层）
ROUTABLE_MODES: tuple[str, ...] = ("native_rag", "local", "global", "agent")

#: 低置信阈值
MIN_TOP_SCORE = 2
MIN_CONFIDENCE = 0.40

_AGENT_STRONG = ("帮我", "请分析", "生成报告", "调查", "评估", "制定计划", "工作流", "多步")
_AGENT_WEAK = ("分析", "生成", "计划", "步骤", "先", "然后", "再", "整理成")
_GLOBAL_MARKERS = ("总结", "整体", "趋势", "概览", "全局", "综述", "总体", "主要结论", "归纳")
_LOCAL_MARKERS = ("关系", "关联", "邻居", "图谱", "实体", "连接", "属于", "路径", "之间")
_NATIVE_MARKERS = ("是什么", "多少", "哪里", "什么时候", "哪一年", "谁", "用途", "含义")


@dataclass(frozen=True)
class IntentDecision:
    """路由决策：目标模式 + 置信 + 命中理由 + 是否回退默认。"""

    mode: str
    confidence: float
    reasons: tuple[str, ...] = field(default_factory=tuple)
    fallback: bool = False

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "fallback": self.fallback,
        }


def route_intent(question: str) -> IntentDecision:
    """按确定性规则为查询选择检索模式（空查询回退 native_rag）。"""
    text = (question or "").strip()
    if not text:
        return IntentDecision(
            mode="native_rag", confidence=0.0, reasons=("空查询回退默认",), fallback=True
        )

    scores: dict[str, int] = {"native_rag": 1, "local": 0, "global": 0, "agent": 0}
    reasons: list[str] = []

    strong_actions = [marker for marker in _AGENT_STRONG if marker in text]
    weak_actions = [marker for marker in _AGENT_WEAK if marker in text]
    if strong_actions:
        scores["agent"] += 2 * len(strong_actions)
        reasons.append(f"动作指令：{'/'.join(strong_actions)}")
    if weak_actions:
        scores["agent"] += len(weak_actions)
        reasons.append(f"多步线索：{'/'.join(weak_actions)}")

    global_hits = [marker for marker in _GLOBAL_MARKERS if marker in text]
    if global_hits:
        scores["global"] += 2 * len(global_hits)
        reasons.append(f"全局主题：{'/'.join(global_hits)}")

    local_hits = [marker for marker in _LOCAL_MARKERS if marker in text]
    if local_hits:
        scores["local"] += 3 * len(local_hits)
        reasons.append(f"实体关系：{'/'.join(local_hits)}")

    native_hits = [marker for marker in _NATIVE_MARKERS if marker in text]
    if native_hits:
        scores["native_rag"] += len(native_hits)
        reasons.append(f"事实疑问：{'/'.join(native_hits)}")

    if len(text) >= 60:
        scores["agent"] += 1
        scores["local"] += 1
        reasons.append("长查询：多跳倾向")
    if text.count("？") + text.count("?") >= 2:
        scores["local"] += 2
        reasons.append("多问句：多跳倾向")

    # 确定性择优：同分按 native_rag > local > global > agent（低风险优先）
    priority = {mode: index for index, mode in enumerate(ROUTABLE_MODES)}
    best_mode = max(ROUTABLE_MODES, key=lambda mode: (scores[mode], -priority[mode]))
    total = sum(scores.values())
    confidence = round(scores[best_mode] / total, 4) if total else 0.0

    if scores[best_mode] < MIN_TOP_SCORE or confidence < MIN_CONFIDENCE:
        return IntentDecision(
            mode="native_rag",
            confidence=confidence,
            reasons=(*reasons, "低置信回退默认 native_rag"),
            fallback=True,
        )
    return IntentDecision(mode=best_mode, confidence=confidence, reasons=tuple(reasons))


def resolve_query_mode(raw_mode: str, question: str) -> tuple[SearchMode, str | None, dict | None]:
    """解析请求模式：显式模式零改写；``auto`` 走路由。

    返回 ``(executed_mode, routed_mode, routing)``：
    - 显式模式：``(SearchMode(raw_mode), None, None)``，未知模式抛 ``ValueError``；
    - ``auto``：路由到 ``native_rag`` / ``local`` / ``global`` 直接执行；
      路由到 ``agent`` 时本端点无法执行，回退 ``local`` 并在 ``routing`` 留痕
      （Agent 模式需专用 ``/agent`` 端点）。
    """
    if raw_mode != "auto":
        return SearchMode(raw_mode), None, None
    decision = route_intent(question)
    executed = decision.mode if decision.mode in {"native_rag", "local", "global"} else "local"
    reasons = list(decision.reasons)
    fallback = decision.fallback or decision.mode != executed
    if decision.mode == "agent":
        reasons.append("Agent 模式需专用端点，已回退 local")
    routing = {
        "requested_mode": "auto",
        "routed_mode": decision.mode,
        "executed_mode": executed,
        "confidence": decision.confidence,
        "reasons": reasons,
        "fallback": fallback,
    }
    return SearchMode(executed), decision.mode, routing
