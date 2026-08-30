"""P6 Task 4 测试：报告契约 I——公共信封 + Evidence + quote 子串校验（纯函数，无夹具）。

覆盖：
- ``AnalysisStatus``（ok/partial/failed，非法值报错）与 ``AnalysisType``（9 类）；
- ``Evidence``：chunk_id / quote 非空校验、confidence 0–1 区间、与引擎侧
  ``EvidenceRef`` 的一一对应互转（契约层 pydantic 形态，见架构节「信封装配」）；
- ``AnalysisEnvelope``：九字段契约（与前端 types.ts ``AnalysisEnvelope`` 逐字段对齐）；
- ``verify_evidence``：quote 去空白后非源文子串 → 该条置信封顶 0.3 + warning；
  失败占比 >30% → status=partial（边界：恰 30% 不降级）。
"""

import dataclasses
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from calliodesmo.analysis.evidence import (
    CONFIDENCE_CAP,
    FAILURE_RATIO_THRESHOLD,
    normalize_for_match,
    verify_evidence,
)
from calliodesmo.analysis.schemas import (
    AnalysisEnvelope,
    AnalysisStatus,
    AnalysisType,
    Evidence,
)

_EXPECTED_ENVELOPE_FIELDS = {
    "task_type",
    "status",
    "generated_at",
    "model",
    "prompt_version",
    "usage",
    "warnings",
    "source_chunk_ids",
    "payload",
}

_EXPECTED_ANALYSIS_TYPES = {
    "summary",
    "key_information",
    "timeline",
    "entity_recognition",
    "relation_mapping",
    "tasks",
    "concepts",
    "qa",
    "custom",
}


def _envelope(payload: dict | None = None, **overrides) -> AnalysisEnvelope:
    """构造最小合法信封（默认 status=ok，payload 单条 summary）。"""
    base: dict = {
        "task_type": "summary",
        "status": "ok",
        "generated_at": datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        "model": "test/model",
        "prompt_version": "summary.v1",
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        "warnings": [],
        "source_chunk_ids": ["c1"],
        "payload": {"summary": "概述"} if payload is None else payload,
    }
    base.update(overrides)
    return AnalysisEnvelope(**base)


def _ev(chunk_id: str = "c1", quote: str = "源文片段", confidence: float | None = None) -> dict:
    """构造 payload 内的证据节点（Evidence.model_dump 形状）。"""
    node: dict = {"chunk_id": chunk_id, "quote": quote}
    if confidence is not None:
        node["confidence"] = confidence
    return node


class TestAnalysisStatus:
    def test_values(self):
        assert {member.value for member in AnalysisStatus} == {"ok", "partial", "failed"}

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            AnalysisStatus("bogus")

    def test_envelope_rejects_invalid_status(self):
        with pytest.raises(ValidationError):
            _envelope(status="bogus")


class TestAnalysisType:
    def test_nine_types(self):
        """9 类分析一次立齐（roadmap 对 P6 的一句话定义）。"""
        assert {member.value for member in AnalysisType} == _EXPECTED_ANALYSIS_TYPES

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            AnalysisType("bogus")

    def test_envelope_rejects_invalid_task_type(self):
        with pytest.raises(ValidationError):
            _envelope(task_type="bogus")


class TestEvidence:
    def test_valid_evidence_defaults_confidence(self):
        ev = Evidence(chunk_id="c1", quote="源文片段")
        assert ev.chunk_id == "c1"
        assert ev.quote == "源文片段"
        assert ev.confidence == 1.0

    @pytest.mark.parametrize(
        ("chunk_id", "quote"),
        [("", "q"), ("  ", "q"), ("c1", ""), ("c1", " \t\n ")],
    )
    def test_blank_fields_rejected(self, chunk_id, quote):
        """chunk_id / quote 非空校验（去空白后为空同样拒绝）。"""
        with pytest.raises(ValidationError):
            Evidence(chunk_id=chunk_id, quote=quote)

    @pytest.mark.parametrize("bad", [-0.1, 1.2])
    def test_confidence_out_of_range_rejected(self, bad):
        with pytest.raises(ValidationError):
            Evidence(chunk_id="c1", quote="q", confidence=bad)

    @pytest.mark.parametrize("ok", [0.0, 0.3, 1.0])
    def test_confidence_boundaries(self, ok):
        assert Evidence(chunk_id="c1", quote="q", confidence=ok).confidence == ok

    def test_from_ref_duck_typed(self):
        """from_ref 按结构互转：接受任何带 chunk_id/quote 属性的对象（引擎侧 dataclass 形态）。"""

        @dataclasses.dataclass(frozen=True)
        class _Ref:
            chunk_id: str
            quote: str

        ev = Evidence.from_ref(_Ref(chunk_id="c9", quote="引文"))
        assert (ev.chunk_id, ev.quote, ev.confidence) == ("c9", "引文", 1.0)

    def test_to_ref_roundtrip_with_evidence_ref(self):
        """to_ref / from_ref 与 interfaces ``EvidenceRef`` 一一对应互转（P6 Task 10 落地）。

        ``confidence`` 不参与互转：转 ``EvidenceRef`` 时舍弃，自 ``EvidenceRef`` 转入默认 1.0。
        """
        from calliodesmo.interfaces.analysis import EvidenceRef

        ev = Evidence(chunk_id="c1", quote="q", confidence=0.8)
        ref = ev.to_ref()
        assert isinstance(ref, EvidenceRef)
        assert (ref.chunk_id, ref.quote) == ("c1", "q")
        back = Evidence.from_ref(ref)
        assert (back.chunk_id, back.quote, back.confidence) == ("c1", "q", 1.0)


