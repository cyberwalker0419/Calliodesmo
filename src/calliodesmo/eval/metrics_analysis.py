"""分析评估确定性指标：字段级 / 元组级 P-R-F1（P6 Task 16，纯函数）。

与 P2 ``eval/metrics.py``（context_recall / faithfulness / answer_relevance）并列：
本模块是确定性硬指标（离线可跑、CI 友好、无 LLM 依赖）；G-Eval rubric judge
（LLM-as-judge，参考分）留 Task 17 ``judge_analysis.py``。

口径（``_prf1``）：
- 多重集双向对齐：``precision = 命中数 / 预测数``、``recall = 命中数 / 金标数``、
  ``f1`` 为调和均值；「双向」即 precision（预测 → 金标）与 recall（金标 → 预测）
  两个方向同时计量，多出金标外的预测压低 precision（幻觉惩罚）。
- 金标与预测均空 → 视为完全匹配 ``(1, 1, 1)``；
- 其余空侧按自然公式取 0（空预测 → 全零）。
- 匹配前统一规范化：去首尾空白 + 大小写折叠（``casefold``），``None`` 视为空串；
  dict 条目键序不敏感（规范化为排序后的 (键, 值) 元组）。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ["PRF1", "answer_field_pair", "field_f1", "tuple_f1"]


@dataclass(frozen=True)
class PRF1:
    """条目匹配的精确率 / 召回率 / F1（各 0–1，保留 4 位）。"""

    precision: float
    recall: float
    f1: float


def _norm_str(value: Any) -> str:
    """规范化字符串：去首尾空白 + 大小写折叠（``None`` → 空串）。"""
    if value is None:
        return ""
    return str(value).strip().casefold()


def _canonical_item(item: Any) -> tuple:
    """条目规范化形态：dict → 排序后的 (键, 值) 元组；标量 → 单值元组。"""
    if isinstance(item, Mapping):
        return tuple(sorted((_norm_str(k), _norm_str(v)) for k, v in item.items()))
    return (_norm_str(item),)


def _prf1(expected: Sequence[Any], predicted: Sequence[Any]) -> PRF1:
    """多重集双向对齐 → P/R/F1（口径见模块 docstring）。"""
    exp_counter = Counter(expected)
    pred_counter = Counter(predicted)
    n_exp = sum(exp_counter.values())
    n_pred = sum(pred_counter.values())
    if n_exp == 0 and n_pred == 0:
        return PRF1(1.0, 1.0, 1.0)
    hits = sum((exp_counter & pred_counter).values())
    precision = hits / n_pred if n_pred else 0.0
    recall = hits / n_exp if n_exp else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return PRF1(round(precision, 4), round(recall, 4), round(f1, 4))


def field_f1(expected_fields: Sequence[Any], predicted_fields: Sequence[Any]) -> PRF1:
    """条目级关键字段匹配 P/R/F1。

    元素可为 dict（多字段条目，键序不敏感）或标量（单值条目，如摘要要点）；
    匹配前逐元素规范化（见模块 docstring）。
    """
    exp = [_canonical_item(x) for x in expected_fields]
    pred = [_canonical_item(x) for x in predicted_fields]
    return _prf1(exp, pred)


def tuple_f1(
    expected_tuples: Sequence[Sequence[Any]], predicted_tuples: Sequence[Sequence[Any]]
) -> PRF1:
    """实体 / 关系 ``(类型, 头[, 尾])`` 元组双向对齐 P/R/F1。

    元组有向（头尾颠倒不算命中）、元长可变（实体二元组 / 关系三元组可同集比较）；
    匹配前逐元素规范化（见模块 docstring）。
    """
    exp = [tuple(_norm_str(part) for part in t) for t in expected_tuples]
    pred = [tuple(_norm_str(part) for part in t) for t in predicted_tuples]
    return _prf1(exp, pred)


def answer_field_pair(
    expected_answer: str, predicted_answer: str
) -> tuple[list[dict[str, str]], list[dict[str, str]]] | None:
    """装配预期 / 实际答案为 ``field_f1`` 入参对；``expected_answer`` 为空 → ``None``（跳过）。

    这是 ``GoldenCase.expected_answer`` 自 P2 以来首次被指标消费的消费路径：
    QA 类金标的 ``expected_answer`` 经本函数落入 ``field_f1`` 字段比对。
    """
    if not _norm_str(expected_answer):
        return None
    return (
        [{"answer": expected_answer.strip()}],
        [{"answer": predicted_answer.strip()}],
    )
