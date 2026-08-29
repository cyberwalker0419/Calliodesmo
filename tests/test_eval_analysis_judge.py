"""P6 Task 17 测试：G-Eval rubric judge + AnalysisEvalHarness 聚合。

覆盖：

- ``eval/judge_analysis.py``：rubric 四维（完整性 / 证据支撑 / 无编造 / 结构规范）
  → 1–5 结构化评分（``AnalysisJudgeScores``）；judge 自身走 Task 7 解析链
  （``analysis/parser.parse_with_retry``），解析失败降级「无分」（None）而非崩溃；
- ``eval/harness.py`` 的 ``AnalysisEvalHarness``：golden 逐例跑分析引擎 →
  确定性指标（``field_f1`` / ``tuple_f1``，QA 类 ``expected_answer`` 经
  ``answer_field_pair`` 消费）+ judge 评分 → 聚合均值与逐例明细；
- 离线桩端到端：``StubLLM`` 固定分析输出 + 固定 judge 分。

**桩对生成质量零区分度，离线证据只承诺结构 / 契约**：本文件中桩相关断言
（固定分析输出 → 确定性指标归零、judge 固定 3 分）锁的是「结构 / 契约」，
不得表述为「分析质量好」；质量证据由 ``scripts/eval_p6.py --real`` 承担
（用户本机，锚点 2026-W45，与 ``scripts/eval_p5.py --real`` 同批）。
"""

import json

import pytest

from calliodesmo.analysis.engine import DefaultAnalysisEngine
from calliodesmo.analysis.schemas import AnalysisType
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.config import Settings
from calliodesmo.eval.golden_analysis import GoldenAnalysisCase
from calliodesmo.eval.harness import (
    AnalysisCaseResult,
    AnalysisEvalHarness,
    AnalysisEvalReport,
)
from calliodesmo.eval.judge_analysis import (
    JUDGE_DIMENSIONS,
    JUDGE_MARKER,
    AnalysisJudgeScores,
    judge_analysis_report,
)
from calliodesmo.eval.metrics_analysis import PRF1
from calliodesmo.interfaces.analysis import AnalysisEngine, AnalysisReport
from calliodesmo.interfaces.llm import LLMMessage, LLMProvider, LLMResponse
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
from calliodesmo.providers.stub_llm import StubLLMProvider

#: 全可见评估上下文（与 scripts/eval_p6.py 同口径：user_id=None 命中 owner_id=None 记录）
ACCESS = AccessContext(
    user_id=None,
    username="eval",
    clearance=ClearanceLevel.SECRET,
    permissions=frozenset(p.value for p in Permission),
    library_scopes=frozenset(s.value for s in LibraryScope),
)

_VALID_JUDGE_JSON = json.dumps(
    {"completeness": 4, "evidence_support": 3, "no_fabrication": 5, "structure": 4},
    ensure_ascii=False,
)


class _FixedJudge(LLMProvider):
    """脚本化假 judge：固定返回预设原文，记录消息与温度。"""

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[list[LLMMessage]] = []
        self.temperatures: list[float] = []

    async def complete(self, messages, *, temperature=0.2, max_tokens=None):
        self.calls.append(list(messages))
        self.temperatures.append(temperature)
        return LLMResponse(
            content=self.content,
            model="fake/judge",
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        )


class _FixedEngine(AnalysisEngine):
    """假分析引擎：按 task_type 值返回预设 AnalysisReport（聚合逻辑单测用）。"""

    def __init__(self, reports: dict[str, AnalysisReport]) -> None:
        self._reports = reports
        self.calls: list[tuple] = []

    async def run(self, spec, materials, access):
        self.calls.append((spec, tuple(materials)))
        return self._reports[spec.task_type.value]


def _report(task_type: str, payload: dict, status: str = "ok") -> AnalysisReport:
    return AnalysisReport(
        task_type=AnalysisType(task_type),
        status=status,
        payload=payload,
        model="fake/model",
        prompt_version=f"{task_type}.v1",
        usage={"total_tokens": 0},
    )


def _chunk(chunk_id="d.md#0", doc_id="d.md", content="示例材料文本：北方稀土总部位于内蒙古包头。"):
    return ChunkRecord(chunk_id=chunk_id, doc_id=doc_id, content=content, vector=[], owner_id=None)


async def _store_with(*chunks) -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    await store.upsert_chunks(list(chunks))
    return store


def _case(**kwargs) -> GoldenAnalysisCase:
    base = {"case_id": "c", "task_type": "summary", "doc_ids": ["d.md"]}
    base.update(kwargs)
    return GoldenAnalysisCase(**base)