class TestAnalysisEnvelope:
    def test_nine_fields(self):
        """信封恰九字段（与前端 AnalysisEnvelope 契约逐字段对齐）。"""
        assert set(AnalysisEnvelope.model_fields) == _EXPECTED_ENVELOPE_FIELDS

    def test_round_trip(self):
        env = _envelope(source_chunk_ids=["c1", "c2"])
        dumped = env.model_dump()
        assert set(dumped) == _EXPECTED_ENVELOPE_FIELDS
        assert AnalysisEnvelope.model_validate(dumped) == env

    def test_list_defaults_empty(self):
        env = _envelope()
        assert env.warnings == []
        assert env.source_chunk_ids == ["c1"]  # 夹具显式给定
        env2 = AnalysisEnvelope(
            task_type="summary",
            status="ok",
            generated_at=datetime(2026, 8, 29, tzinfo=UTC),
            model="m",
            prompt_version="summary.v1",
            usage={},
            payload={},
        )
        assert env2.warnings == []
        assert env2.source_chunk_ids == []

    def test_usage_values_must_be_int(self):
        with pytest.raises(ValidationError):
            _envelope(usage={"prompt_tokens": "many"})

    def test_payload_must_be_dict(self):
        with pytest.raises(ValidationError):
            _envelope(payload=["not", "a", "dict"])

    def test_missing_required_field_rejected(self):
        with pytest.raises(ValidationError):
            AnalysisEnvelope(task_type="summary", status="ok")


class TestNormalizeForMatch:
    def test_strips_whitespace(self):
        assert normalize_for_match("  甲 乙  丙 \n") == "甲乙丙"

    def test_strips_fullwidth_space(self):
        """全角空格（　）亦属空白。"""
        assert normalize_for_match("甲　乙") == "甲乙"

    def test_empty(self):
        assert normalize_for_match("   ") == ""


