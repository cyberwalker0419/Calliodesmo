"""P8 接地度指标：单一事实源（纯函数、无夹具、无 LLM、无 numpy）。

与 P2 ``eval/metrics.py``（context_recall / faithfulness / answer_relevance）和
P6 ``eval/metrics_analysis.py``（字段 / 元组 P-R-F1）并列：本模块只做**接地度与
校准**的确定性计量，供 ``scripts/eval_p8.py`` 与验证报告消费。

口径约定：
- 所有比率在分母为 0 时返回 ``0.0``（不抛异常、不返回 NaN）；
- 计数类入参非法（如 supported > total）按 ``[0, 1]`` 截断，保证比率有界；
- ``expected_calibration_error`` 为等宽 10 桶（可配）分箱，返回
  ``(ece, reliability_table, sample_count)``；空样本返回 ``(0.0, [], 0)``；
- 置信越界按 ``[0, 1]`` 截断后入桶，``1.0`` 落入最后一桶。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

__all__ = [
    "ReliabilityBin",
    "citation_precision",
    "citation_recall",
    "claim_grounding",
    "contradiction_rate",
    "expected_calibration_error",
    "intent_accuracy",
    "uncited_claim_rate",
    "unsupported_rate",
]


def _ratio(numerator: int | float, denominator: int | float) -> float:
    """安全比率：分母 0 → 0.0；结果截断到 [0, 1]。"""
    if denominator <= 0:
        return 0.0
    return min(max(float(numerator) / float(denominator), 0.0), 1.0)


def citation_precision(supported_citations: int, total_citations: int) -> float:
    """引注精确率：被核验为 supported 的引注数 / 引注总数。"""
    return _ratio(supported_citations, total_citations)


def citation_recall(hit_chunk_ids: Iterable[str], gold_chunk_ids: Iterable[str]) -> float:
    """引注召回率：命中金标证据块数 / 金标证据块总数（集合语义，重复入参去重）。"""
    gold = set(gold_chunk_ids)
    hits = len(set(hit_chunk_ids) & gold)
    return _ratio(hits, len(gold))


def claim_grounding(supported_claims: int, checkable_claims: int) -> float:
    """整体接地度：supported 声明数 / 可核查声明总数。"""
    return _ratio(supported_claims, checkable_claims)


def unsupported_rate(unsupported_claims: int, checkable_claims: int) -> float:
    """幻觉面（无证据支撑）：unsupported 声明数 / 可核查声明总数。"""
    return _ratio(unsupported_claims, checkable_claims)


def contradiction_rate(contradicted_claims: int, checkable_claims: int) -> float:
    """冲突面：contradicted 声明数 / 可核查声明总数。"""
    return _ratio(contradicted_claims, checkable_claims)


def uncited_claim_rate(uncited_claims: int, checkable_claims: int) -> float:
    """引注纪律：无引注的可核查声明数 / 可核查声明总数。"""
    return _ratio(uncited_claims, checkable_claims)


def intent_accuracy(correct_routes: int, labeled_queries: int) -> float:
    """意图路由质量：路由正确数 / 标注查询数。"""
    return _ratio(correct_routes, labeled_queries)


@dataclass(frozen=True)
class ReliabilityBin:
    """可靠性表单桶：区间 [lower, upper)、样本数、平均置信、准确率与差值。"""

    lower: float
    upper: float
    count: int
    avg_confidence: float
    accuracy: float
    gap: float


def expected_calibration_error(
    confidences: Sequence[float],
    outcomes: Sequence[bool],
    *,
    bins: int = 10,
) -> tuple[float, list[ReliabilityBin], int]:
    """等宽分箱期望校准误差（ECE）。

    参数:
        confidences: 每条样本的自报 / 校准后置信（越界按 [0, 1] 截断）。
        outcomes: 每条样本是否正确（必须与 ``confidences`` 等长；仅接受 bool）。
        bins: 桶数（默认 10）。

    返回:
        ``(ece, reliability_table, sample_count)``；空样本返回 ``(0.0, [], 0)``。
        可靠性表固定 ``bins`` 项（按区间升序），空桶计数 0、其余字段 0.0，
        便于报告端按桶号稳定索引。
    """
    if len(confidences) != len(outcomes):
        raise ValueError("confidences 与 outcomes 长度必须一致")
    if bins < 1:
        raise ValueError("bins 必须 ≥ 1")
    if any(not isinstance(o, bool) for o in outcomes):
        raise ValueError("outcomes 必须为 bool 序列")

    n = len(confidences)
    if n == 0:
        return 0.0, [], 0

    counts = [0] * bins
    conf_sums = [0.0] * bins
    correct_counts = [0] * bins
    for raw_conf, outcome in zip(confidences, outcomes, strict=True):
        conf = min(max(float(raw_conf), 0.0), 1.0)
        idx = min(int(conf * bins), bins - 1)
        counts[idx] += 1
        conf_sums[idx] += conf
        correct_counts[idx] += 1 if outcome else 0

    table: list[ReliabilityBin] = []
    ece = 0.0
    width = 1.0 / bins
    for idx in range(bins):
        if counts[idx] == 0:
            table.append(
                ReliabilityBin(
                    lower=round(idx * width, 6),
                    upper=round((idx + 1) * width, 6),
                    count=0,
                    avg_confidence=0.0,
                    accuracy=0.0,
                    gap=0.0,
                )
            )
            continue
        avg_conf = conf_sums[idx] / counts[idx]
        accuracy = correct_counts[idx] / counts[idx]
        gap = abs(accuracy - avg_conf)
        ece += (counts[idx] / n) * gap
        table.append(
            ReliabilityBin(
                lower=round(idx * width, 6),
                upper=round((idx + 1) * width, 6),
                count=counts[idx],
                avg_confidence=round(avg_conf, 6),
                accuracy=round(accuracy, 6),
                gap=round(gap, 6),
            )
        )
    return round(ece, 6), table, n