def _harness(engine, judge, store) -> AnalysisEvalHarness:
    return AnalysisEvalHarness(engine, judge, vector_store=store)


class TestAnalysisJudgeScoresModel:
    def test_valid_scores(self):
        scores = AnalysisJudgeScores.model_validate_json(_VALID_JUDGE_JSON)
        assert scores.completeness == 4
        assert scores.evidence_support == 3
        assert scores.no_fabrication == 5
        assert scores.structure == 4

    def test_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            AnalysisJudgeScores.model_validate(
                {"completeness": 0, "evidence_support": 3, "no_fabrication": 5, "structure": 4}
            )
        with pytest.raises(ValueError):
            AnalysisJudgeScores.model_validate(
                {"completeness": 6, "evidence_support": 3, "no_fabrication": 5, "structure": 4}
            )

    def test_missing_dimension_rejected(self):
        with pytest.raises(ValueError):
            AnalysisJudgeScores.model_validate(
                {"completeness": 4, "evidence_support": 3, "structure": 4}
            )

    def test_overall_is_dimension_mean(self):
        scores = AnalysisJudgeScores.model_validate_json(_VALID_JUDGE_JSON)
        assert scores.overall == pytest.approx(4.0)

    def test_dimensions_constant(self):
        assert JUDGE_DIMENSIONS == (
            "completeness",
            "evidence_support",
            "no_fabrication",
            "structure",
        )


class TestJudgeAnalysisReport:
    async def test_happy_path_returns_scores(self):
        judge = _FixedJudge(_VALID_JUDGE_JSON)
        scores = await judge_analysis_report(
            judge, task_type="summary", payload={"summary": "示例"}, material_texts=["材料一"]
        )
        assert scores is not None
        assert scores.completeness == 4

    async def test_prompt_carries_marker_rubric_report_and_materials(self):
        judge = _FixedJudge(_VALID_JUDGE_JSON)
        await judge_analysis_report(
            judge,
            task_type="qa",
            payload={"question": "总部在哪？", "answer": "内蒙古包头"},
            material_texts=["示例材料文本片段"],
            question="总部在哪？",
        )
        assert len(judge.calls) == 1
        system = next(m.content for m in judge.calls[0] if m.role == "system")
        user = next(m.content for m in judge.calls[0] if m.role == "user")
        assert JUDGE_MARKER in system  # 桩分发锚点（离线固定分路径）
        assert "完整性" in user and "证据支撑" in user and "无编造" in user and "结构规范" in user
        assert "内蒙古包头" in user  # 报告负载入提示
        assert "示例材料文本片段" in user  # 材料入提示（证据支撑 / 无编造判定依据）
        assert "总部在哪？" in user  # QA 问题入提示
        # judge 评分走确定性温度
        assert judge.temperatures == [0.0]

    async def test_parse_failure_degrades_to_none(self):
        # 解析失败降级「无分」而非崩溃（Task 17 口径）
        judge = _FixedJudge("这不是 JSON，也没有任何可抢救的结构 {{{")
        scores = await judge_analysis_report(judge, task_type="summary", payload={"summary": "x"})
        assert scores is None

    async def test_empty_output_degrades_to_none(self):
        judge = _FixedJudge("")
        assert await judge_analysis_report(judge, task_type="summary", payload={}) is None

    async def test_validation_failure_degrades_to_none(self):
        # 维度越界 → pydantic 校验失败 → 无分（不崩溃）
        judge = _FixedJudge(
            json.dumps(
                {"completeness": 99, "evidence_support": 3, "no_fabrication": 5, "structure": 4}
            )
        )
        assert await judge_analysis_report(judge, task_type="summary", payload={}) is None

    async def test_code_fence_wrapped_json_still_parses(self):
        # judge 走 Task 7 解析链：剥围栏 / 散文抢救等能力与分析主链同一实现
        judge = _FixedJudge(f"评分如下：\n```json\n{_VALID_JUDGE_JSON}\n```\n以上。")
        scores = await judge_analysis_report(judge, task_type="summary", payload={})
        assert scores is not None
        assert scores.structure == 4

    async def test_stub_judge_fixed_scores(self):
        # 离线桩固定分：**桩对生成质量零区分度，离线证据只承诺结构 / 契约**——
        # 固定分仅锁 judge 契约（消息可解析、分值在 1–5 内），不得表述为质量结论。
        scores = await judge_analysis_report(
            StubLLMProvider(), task_type="summary", payload={"summary": "任意"}
        )
        assert scores is not None
        assert all(getattr(scores, dim) == 3 for dim in JUDGE_DIMENSIONS)
        assert scores.overall == pytest.approx(3.0)


