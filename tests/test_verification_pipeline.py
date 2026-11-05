"""P8 Task 3：接地度侧车流水线单测（QA / 分析 payload / 越权）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from calliodesmo.verification.pipeline import build_verification

_DEMO = Path(__file__).resolve().parents[1] / "data" / "demo"
_PUBLIC = "public__rare-earth-brief.md#0"
_INTERNAL = "internal__apt28-tracking.md#0"
_CONFIDENTIAL = "confidential__nightingale-assessment.md#0"


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    return {f"{p.name}#0": p.read_text(encoding="utf-8") for p in sorted(_DEMO.glob("*.md"))}


class TestQaAnswer:
    """QA 答案：句子切分 + 引注解析。"""

    def test_cited_sentences_verified(self, sources):
        answer = (
            "镨钕氧化物用于制造钕铁硼永磁材料 [public__rare-earth-brief.md#0]。"
            "APT28 的指挥部位于圣彼得堡 [internal__apt28-tracking.md#0]。"
        )
        sidecar = build_verification(source="qa", sources=sources, answer=answer)
        assert sidecar["totals"]["claims"] == 2
        assert sidecar["totals"]["citations"] == 2
        assert sidecar["totals"]["citations_supported"] == 1
        assert sidecar["totals"]["supported"] == 1
        assert sidecar["totals"]["unsupported"] == 1
        assert sidecar["metrics"]["citation_precision"] == 0.5

    def test_uncited_sentence_counted_separately(self, sources):
        sidecar = build_verification(source="qa", sources=sources, answer="稀土市场保持平稳。")
        assert sidecar["totals"]["uncited"] == 1
        assert sidecar["totals"]["checkable"] == 0
        assert sidecar["metrics"]["uncited_claim_rate"] == 1.0
        assert sidecar["needs_review"] is False

    def test_invisible_citation_not_leaked(self, sources):
        public_only = {k: v for k, v in sources.items() if not k.startswith("confidential__")}
        answer = "夜莺组织活跃于东南亚地区 [confidential__nightingale-assessment.md#0]。"
        sidecar = build_verification(source="qa", sources=public_only, answer=answer)
        claim = sidecar["claims"][0]
        assert claim["verdict"] == "unsupported"
        assert claim["evidence"] == []
        assert "夜莺组织活跃" not in str(claim["evidence"])

    def test_contradiction_marks_review(self, sources):
        answer = "夜莺组织的威胁等级低 [confidential__nightingale-assessment.md#0]。"
        sidecar = build_verification(source="qa", sources=sources, answer=answer)
        assert sidecar["totals"]["contradicted"] == 1
        assert sidecar["needs_review"] is True


class TestAnalysisPayload:
    """分析 payload：Evidence 节点引注 + 文本字段跨文档核验。"""

    def test_payload_sidecar(self, sources):
        payload = {
            "summary": "镨钕氧化物报价小幅上行。APT28 使用 LockBit 勒索软件。",
            "evidence": [
                {"chunk_id": _PUBLIC, "quote": "镨钕氧化物报价小幅上行", "confidence": 0.9},
                {"chunk_id": _PUBLIC, "quote": "并不存在的引文", "confidence": 0.9},
            ],
        }
        sidecar = build_verification(source="analysis", sources=sources, payload=payload)
        assert sidecar["totals"]["citations"] == 2
        assert sidecar["totals"]["citations_supported"] == 1
        assert sidecar["totals"]["uncited"] == 2
        assert sidecar["metrics"]["citation_precision"] == 0.5
        assert sidecar["needs_review"] is True

    def test_payload_evidence_requires_visible_chunk(self, sources):
        public_only = {k: v for k, v in sources.items() if not k.startswith("confidential__")}
        payload = {"evidence": [{"chunk_id": _CONFIDENTIAL, "quote": "威胁等级高"}]}
        sidecar = build_verification(source="analysis", sources=public_only, payload=payload)
        assert sidecar["claims"][0]["verdict"] == "unsupported"
        assert sidecar["claims"][0]["evidence"] == []

    def test_payload_without_text_or_evidence(self, sources):
        sidecar = build_verification(source="analysis", sources=sources, payload={})
        assert sidecar["totals"]["claims"] == 0
        assert sidecar["needs_review"] is False


class TestShapeAndDeterminism:
    """侧车形状稳定、可 JSON 序列化、同输入同输出。"""

    def test_json_serializable_and_versioned(self, sources):
        import json

        sidecar = build_verification(source="agent", sources=sources, answer="测试答案。")
        json.dumps(sidecar, ensure_ascii=False)
        assert sidecar["version"] == 1
        assert sidecar["source"] == "agent"
        assert set(sidecar["metrics"]) == {
            "citation_precision",
            "claim_grounding",
            "unsupported_rate",
            "contradiction_rate",
            "uncited_claim_rate",
            "calibrated_confidence",
        }

    def test_requires_answer_or_payload(self, sources):
        with pytest.raises(ValueError):
            build_verification(source="qa", sources=sources)

    def test_deterministic(self, sources):
        answer = "镨钕氧化物报价小幅上行 [public__rare-earth-brief.md#0]。"
        assert build_verification(source="qa", sources=sources, answer=answer) == (
            build_verification(source="qa", sources=sources, answer=answer)
        )


class TestCalibrationIntegration:
    """T4：侧车置信经温度缩放，缺切片回退恒等并留痕。"""

    def test_calibrated_confidence_uses_slice(self, sources):
        from calliodesmo.verification.calibration import (
            CalibrationParams,
            CalibrationSlice,
            Calibrator,
        )

        calibrator = Calibrator(
            params=CalibrationParams(
                slices=(
                    CalibrationSlice(
                        model="m", prompt_version="qa.v1", temperature=2.0, sample_count=120
                    ),
                )
            )
        )
        sidecar = build_verification(
            source="qa",
            sources=sources,
            answer="镨钕氧化物报价小幅上行 [public__rare-earth-brief.md#0]。",
            model="m",
            prompt_version="qa.v1",
            calibrator=calibrator,
        )
        claim = sidecar["claims"][0]
        assert claim["calibrated_confidence"] < claim["confidence"]
        assert sidecar["calibration"]["warnings"] == []

    def test_missing_slice_identity_with_warning(self, sources):
        from calliodesmo.verification.calibration import Calibrator

        sidecar = build_verification(
            source="qa",
            sources=sources,
            answer="镨钕氧化物报价小幅上行 [public__rare-earth-brief.md#0]。",
            model="unknown-model",
            prompt_version="qa.v1",
            calibrator=Calibrator(),
        )
        claim = sidecar["claims"][0]
        assert claim["calibrated_confidence"] == claim["confidence"]
        assert sidecar["calibration"]["warnings"]
