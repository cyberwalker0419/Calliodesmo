"""分析 golden 集：``GoldenAnalysisCase`` 数据模型 + 从 YAML 加载（P6 Task 16）。

与 P2 ``eval/golden.py`` 的 ``GoldenCase`` / ``load_golden`` 并列：QA 检索回归用
``GoldenCase``，九类分析回归用本模块。``case_id`` 逐例定位评估明细；``task_type``
取 ``AnalysisType`` 值（本模块不顶层依赖契约层，保持评估域松耦合，合法性由
``analysis/specs.py`` 注册表在消费侧把关）；``expected_answer`` 为 QA 类金标，自 P2
以来首次被指标消费（``metrics_analysis.answer_field_pair``，为空跳过该指标）。

默认路径消费 ``Settings.eval_analysis_golden_file``（Task 3 落地，
``.env.example`` 已同步）——调用侧不传 ``path`` 即取配置值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class GoldenAnalysisCase:
    """分析 golden 单例：类型 + 材料范围 + 金标（字段条目 / 元组 / QA 答案）。

    - ``expected_fields``：条目级关键字段金标（``field_f1`` 消费）；元素可为
      dict（多字段条目，如关键信息 ``{label, value}``）或标量（单值条目，如摘要要点）。
    - ``expected_tuples``： ``(类型, 头[, 尾])`` 元组金标（``tuple_f1`` 消费），
      实体识别用二元组、关系映射用三元组。
    - ``expected_answer``：QA 类标准答案（``answer_field_pair`` 消费，空 = 跳过该指标）。
    """

    case_id: str
    task_type: str
    doc_ids: list[str] = field(default_factory=list)
    relevant_chunk_ids: list[str] = field(default_factory=list)
    question: str = ""
    expected_fields: list[Any] = field(default_factory=list)
    expected_tuples: list[tuple[str, ...]] = field(default_factory=list)
    expected_answer: str = ""


def load_golden_analysis(path: str | Path | None = None) -> list[GoldenAnalysisCase]:
    """从 YAML 文件加载分析 golden 集。空文件 / 缺 ``cases`` 键返回空集。

    ``path`` 缺省时消费 ``Settings.eval_analysis_golden_file``（Task 3 配置项）。
    """
    if path is None:
        from calliodesmo.config import get_settings

        path = get_settings().eval_analysis_golden_file
    p = Path(path)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not data or "cases" not in data:
        return []
    cases: list[GoldenAnalysisCase] = []
    for item in data["cases"]:
        cases.append(
            GoldenAnalysisCase(
                case_id=item.get("case_id", ""),
                task_type=item.get("task_type", ""),
                doc_ids=item.get("doc_ids", []) or [],
                relevant_chunk_ids=item.get("relevant_chunk_ids", []) or [],
                question=item.get("question", "") or "",
                expected_fields=item.get("expected_fields", []) or [],
                expected_tuples=[tuple(t) for t in (item.get("expected_tuples", []) or [])],
                expected_answer=item.get("expected_answer", "") or "",
            )
        )
    return cases