class TestAnalysisEvalHarness:
    async def test_aggregate_means_and_per_case_detail(self):
        store = await _store_with(_chunk())
        engine = _FixedEngine(
            {
                "key_information": _report(
                    "key_information",
                    {"items": [{"label": "供应方", "value": "北方稀土", "confidence": 1.0}]},
                ),
                "entity_recognition": _report(
                    "entity_recognition",
                    {"items": [{"name": "北方稀土", "type": "组织", "confidence": 1.0}]},
                ),
                "qa": _report(
                    "qa",
                    {"question": "总部在哪？", "answer": "内蒙古包头", "citations": ["d.md#0"]},
                ),
            }
        )
        harness = _harness(engine, _FixedJudge(_VALID_JUDGE_JSON), store)
        cases = [
            _case(
                case_id="ki",
                task_type="key_information",
                expected_fields=[{"label": "供应方", "value": "北方稀土"}],
            ),
            _case(
                case_id="ent",
                task_type="entity_recognition",
                expected_tuples=[("组织", "北方稀土"), ("人物", "张明")],
            ),
            _case(
                case_id="qa",
                task_type="qa",
                question="总部在哪？",
                expected_answer="内蒙古包头",
            ),
        ]
        report = await harness.run(cases, access=ACCESS)

        assert isinstance(report, AnalysisEvalReport)
        assert report.total == 3
        assert [c.case_id for c in report.cases] == ["ki", "ent", "qa"]
        assert all(isinstance(c, AnalysisCaseResult) for c in report.cases)
        # ki：字段全命中 → F1=1；ent 无字段金标 → 跳过（None）；qa：expected_answer
        # 经 answer_field_pair 消费落字段比对 → 全命中
        assert report.cases[0].field_scores == PRF1(1.0, 1.0, 1.0)
        assert report.cases[1].field_scores is None
        assert report.cases[2].field_scores == PRF1(1.0, 1.0, 1.0)
        assert report.mean_field_f1 == pytest.approx(1.0)
        # ent：元组部分命中（2 金标命中 1，预测无多余）
        assert report.cases[1].tuple_scores == PRF1(1.0, 0.5, round(2 / 3, 4))
        assert report.cases[0].tuple_scores is None
        assert report.mean_tuple_f1 == pytest.approx(round(2 / 3, 4))
        # judge 均值（四维均值 4.0）逐例落明细
        assert report.mean_judge_overall == pytest.approx(4.0)
        assert all(c.judge_scores is not None for c in report.cases)
        assert report.cases[0].judge_scores.completeness == 4
        assert report.judge_dimension_means["no_fabrication"] == pytest.approx(5.0)

    async def test_expected_answer_mismatch_scores_zero(self):
        store = await _store_with(_chunk())
        engine = _FixedEngine(
            {"qa": _report("qa", {"question": "Q?", "answer": "北京", "citations": []})}
        )
        harness = _harness(engine, None, store)
        report = await harness.run(
            [_case(case_id="qa", task_type="qa", question="Q?", expected_answer="内蒙古包头")],
            access=ACCESS,
        )
        assert report.cases[0].field_scores == PRF1(0.0, 0.0, 0.0)
        assert report.mean_field_f1 == pytest.approx(0.0)

    async def test_no_golden_skips_metrics(self):
        # 无字段 / 元组 / 答案金标 → 指标跳过（None），不误计 0 拉低均值
        store = await _store_with(_chunk())
        engine = _FixedEngine({"summary": _report("summary", {"key_points": ["任意要点"]})})
        harness = _harness(engine, None, store)
        report = await harness.run([_case(case_id="s")], access=ACCESS)
        assert report.cases[0].field_scores is None
        assert report.cases[0].tuple_scores is None
        assert report.mean_field_f1 is None
        assert report.mean_tuple_f1 is None

    async def test_timeline_projection_to_expected_keys(self):
        # 时间线金标按声明字段子集对齐：金标只给 description，预测条目含全部核心键，
        # 比对时投影到金标声明键（金标未声明的字段不计），保证参考分可标注性
        store = await _store_with(_chunk())
        engine = _FixedEngine(
            {
                "timeline": _report(
                    "timeline",
                    {
                        "items": [
                            {
                                "date_raw": "2023年",
                                "date_normalized": "2023",
                                "granularity": "approximate",
                                "description": "夜莺活跃",
                                "confidence": 1.0,
                            }
                        ]
                    },
                )
            }
        )
        harness = _harness(engine, None, store)
        report = await harness.run(
            [
                _case(
                    case_id="tl",
                    task_type="timeline",
                    expected_fields=[{"description": "夜莺活跃"}],
                )
            ],
            access=ACCESS,
        )
        assert report.cases[0].field_scores == PRF1(1.0, 1.0, 1.0)

    async def test_failed_report_records_status_without_scores(self):
        # 报告完全失败（解析预算耗尽等）：状态落明细，指标与 judge 跳过不计均值
        store = await _store_with(_chunk())
        engine = _FixedEngine({"summary": _report("summary", {}, status="failed")})
        harness = _harness(engine, _FixedJudge(_VALID_JUDGE_JSON), store)
        report = await harness.run(
            [_case(case_id="s", expected_fields=["应有要点"])], access=ACCESS
        )
        case = report.cases[0]
        assert case.status == "failed"
        assert case.field_scores is None
        assert case.judge_scores is None
        assert report.mean_field_f1 is None
        assert report.mean_judge_overall is None

    async def test_no_visible_materials_recorded_not_crash(self):
        # 无可见材料：逐例留痕跳过，不中断回归（与 worker「无可见材料」拦截同语义）
        store = await _store_with(_chunk())
        engine = _FixedEngine({"summary": _report("summary", {})})
        harness = _harness(engine, None, store)
        report = await harness.run(
            [_case(case_id="s", doc_ids=["missing.md"], expected_fields=["要点"])],
            access=ACCESS,
        )
        case = report.cases[0]
        assert case.field_scores is None
        assert any("无可见材料" in w for w in case.warnings)
        assert engine.calls == []  # 未进引擎

    async def test_judge_none_and_judge_parse_failure(self):
        store = await _store_with(_chunk())
        engine = _FixedEngine({"summary": _report("summary", {"summary": "s"})})
        # judge=None → 无 judge 分
        report = await _harness(engine, None, store).run([_case(case_id="s")], access=ACCESS)
        assert report.cases[0].judge_scores is None
        assert report.mean_judge_overall is None
        assert report.judge_dimension_means == {}
        # judge 输出不可解析 → 逐例降级无分，不崩整个回归
        report2 = await _harness(engine, _FixedJudge("垃圾输出"), store).run(
            [_case(case_id="s")], access=ACCESS
        )
        assert report2.cases[0].judge_scores is None
        assert report2.mean_judge_overall is None

    async def test_to_dict_serializable(self):
        store = await _store_with(_chunk())
        engine = _FixedEngine({"summary": _report("summary", {"summary": "s"})})
        report = await _harness(engine, _FixedJudge(_VALID_JUDGE_JSON), store).run(
            [_case(case_id="s")], access=ACCESS
        )
        data = report.to_dict()
        dumped = json.dumps(data, ensure_ascii=False)  # 全量 JSON 可序列化
        assert data["total"] == 1
        assert data["cases"][0]["case_id"] == "s"
        assert data["cases"][0]["judge_scores"]["completeness"] == 4
        assert json.loads(dumped)["cases"][0]["field_scores"] is None


