"""评估 harness：

- ``EvalHarness``：对 golden Q&A 集跑检索回归（P2），汇总均值与每条详情；
- ``AnalysisEvalHarness``：对分析 golden 集跑九类分析回归（P6 Task 17），
  聚合 ``field_f1`` / ``tuple_f1`` / G-Eval judge 均值与逐例明细。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from calliodesmo.analysis.materials import fold_graph_context, gather_materials
from calliodesmo.analysis.schemas import AnalysisType
from calliodesmo.auth.context import AccessContext
from calliodesmo.eval.golden import GoldenCase
from calliodesmo.eval.golden_analysis import GoldenAnalysisCase
from calliodesmo.eval.judge_analysis import (
    JUDGE_DIMENSIONS,
    AnalysisJudgeScores,
    judge_analysis_report,
)
from calliodesmo.eval.metrics import answer_relevance, context_recall, faithfulness
from calliodesmo.eval.metrics_analysis import PRF1, answer_field_pair, field_f1, tuple_f1
from calliodesmo.interfaces.analysis import AnalysisEngine, AnalysisSpec
from calliodesmo.interfaces.graph_store import GraphStore
from calliodesmo.interfaces.llm import LLMProvider
from calliodesmo.interfaces.retriever import SearchEngine, SearchMode
from calliodesmo.interfaces.vector_store import VectorStore


@dataclass
class CaseResult:
    question: str
    context_recall: float
    faithfulness: float
    answer_relevance: float
    answer_text: str
    source_chunk_ids: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    total: int = 0
    mean_context_recall: float = 0.0
    mean_faithfulness: float = 0.0
    mean_answer_relevance: float = 0.0
    cases: list[CaseResult] = field(default_factory=list)


class EvalHarness:
    """评估 harness：对每 golden case 跑 engine.query -> 算指标 -> 汇总。"""

    def __init__(self, engine: SearchEngine, judge: LLMProvider) -> None:
        self._engine = engine
        self._judge = judge

    async def run(self, cases: list[GoldenCase], *, access: AccessContext) -> EvalReport:
        if not cases:
            return EvalReport()
        results: list[CaseResult] = []
        for case in cases:
            mode = SearchMode(case.mode)
            answer = await self._engine.query(case.question, mode=mode, top_k=10, access=access)
            cr = context_recall(answer.source_chunk_ids, set(case.relevant_chunk_ids))
            context_texts = [c.get("content", "") for c in answer.context_chunks]
            fa = await faithfulness(answer.text, context_texts, judge=self._judge)
            ar = await answer_relevance(answer.text, case.question, judge=self._judge)
            results.append(
                CaseResult(
                    question=case.question,
                    context_recall=cr,
                    faithfulness=fa,
                    answer_relevance=ar,
                    answer_text=answer.text,
                    source_chunk_ids=answer.source_chunk_ids,
                )
            )
        n = len(results)
        report = EvalReport(
            total=n,
            mean_context_recall=round(sum(r.context_recall for r in results) / n, 4),
            mean_faithfulness=round(sum(r.faithfulness for r in results) / n, 4),
            mean_answer_relevance=round(sum(r.answer_relevance for r in results) / n, 4),
            cases=results,
        )
        return report


# ---------------------------------------------------------------------------
# P6 Task 17：分析评估 harness（field_f1 / tuple_f1 / G-Eval judge 聚合）
# ---------------------------------------------------------------------------


@dataclass
class AnalysisCaseResult:
    """分析评估逐例明细。

    - ``field_scores`` / ``tuple_scores``：``None`` = 本例无对应金标（跳过）或报告
      失败 / 无可见材料（不计入均值，避免与「低分产出」混淆）；
    - ``judge_scores``：``None`` = 未配 judge 或 judge 输出解析失败降级「无分」；
    - QA 类 ``expected_answer`` 经 ``answer_field_pair`` 折入 ``field_scores``
      （``GoldenCase.expected_answer`` 自 P2 以来的消费路径，口径见
      ``eval/metrics_analysis.answer_field_pair``）；
    - ``warnings``：逐例留痕（无可见材料 / 报告失败原因等）。
    """

    case_id: str
    task_type: str
    status: str
    field_scores: PRF1 | None
    tuple_scores: PRF1 | None
    judge_scores: AnalysisJudgeScores | None
    payload: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class AnalysisEvalReport:
    """分析评估聚合报告：``field_f1`` / ``tuple_f1`` / judge 均值 + 逐例明细。

    均值为对应指标非 ``None`` 用例的均值（4 位小数）；无非空用例时保持 ``None``。
    ``judge_dimension_means`` 为 rubric 四维各自均值（无 judge 分时为空字典）。
    """

    total: int = 0
    mean_field_f1: float | None = None
    mean_tuple_f1: float | None = None
    mean_judge_overall: float | None = None
    judge_dimension_means: dict[str, float] = field(default_factory=dict)
    cases: list[AnalysisCaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON 可序列化形态（``scripts/eval_p6.py`` 落盘证据消费）。"""
        return {
            "total": self.total,
            "mean_field_f1": self.mean_field_f1,
            "mean_tuple_f1": self.mean_tuple_f1,
            "mean_judge_overall": self.mean_judge_overall,
            "judge_dimension_means": dict(self.judge_dimension_means),
            "cases": [
                {
                    "case_id": c.case_id,
                    "task_type": c.task_type,
                    "status": c.status,
                    "field_scores": _prf1_dict(c.field_scores),
                    "tuple_scores": _prf1_dict(c.tuple_scores),
                    "judge_scores": c.judge_scores.model_dump() if c.judge_scores else None,
                    "payload": c.payload,
                    "warnings": list(c.warnings),
                }
                for c in self.cases
            ],
        }


