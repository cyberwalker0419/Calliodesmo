"""P8 Task 1：接地度指标纯函数（边界值 / 除零 / 分箱）单测。"""

from __future__ import annotations

import pytest

from calliodesmo.eval.metrics_grounding import (
    ReliabilityBin,
    citation_precision,
    citation_recall,
    claim_grounding,
    contradiction_rate,
    expected_calibration_error,
    intent_accuracy,
    uncited_claim_rate,
    unsupported_rate,
)


class TestRateMetrics:
    """比率类指标：正常值 / 除零 / 边界。"""

    def test_citation_precision_basic(self):
        assert citation_precision(3, 4) == pytest.approx(0.75)

    def test_citation_precision_empty(self):
        assert citation_precision(0, 0) == 0.0

    def test_citation_precision_all_supported(self):
        assert citation_precision(5, 5) == 1.0

    def test_citation_precision_none_supported(self):
        assert citation_precision(0, 5) == 0.0

    def test_citation_precision_clamps_out_of_range(self):
        # 计数非法（supported > total）按 1.0 封顶，不产生 >1 的比率
        assert citation_precision(7, 5) == 1.0

    def test_citation_recall_basic(self):
        assert citation_recall(["a", "b"], {"a", "b", "c", "d"}) == pytest.approx(0.5)

    def test_citation_recall_dedupes(self):
        assert citation_recall(["a", "a"], {"a", "b"}) == pytest.approx(0.5)

    def test_citation_recall_empty_gold(self):
        assert citation_recall(["a"], set()) == 0.0

    def test_claim_grounding(self):
        assert claim_grounding(8, 10) == pytest.approx(0.8)
        assert claim_grounding(0, 0) == 0.0

    def test_unsupported_rate(self):
        assert unsupported_rate(1, 10) == pytest.approx(0.1)
        assert unsupported_rate(0, 0) == 0.0

    def test_contradiction_rate(self):
        assert contradiction_rate(1, 20) == pytest.approx(0.05)
        assert contradiction_rate(0, 0) == 0.0

    def test_uncited_claim_rate(self):
        assert uncited_claim_rate(3, 6) == pytest.approx(0.5)
        assert uncited_claim_rate(0, 0) == 0.0

    def test_intent_accuracy(self):
        assert intent_accuracy(9, 10) == pytest.approx(0.9)
        assert intent_accuracy(0, 0) == 0.0


class TestExpectedCalibrationError:
    """ECE：10 桶分箱、边界、空样本、全同类。"""

    def test_perfect_calibration_is_zero(self):
        # 每桶置信与准确率一致：conf=1.0 且全对 / conf=0.0 且全错
        ece, table, n = expected_calibration_error([1.0] * 5 + [0.0] * 5, [True] * 5 + [False] * 5)
        assert ece == pytest.approx(0.0)
        assert n == 10
        assert len(table) == 10

    def test_overconfident_known_value(self):
        # 单样本 conf=0.9 但答错：|0-0.9| * 1 = 0.9
        ece, table, n = expected_calibration_error([0.9], [False])
        assert ece == pytest.approx(0.9)
        assert n == 1
        assert table[9].count == 1
        assert table[9].accuracy == 0.0

    def test_underconfident_known_value(self):
        # 单样本 conf=0.2 但答对：|1-0.2| = 0.8
        ece, _, _ = expected_calibration_error([0.2], [True])
        assert ece == pytest.approx(0.8)

    def test_mixed_weighted_average(self):
        # 桶 5（conf 0.5）：2 样本 1 对 → gap 0；桶 9（conf 0.9）：2 样本 2 对 → gap 0.1
        # ECE = (2*0 + 2*0.1) / 4 = 0.05
        ece, _, n = expected_calibration_error([0.5, 0.5, 0.9, 0.9], [True, False, True, True])
        assert ece == pytest.approx(0.05)
        assert n == 4

    def test_empty_samples(self):
        ece, table, n = expected_calibration_error([], [])
        assert ece == 0.0
        assert table == []
        assert n == 0

    def test_all_same_class(self):
        ece, _, n = expected_calibration_error([0.0] * 4, [True] * 4)
        assert ece == pytest.approx(1.0)
        assert n == 4

    def test_bin_boundaries(self):
        # 1.0 落入最后一桶（不越界）；0.0 落入第一桶
        _, table, _ = expected_calibration_error([0.0, 1.0], [True, True])
        assert table[0].count == 1
        assert table[9].count == 1

    def test_confidence_clamped(self):
        # 越界置信按 [0,1] 截断，不产生越界桶或异常
        ece, table, n = expected_calibration_error([1.5, -0.5], [True, True])
        assert n == 2
        assert table[9].count == 1
        assert table[0].count == 1
        assert 0.0 <= ece <= 1.0

    def test_reliability_table_fields(self):
        _, table, _ = expected_calibration_error([0.75, 0.75], [True, False])
        bin_ = table[7]
        assert isinstance(bin_, ReliabilityBin)
        assert bin_.lower == pytest.approx(0.7)
        assert bin_.upper == pytest.approx(0.8)
        assert bin_.count == 2
        assert bin_.avg_confidence == pytest.approx(0.75)
        assert bin_.accuracy == pytest.approx(0.5)
        assert bin_.gap == pytest.approx(0.25)

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            expected_calibration_error([0.5], [True, False])

    def test_non_binary_outcome_raises(self):
        with pytest.raises(ValueError):
            expected_calibration_error([0.5], [1])