class TestOfflineEndToEndStub:
    """离线桩端到端（真引擎 + 桩 LLM + 内存 store 采集）：锁结构与契约。

    **桩对生成质量零区分度，离线证据只承诺结构 / 契约**：桩固定分析输出与金标
    零重合 → 确定性指标归零；桩 judge 固定 3 分。本测试不表述为「分析质量好」。
    """

    async def test_summary_stub_full_loop(self):
        store = await _store_with(
            _chunk(chunk_id="doc.md#0", doc_id="doc.md", content="任意语料文本。")
        )
        engine = DefaultAnalysisEngine(
            llm=StubLLMProvider(), settings=Settings(_env_file=None, llm_model="test/stub")
        )
        harness = AnalysisEvalHarness(engine, StubLLMProvider(), vector_store=store)
        report = await harness.run(
            [_case(case_id="s", doc_ids=["doc.md"], expected_fields=["金标要点（桩必不命中）"])],
            access=ACCESS,
        )
        case = report.cases[0]
        assert case.status == "ok"  # 桩结构契约通过（状态机 / 报告 schema）
        assert case.field_scores is not None
        assert case.field_scores.f1 == 0.0  # 桩零区分度：确定性指标归零
        assert case.judge_scores is not None
        assert case.judge_scores.overall == pytest.approx(3.0)  # 桩固定分
        assert report.mean_judge_overall == pytest.approx(3.0)