class TestVerifyEvidence:
    def test_all_match_keeps_status_and_confidence(self):
        payload = {"items": [{"confidence": 0.9, "evidence": [_ev("c1", "源文片段", 0.9)]}]}
        env = _envelope(payload=payload)
        result = verify_evidence(env, {"c1": "这是源文片段原文"})
        assert result.status is AnalysisStatus.OK
        assert result.warnings == []
        assert result.payload["items"][0]["evidence"][0]["confidence"] == 0.9

    def test_whitespace_insensitive_match(self):
        """quote 与源文的空白差异（换行/空格）不影响匹配。"""
        payload = {"items": [{"evidence": [_ev("c1", "源文\n片段")]}]}
        env = _envelope(payload=payload)
        result = verify_evidence(env, {"c1": "这是 源文片段 原文"})
        assert result.status is AnalysisStatus.OK
        assert result.warnings == []

    def test_mismatch_caps_confidence_and_warns(self):
        payload = {"items": [{"confidence": 0.9, "evidence": [_ev("c1", "编造的引文", 0.9)]}]}
        env = _envelope(payload=payload)
        result = verify_evidence(env, {"c1": "这是源文片段原文"})
        node = result.payload["items"][0]["evidence"][0]
        assert node["confidence"] == CONFIDENCE_CAP
        assert len(result.warnings) == 1
        assert "c1" in result.warnings[0]
        # 单条失败占比 100% > 30% → 降级
        assert result.status is AnalysisStatus.PARTIAL

    def test_mismatch_caps_at_most_keeps_lower_confidence(self):
        """封顶取 min：原置信低于 0.3 不上调。"""
        payload = {"items": [{"evidence": [_ev("c1", "编造", 0.2)]}]}
        result = verify_evidence(_envelope(payload=payload), {"c1": "源文"})
        assert result.payload["items"][0]["evidence"][0]["confidence"] == 0.2

    def test_mismatch_without_confidence_key_gets_capped_from_default(self):
        payload = {"items": [{"evidence": [_ev("c1", "编造")]}]}
        result = verify_evidence(_envelope(payload=payload), {"c1": "源文"})
        assert result.payload["items"][0]["evidence"][0]["confidence"] == CONFIDENCE_CAP

    def test_unknown_chunk_id_fails(self):
        payload = {"items": [{"evidence": [_ev("c404", "任意引文")]}]}
        result = verify_evidence(_envelope(payload=payload), {"c1": "源文"})
        assert result.payload["items"][0]["evidence"][0]["confidence"] == CONFIDENCE_CAP
        assert "c404" in result.warnings[0]
        assert result.status is AnalysisStatus.PARTIAL

    def test_blank_quote_fails(self):
        """payload 为原始 dict（LLM 输出），空白 quote 即使能绕过 Evidence 构造也须判失败。"""
        payload = {"items": [{"evidence": [_ev("c1", "   ")]}]}
        result = verify_evidence(_envelope(payload=payload), {"c1": "源文"})
        assert result.payload["items"][0]["evidence"][0]["confidence"] == CONFIDENCE_CAP
        assert result.status is AnalysisStatus.PARTIAL

    def test_failure_ratio_at_threshold_stays_ok(self):
        """边界：恰 30%（3/10）失败不降级（仅 >30% 降级）。"""
        assert FAILURE_RATIO_THRESHOLD == 0.3
        evidences = [_ev("c1", "坏引文" if i < 3 else "源文片段") for i in range(10)]
        payload = {"items": [{"evidence": evidences}]}
        result = verify_evidence(_envelope(payload=payload), {"c1": "这是源文片段原文"})
        assert result.status is AnalysisStatus.OK
        assert len(result.warnings) == 3

    def test_failure_ratio_above_threshold_goes_partial(self):
        """4/10 = 40% > 30% → partial。"""
        evidences = [_ev("c1", "坏引文" if i < 4 else "源文片段") for i in range(10)]
        payload = {"items": [{"evidence": evidences}]}
        result = verify_evidence(_envelope(payload=payload), {"c1": "这是源文片段原文"})
        assert result.status is AnalysisStatus.PARTIAL
        assert len(result.warnings) == 4

    def test_partial_input_status_never_upgraded(self):
        """已 partial / failed 的信封不因证据全过而升级。"""
        payload = {"items": [{"evidence": [_ev("c1", "源文片段")]}]}
        for incoming in (AnalysisStatus.PARTIAL, AnalysisStatus.FAILED):
            result = verify_evidence(
                _envelope(payload=payload, status=incoming), {"c1": "源文片段"}
            )
            assert result.status is incoming

    def test_no_evidence_nodes_changes_nothing(self):
        payload = {"summary": "无证据节点的摘要", "answer": "42"}
        env = _envelope(payload=payload)
        result = verify_evidence(env, {"c1": "源文"})
        assert result.status is AnalysisStatus.OK
        assert result.warnings == []
        assert result.payload == payload

    def test_existing_warnings_preserved(self):
        payload = {"items": [{"evidence": [_ev("c1", "编造")]}]}
        env = _envelope(payload=payload, warnings=["既有告警"])
        result = verify_evidence(env, {"c1": "源文"})
        assert result.warnings[0] == "既有告警"
        assert len(result.warnings) == 2

    def test_non_evidence_dicts_untouched(self):
        """仅含 chunk_id（缺 quote）的 dict 不是证据节点，不参与校验。"""
        payload = {"source": {"chunk_id": "c1", "label": "来源"}, "items": []}
        result = verify_evidence(_envelope(payload=payload), {})
        assert result.payload == payload
        assert result.warnings == []

    def test_pure_function_does_not_mutate_input(self):
        payload = {"items": [{"evidence": [_ev("c1", "编造", 0.9)]}]}
        env = _envelope(payload=payload)
        verify_evidence(env, {"c1": "源文"})
        # 入参信封与 payload 不被就地修改
        assert env.payload["items"][0]["evidence"][0]["confidence"] == 0.9
        assert env.warnings == []
        assert env.status is AnalysisStatus.OK

    def test_nested_evidence_found(self):
        """证据可嵌套任意深度（items → evidence 列表）。"""
        payload = {
            "items": [
                {"name": "甲", "evidence": [_ev("c1", "源文片段")]},
                {"name": "乙", "evidence": [_ev("c2", "另一段源文")]},
            ]
        }
        sources = {"c1": "这是源文片段原文", "c2": "另一段源文在此"}
        result = verify_evidence(_envelope(payload=payload), sources)
        assert result.status is AnalysisStatus.OK
        assert result.warnings == []