def _prf1_dict(scores: PRF1 | None) -> dict[str, float] | None:
    """PRF1 → dict（None 透传）。"""
    if scores is None:
        return None
    return {"precision": scores.precision, "recall": scores.recall, "f1": scores.f1}


def _mean(values: Sequence[float]) -> float | None:
    """非空均值（4 位小数）；空序列返回 None（区别于 0 分）。"""
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _extract_predictions(
    task_type: AnalysisType, payload: Mapping[str, Any]
) -> tuple[list[Any], list[tuple[str, ...]], str]:
    """自报告负载抽取确定性指标入参：``(预测字段条目, 预测元组, 预测答案)``。

    抽取形状与 ``config/golden_analysis.yaml`` 金标口径一一对应（注册表类型无关：
    加类型 = 加一条分支）；``custom`` 为用户 schema 驱动的开放字段，无确定性抽取
    口径，仅参与 judge 评分。时间线条目抽取全部核心键，比对时按金标声明键投影
    （``_project_to_expected_keys``），保证金标可按字段子集标注。
    """
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    fields_out: list[Any] = []
    tuples_out: list[tuple[str, ...]] = []
    answer_out = ""
    if task_type is AnalysisType.SUMMARY:
        points = payload.get("key_points")
        fields_out = list(points) if isinstance(points, list) else []
    elif task_type is AnalysisType.KEY_INFORMATION:
        fields_out = [
            {"label": item.get("label", ""), "value": item.get("value", "")}
            for item in items
            if isinstance(item, Mapping)
        ]
    elif task_type is AnalysisType.TIMELINE:
        fields_out = [
            {
                "date_raw": item.get("date_raw", ""),
                "date_normalized": item.get("date_normalized"),
                "granularity": item.get("granularity", ""),
                "description": item.get("description", ""),
            }
            for item in items
            if isinstance(item, Mapping)
        ]
    elif task_type is AnalysisType.ENTITY_RECOGNITION:
        tuples_out = [
            (str(item.get("type", "")), str(item.get("name", "")))
            for item in items
            if isinstance(item, Mapping)
        ]
    elif task_type is AnalysisType.RELATION_MAPPING:
        tuples_out = [
            (str(item.get("type", "")), str(item.get("head", "")), str(item.get("tail", "")))
            for item in items
            if isinstance(item, Mapping)
        ]
    elif task_type is AnalysisType.TASKS:
        fields_out = [
            {
                "action": item.get("action", ""),
                "owner_raw": item.get("owner_raw", ""),
                "deadline_raw": item.get("deadline_raw", ""),
            }
            for item in items
            if isinstance(item, Mapping)
        ]
    elif task_type is AnalysisType.CONCEPTS:
        fields_out = [
            {"name": item.get("name", ""), "definition": item.get("definition", "")}
            for item in items
            if isinstance(item, Mapping)
        ]
    elif task_type is AnalysisType.QA:
        raw_answer = payload.get("answer", "")
        answer_out = str(raw_answer) if raw_answer is not None else ""
    # CUSTOM：开放字段无确定性抽取口径（仅 judge），见模块 / 函数注记
    return fields_out, tuples_out, answer_out


