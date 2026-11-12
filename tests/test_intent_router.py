"""P8 Task 5：确定性意图路由决策表单测。"""

from __future__ import annotations

import pytest

from calliodesmo.retrieval.intent import IntentDecision, route_intent


class TestPositiveRoutes:
    """四类正例：多跳 / 全局主题 / 实体关系 / 操作指令。"""

    def test_action_instruction_routes_agent(self):
        decision = route_intent("帮我调查 APT28 的组织结构并生成报告")
        assert decision.mode == "agent"
        assert decision.confidence >= 0.45
        assert any("动作指令" in reason for reason in decision.reasons)

    def test_global_theme_routes_global(self):
        decision = route_intent("总结本月稀土市场的整体趋势")
        assert decision.mode == "global"
        assert any("全局主题" in reason for reason in decision.reasons)

    def test_entity_relation_routes_local(self):
        decision = route_intent("夜莺组织与张三、李四之间是什么关系？")
        assert decision.mode == "local"
        assert any("实体关系" in reason for reason in decision.reasons)

    def test_factoid_routes_native(self):
        decision = route_intent("镨钕氧化物有什么用途？")
        assert decision.mode == "native_rag"
        assert decision.fallback is False

    def test_multi_question_routes_local(self):
        decision = route_intent("APT28 使用什么后门？该后门用什么语言重写？")
        assert decision.mode == "local"


class TestFallback:
    """模糊查询回退默认模式。"""

    def test_ambiguous_query_falls_back_native(self):
        decision = route_intent("稀土")
        assert decision.mode == "native_rag"
        assert decision.fallback is True
        assert any("回退" in reason for reason in decision.reasons)

    def test_empty_query_falls_back(self):
        decision = route_intent("   ")
        assert decision.mode == "native_rag"
        assert decision.fallback is True
        assert decision.confidence == 0.0


class TestDecisionShape:
    """决策结构稳定、确定性、置信有界。"""

    @pytest.mark.parametrize(
        "question",
        [
            "镨钕氧化物有什么用途？",
            "总结本月稀土市场的整体趋势",
            "夜莺组织与张三、李四之间是什么关系？",
            "帮我调查 APT28 的组织结构并生成报告",
            "稀土",
        ],
    )
    def test_confidence_bounded(self, question):
        decision = route_intent(question)
        assert 0.0 <= decision.confidence <= 1.0
        assert decision.mode in {"native_rag", "local", "global", "agent"}

    def test_deterministic(self):
        question = "总结本月稀土市场的整体趋势"
        assert route_intent(question) == route_intent(question)

    def test_as_dict(self):
        decision = route_intent("镨钕氧化物有什么用途？")
        payload = decision.as_dict()
        assert set(payload) == {"mode", "confidence", "reasons", "fallback"}
        assert isinstance(payload["reasons"], list)

    def test_no_reason_means_no_signal(self):
        decision = route_intent("稀土市场")
        assert isinstance(decision, IntentDecision)
        assert decision.mode == "native_rag"