def _project_to_expected_keys(predicted_fields: list[Any], expected_fields: list[Any]) -> list[Any]:
    """预测条目投影到金标声明键：金标 dict 条目未声明的字段不计入比对。

    时间线等宽条目报告的金标可按字段子集标注（如只给 ``description``）；
    金标无 dict 条目时原样返回（标量条目不参与投影）。
    """
    keys = {
        key for expected in expected_fields if isinstance(expected, Mapping) for key in expected
    }
    if not keys:
        return predicted_fields
    projected: list[Any] = []
    for item in predicted_fields:
        if isinstance(item, Mapping):
            projected.append({key: value for key, value in item.items() if key in keys})
        else:
            projected.append(item)
    return projected


class AnalysisEvalHarness:
    """分析评估 harness：golden 逐例采集材料 → 引擎跑分析 → 确定性指标 + judge → 聚合。

    与 ``EvalHarness``（检索）并列；构造注入全部依赖（离线可测）：

    - ``engine``：分析引擎（离线 ``DefaultAnalysisEngine`` + ``StubLLMProvider``）；
    - ``judge``：G-Eval judge LLM；``None`` = 不跑 judge（逐例 ``judge_scores=None``）；
    - ``vector_store`` / ``graph_store``：材料采集经 ``gather_materials``（含
      ``visible_to`` 红线，与 worker 同一采集路径）；
    - ``max_chunks`` / ``max_input_chars``：采集双闸预算；``None`` = 采集器默认值。

    口径：**桩对生成质量零区分度，离线证据只承诺结构 / 契约**（离线全绿不得表述为
    「分析质量好」，质量证据仅 ``scripts/eval_p6.py --real``，锚点 2026-W45）。
    引擎传输层异常向上传播（与引擎同口径）；无可见材料逐例留痕跳过不中断回归。
    """

    def __init__(
        self,
        engine: AnalysisEngine,
        judge: LLMProvider | None,
        *,
        vector_store: VectorStore,
        graph_store: GraphStore | None = None,
        max_chunks: int | None = None,
        max_input_chars: int | None = None,
    ) -> None:
        self._engine = engine
        self._judge = judge
        self._vector_store = vector_store
        self._graph_store = graph_store
        self._max_chunks = max_chunks
        self._max_input_chars = max_input_chars

    async def run(
        self, cases: list[GoldenAnalysisCase], *, access: AccessContext
    ) -> AnalysisEvalReport:
        """逐例执行并聚合（空金标集返回空报告）。"""
        if not cases:
            return AnalysisEvalReport()
        results: list[AnalysisCaseResult] = []
        for case in cases:
            results.append(await self._run_case(case, access=access))
        return self._aggregate(results)

    async def _run_case(
        self, case: GoldenAnalysisCase, *, access: AccessContext
    ) -> AnalysisCaseResult:
        """单例执行：采集 → 引擎 → 指标 → judge；无可见材料 / 报告失败逐例留痕。"""
        task_type = AnalysisType(case.task_type)
        gathered = await gather_materials(
            vector_store=self._vector_store,
            graph_store=self._graph_store,
            access=access,
            task_type=task_type,
            doc_ids=case.doc_ids or None,
            max_chunks=self._max_chunks,
            max_input_chars=self._max_input_chars,
        )
        if not gathered.materials:
            # 与 worker「无可见材料」拦截同语义：逐例留痕跳过，不中断回归
            return AnalysisCaseResult(
                case_id=case.case_id,
                task_type=task_type.value,
                status="skipped",
                field_scores=None,
                tuple_scores=None,
                judge_scores=None,
                warnings=["无可见材料（提交范围为空或权限已变化），本例跳过"],
            )
        spec = AnalysisSpec(
            task_type=task_type,
            doc_ids=tuple(case.doc_ids) if case.doc_ids else None,
            question=case.question,
        )
        # 图谱上下文折入材料（与 worker 同一采集 / 装配路径，见 analysis/materials）
        materials = fold_graph_context(gathered)
        report = await self._engine.run(spec, materials, access)
        if report.status != "ok" and report.status != "partial":
            # 完全失败：指标与 judge 跳过（不计均值；无产出与低分产出不可比）
            return AnalysisCaseResult(
                case_id=case.case_id,
                task_type=task_type.value,
                status=report.status,
                field_scores=None,
                tuple_scores=None,
                judge_scores=None,
                payload=dict(report.payload),
                warnings=list(report.warnings) or ["报告失败（无可读原因）"],
            )

        pred_fields, pred_tuples, pred_answer = _extract_predictions(task_type, report.payload)
        field_scores = self._field_scores(case, task_type, pred_fields, pred_answer)
        tuple_scores = tuple_f1(case.expected_tuples, pred_tuples) if case.expected_tuples else None
        judge_scores = (
            await judge_analysis_report(
                self._judge,
                task_type=task_type,
                payload=report.payload,
                material_texts=[m.text for m in materials],
                question=case.question,
            )
            if self._judge is not None
            else None
        )
        return AnalysisCaseResult(
            case_id=case.case_id,
            task_type=task_type.value,
            status=report.status,
            field_scores=field_scores,
            tuple_scores=tuple_scores,
            judge_scores=judge_scores,
            payload=dict(report.payload),
            warnings=list(report.warnings),
        )

    @staticmethod
    def _field_scores(
        case: GoldenAnalysisCase,
        task_type: AnalysisType,
        pred_fields: list[Any],
        pred_answer: str,
    ) -> PRF1 | None:
        """字段级比对（含金标键投影 + QA ``expected_answer`` 消费路径）。

        QA 类 ``expected_answer`` 经 ``answer_field_pair`` 折入字段比对——
        ``GoldenCase.expected_answer`` 自 P2 以来首次被指标消费的消费路径
        （``eval/metrics_analysis.answer_field_pair``，为空跳过）。
        """
        expected = list(case.expected_fields)
        predicted = list(pred_fields)
        if task_type is AnalysisType.QA:
            pair = answer_field_pair(case.expected_answer, pred_answer)
            if pair is not None:
                expected = expected + list(pair[0])
                predicted = predicted + list(pair[1])
        if not expected:
            return None  # 无字段金标 → 跳过（不误计 0 拉低均值）
        return field_f1(expected, _project_to_expected_keys(predicted, expected))

    @staticmethod
    def _aggregate(results: list[AnalysisCaseResult]) -> AnalysisEvalReport:
        """聚合：非 None 逐例指标取均值（4 位）；judge 另出四维各自均值。"""
        scored_judges = [c.judge_scores for c in results if c.judge_scores is not None]
        dimension_means: dict[str, float] = {}
        if scored_judges:
            dimension_means = {
                dim: _mean([getattr(scores, dim) for scores in scored_judges]) or 0.0
                for dim in JUDGE_DIMENSIONS
            }
        return AnalysisEvalReport(
            total=len(results),
            mean_field_f1=_mean([c.field_scores.f1 for c in results if c.field_scores]),
            mean_tuple_f1=_mean([c.tuple_scores.f1 for c in results if c.tuple_scores]),
            mean_judge_overall=_mean([scores.overall for scores in scored_judges]),
            judge_dimension_means=dimension_means,
            cases=results,
        )
