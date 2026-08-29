"""P6 Task 5 测试：报告契约 II——9 类报告模型 + AnalysisTaskSpec 注册表（纯逻辑，无夹具）。

覆盖：
- 9 类报告 pydantic 模型各一条正例 + 关键反例（字段集合锁定 / 空白核心字段拒绝 / extra 字段拒绝）；
- 每条 item 的 ``confidence`` 0–1 区间校验 + 缺证据自动降置信（封顶 ``CONFIDENCE_CAP``，
  取 min：原置信更低不上调）；聚合形态（Summary / QA / Custom）置信与证据在顶层，
  条目形态（其余六类）在每条 item 上，同一契约基类承载；
- 时间线 ``date_normalized`` ISO 8601 校验（宽松年 / 月精度，拒非法历法与非 ISO 格式）、
  ``granularity`` 三值枚举、exact / approximate 必须给归一化日期、relative 允许缺省
  （模糊时间不得臆造精确日期）；
- ``AnalysisTaskSpec`` 注册表：本批注册 5 类（summary / key_information / timeline /
  entity_recognition / qa），未注册类型（第二批 3 类 + custom）``get_spec`` 抛 ``KeyError``
  （API 层转 400，未交付类型天然不可提交）；
- ``build_custom_spec`` 仅声明 / 占位，实现留 Task 22（2026-W44）。
"""

import dataclasses

import pytest
from pydantic import ValidationError

from calliodesmo.analysis.evidence import CONFIDENCE_CAP
from calliodesmo.analysis.schemas import (
    ActionItem,
    ActionItemReport,
    AnalysisType,
    ConceptItem,
    ConceptReport,
    CustomReport,
    EntityRecognitionReport,
    Evidence,
    KeyInfoItem,
    KeyInfoReport,
    QAReport,
    RecognizedEntity,
    RelationItem,
    RelationMappingReport,
    SummaryReport,
    TimelineEvent,
    TimelineGranularity,
    TimelineReport,
)
from calliodesmo.analysis.specs import (
    BUILTIN_ANALYSIS_SPECS,
    AnalysisTaskSpec,
    build_custom_spec,
    get_spec,
)

#: 9 类模型字段集合锁定（契约完整，增删字段须过计划变更）
_EXPECTED_MODEL_FIELDS: list[tuple[type, set[str]]] = [
    (SummaryReport, {"confidence", "evidence", "summary", "key_points"}),
    (KeyInfoReport, {"items"}),
    (KeyInfoItem, {"confidence", "evidence", "label", "value"}),
    (TimelineReport, {"items"}),
    (
        TimelineEvent,
        {"confidence", "evidence", "date_raw", "date_normalized", "granularity", "description"},
    ),
    (EntityRecognitionReport, {"items"}),
    (RecognizedEntity, {"confidence", "evidence", "name", "type", "description"}),
    (RelationMappingReport, {"items"}),
    (RelationItem, {"confidence", "evidence", "head", "tail", "type", "description"}),
    (ActionItemReport, {"items"}),
    (ActionItem, {"confidence", "evidence", "action", "owner_raw", "deadline_raw"}),
    (ConceptReport, {"items"}),
    (ConceptItem, {"confidence", "evidence", "name", "definition", "related"}),
    (QAReport, {"confidence", "evidence", "question", "answer", "citations"}),
    (CustomReport, {"confidence", "evidence", "fields"}),
]

#: 带 confidence/evidence 契约的模型与各自最小合法入参（条目形态六类 + 聚合形态三类）
_CONFIDENCE_CARRIERS: list[tuple[type, dict]] = [
    (KeyInfoItem, {"label": "时间", "value": "2026-08-29"}),
    (TimelineEvent, {"date_raw": "三天后", "granularity": "relative"}),
    (RecognizedEntity, {"name": "甲公司"}),
    (RelationItem, {"head": "甲公司", "tail": "乙公司", "type": "合作"}),
    (ActionItem, {"action": "提交报告"}),
    (ConceptItem, {"name": "知识图谱"}),
    (SummaryReport, {"summary": "材料概述了项目进展。"}),
    (QAReport, {"question": "何时立项？", "answer": "2026-08-29"}),
    (CustomReport, {}),
]

_FIRST_BATCH = [
    AnalysisType.SUMMARY,
    AnalysisType.KEY_INFORMATION,
    AnalysisType.TIMELINE,
    AnalysisType.ENTITY_RECOGNITION,
    AnalysisType.QA,
]

_EXPECTED_OUTPUT_CLS = {
    AnalysisType.SUMMARY: SummaryReport,
    AnalysisType.KEY_INFORMATION: KeyInfoReport,
    AnalysisType.TIMELINE: TimelineReport,
    AnalysisType.ENTITY_RECOGNITION: EntityRecognitionReport,
    AnalysisType.QA: QAReport,
}


def _ev(chunk_id: str = "c1", quote: str = "源文片段") -> dict:
    """构造证据节点（Evidence.model_dump 形状）。"""
    return {"chunk_id": chunk_id, "quote": quote}


class TestModelFieldContracts:
    """9 类模型字段集合锁定。"""

    @pytest.mark.parametrize(
        ("cls", "fields"),
        _EXPECTED_MODEL_FIELDS,
        ids=[cls.__name__ for cls, _ in _EXPECTED_MODEL_FIELDS],
    )
    def test_field_set(self, cls, fields):
        assert set(cls.model_fields) == fields


class TestSummaryReport:
    def test_valid_with_evidence(self):
        report = SummaryReport(
            summary="材料概述了项目进展。",
            key_points=["节点一", "节点二"],
            confidence=0.9,
            evidence=[Evidence(chunk_id="c1", quote="源文片段")],
        )
        assert report.summary == "材料概述了项目进展。"
        assert report.key_points == ["节点一", "节点二"]
        assert report.confidence == 0.9

    def test_round_trip(self):
        report = SummaryReport(
            summary="概述", key_points=["要点"], evidence=[Evidence(chunk_id="c1", quote="q")]
        )
        assert SummaryReport.model_validate(report.model_dump()) == report

    @pytest.mark.parametrize("bad", ["", "   "])
    def test_blank_summary_rejected(self, bad):
        with pytest.raises(ValidationError):
            SummaryReport(summary=bad)

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            SummaryReport(summary="概述", hallucinated="x")


class TestKeyInfoReport:
    def test_valid_items(self):
        report = KeyInfoReport(
            items=[{"label": "时间", "value": "2026-08-29", "confidence": 0.8, "evidence": [_ev()]}]
        )
        item = report.items[0]
        assert isinstance(item, KeyInfoItem)
        assert (item.label, item.value, item.confidence) == ("时间", "2026-08-29", 0.8)

    def test_items_default_empty(self):
        assert KeyInfoReport().items == []

    @pytest.mark.parametrize("field", ["label", "value"])
    def test_blank_core_field_rejected(self, field):
        raw = {"label": "时间", "value": "2026-08-29"}
        raw[field] = "  "
        with pytest.raises(ValidationError):
            KeyInfoReport(items=[raw])


class TestTimelineReport:
    def test_valid_exact_event(self):
        report = TimelineReport(
            items=[
                {
                    "date_raw": "2026年8月29日",
                    "date_normalized": "2026-08-29",
                    "granularity": "exact",
                    "description": "项目立项",
                    "evidence": [_ev()],
                }
            ]
        )
        event = report.items[0]
        assert isinstance(event, TimelineEvent)
        assert event.granularity is TimelineGranularity.EXACT
        assert event.date_normalized == "2026-08-29"

    def test_granularity_three_values(self):
        assert {member.value for member in TimelineGranularity} == {
            "exact",
            "approximate",
            "relative",
        }

    def test_invalid_granularity_rejected(self):
        with pytest.raises(ValidationError):
            TimelineReport(items=[{"date_raw": "昨天", "granularity": "daily"}])

    @pytest.mark.parametrize(
        "normalized",
        [
            "2026",
            "2026-08",
            "2026-08-29",
            "2026-08-29T12:00",
            "2026-08-29T12:00:00Z",
            "2026-08-29T12:00:00+08:00",
        ],
    )
    def test_iso_8601_accepted(self, normalized):
        event = TimelineEvent(date_raw="x", date_normalized=normalized, granularity="approximate")
        assert event.date_normalized == normalized

    @pytest.mark.parametrize(
        "normalized",
        [
            "昨天",
            "2026-8-9",
            "2026/08/29",
            "29-08-2026",
            "2026-13-01",
            "2026-08-32",
            "2026-08-29T25:00",
        ],
    )
    def test_non_iso_rejected(self, normalized):
        with pytest.raises(ValidationError):
            TimelineEvent(date_raw="x", date_normalized=normalized, granularity="approximate")

    def test_exact_requires_normalized(self):
        with pytest.raises(ValidationError, match="date_normalized"):
            TimelineEvent(date_raw="2026年8月29日", granularity="exact")

    def test_approximate_requires_normalized(self):
        with pytest.raises(ValidationError):
            TimelineEvent(date_raw="大概去年", granularity="approximate")

    def test_relative_allows_missing_normalized(self):
        """模糊时间落 relative 且不得臆造精确日期（归一化缺省合法）。"""
        event = TimelineEvent(date_raw="三天后", granularity="relative")
        assert event.date_normalized is None

    def test_blank_date_raw_rejected(self):
        with pytest.raises(ValidationError):
            TimelineEvent(date_raw="  ", granularity="relative")


class TestEntityRecognitionReport:
    def test_valid_items(self):
        report = EntityRecognitionReport(
            items=[
                {
                    "name": "甲公司",
                    "type": "组织",
                    "description": "合同甲方",
                    "confidence": 0.7,
                    "evidence": [_ev()],
                }
            ]
        )
        item = report.items[0]
        assert isinstance(item, RecognizedEntity)
        assert (item.name, item.type, item.description) == ("甲公司", "组织", "合同甲方")

    def test_blank_name_rejected(self):
        with pytest.raises(ValidationError):
            EntityRecognitionReport(items=[{"name": "", "type": "组织"}])

    def test_type_and_description_default_empty(self):
        item = RecognizedEntity(name="甲")
        assert item.type == ""
        assert item.description == ""


class TestRelationMappingReport:
    def test_valid_items(self):
        report = RelationMappingReport(
            items=[
                {
                    "head": "甲公司",
                    "tail": "乙公司",
                    "type": "合作",
                    "description": "联合研发",
                    "evidence": [_ev()],
                }
            ]
        )
        item = report.items[0]
        assert isinstance(item, RelationItem)
        assert (item.head, item.tail, item.type) == ("甲公司", "乙公司", "合作")

    @pytest.mark.parametrize("field", ["head", "tail", "type"])
    def test_blank_core_field_rejected(self, field):
        raw = {"head": "甲公司", "tail": "乙公司", "type": "合作"}
        raw[field] = " "
        with pytest.raises(ValidationError):
            RelationMappingReport(items=[raw])


class TestActionItemReport:
    def test_valid_items(self):
        report = ActionItemReport(
            items=[
                {
                    "action": "提交季度报告",
                    "owner_raw": "张三",
                    "deadline_raw": "下周五前",
                    "evidence": [_ev()],
                }
            ]
        )
        item = report.items[0]
        assert isinstance(item, ActionItem)
        assert (item.action, item.owner_raw, item.deadline_raw) == (
            "提交季度报告",
            "张三",
            "下周五前",
        )

    def test_raw_fields_default_empty(self):
        item = ActionItem(action="跟进进展")
        assert item.owner_raw == ""
        assert item.deadline_raw == ""

    def test_blank_action_rejected(self):
        with pytest.raises(ValidationError):
            ActionItemReport(items=[{"action": ""}])


class TestConceptReport:
    def test_valid_items(self):
        report = ConceptReport(
            items=[
                {
                    "name": "知识图谱",
                    "definition": "以图结构组织的知识库",
                    "related": ["实体消解"],
                    "evidence": [_ev()],
                }
            ]
        )
        item = report.items[0]
        assert isinstance(item, ConceptItem)
        assert item.related == ["实体消解"]

    def test_definition_and_related_defaults(self):
        item = ConceptItem(name="概念")
        assert item.definition == ""
        assert item.related == []

    def test_blank_name_rejected(self):
        with pytest.raises(ValidationError):
            ConceptReport(items=[{"name": "  "}])


class TestQAReport:
    def test_valid(self):
        report = QAReport(
            question="项目何时立项？",
            answer="2026年8月29日 [c1]",
            citations=["c1"],
            evidence=[Evidence(chunk_id="c1", quote="源文片段")],
        )
        assert report.citations == ["c1"]
        assert report.confidence == 1.0

    @pytest.mark.parametrize("field", ["question", "answer"])
    def test_blank_core_field_rejected(self, field):
        raw = {"question": "何时立项？", "answer": "2026-08-29"}
        raw[field] = ""
        with pytest.raises(ValidationError):
            QAReport(**raw)

    def test_citations_default_empty(self):
        report = QAReport(question="q", answer="无可引用证据")
        assert report.citations == []


class TestCustomReport:
    def test_open_fields(self):
        report = CustomReport(fields={"风险等级": "高", "条目": [1, 2]}, evidence=[_ev()])
        assert report.fields["风险等级"] == "高"
        assert report.confidence == 1.0

    def test_fields_default_empty(self):
        report = CustomReport()
        assert report.fields == {}


class TestConfidenceEvidenceContract:
    """每条 item（与聚合报告顶层）的 confidence 0–1 校验 + 缺证据自动降置信。"""

    @pytest.mark.parametrize(
        ("cls", "kwargs"),
        _CONFIDENCE_CARRIERS,
        ids=[cls.__name__ for cls, _ in _CONFIDENCE_CARRIERS],
    )
    def test_default_confidence_capped_without_evidence(self, cls, kwargs):
        """缺证据：默认置信 1.0 自动降至封顶值（不臆造高置信）。"""
        obj = cls(**kwargs)
        assert obj.evidence == []
        assert obj.confidence == CONFIDENCE_CAP

    @pytest.mark.parametrize(
        ("cls", "kwargs"),
        _CONFIDENCE_CARRIERS,
        ids=[cls.__name__ for cls, _ in _CONFIDENCE_CARRIERS],
    )
    def test_explicit_confidence_capped_without_evidence(self, cls, kwargs):
        obj = cls(**kwargs, confidence=0.9)
        assert obj.confidence == CONFIDENCE_CAP

    @pytest.mark.parametrize(
        ("cls", "kwargs"),
        _CONFIDENCE_CARRIERS,
        ids=[cls.__name__ for cls, _ in _CONFIDENCE_CARRIERS],
    )
    def test_lower_confidence_kept_without_evidence(self, cls, kwargs):
        """封顶取 min：原置信低于封顶值不上调。"""
        obj = cls(**kwargs, confidence=0.2)
        assert obj.confidence == 0.2

    @pytest.mark.parametrize(
        ("cls", "kwargs"),
        _CONFIDENCE_CARRIERS,
        ids=[cls.__name__ for cls, _ in _CONFIDENCE_CARRIERS],
    )
    def test_evidence_present_keeps_confidence(self, cls, kwargs):
        obj = cls(**kwargs, confidence=0.9, evidence=[Evidence(chunk_id="c1", quote="q")])
        assert obj.confidence == 0.9

    @pytest.mark.parametrize(("cls", "kwargs"), _CONFIDENCE_CARRIERS[:2])
    @pytest.mark.parametrize("bound", [0.0, 1.0])
    def test_confidence_boundaries(self, cls, kwargs, bound):
        obj = cls(**kwargs, confidence=bound, evidence=[Evidence(chunk_id="c1", quote="q")])
        assert obj.confidence == bound

    @pytest.mark.parametrize(("cls", "kwargs"), _CONFIDENCE_CARRIERS[:2])
    @pytest.mark.parametrize("bad", [-0.1, 1.01])
    def test_confidence_out_of_range_rejected(self, cls, kwargs, bad):
        with pytest.raises(ValidationError):
            cls(**kwargs, confidence=bad)


class TestAnalysisTaskSpec:
    def test_field_contract(self):
        assert {field.name for field in dataclasses.fields(AnalysisTaskSpec)} == {
            "type",
            "output_cls",
            "template_name",
            "stub_marker",
            "max_retries",
        }

    def test_frozen(self):
        spec = get_spec(AnalysisType.SUMMARY)
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.max_retries = 5


class TestRegistry:
    def test_first_batch_registered_exactly(self):
        """本批只注册 5 类（契约完整、交付分批）；第二批与 custom 未注册。"""
        assert set(BUILTIN_ANALYSIS_SPECS) == set(_FIRST_BATCH)

    @pytest.mark.parametrize("task_type", _FIRST_BATCH)
    def test_get_spec_fields(self, task_type):
        spec = get_spec(task_type)
        assert isinstance(spec, AnalysisTaskSpec)
        assert spec.type is task_type
        assert spec.output_cls is _EXPECTED_OUTPUT_CLS[task_type]
        assert spec.template_name == f"{task_type.value}.txt"
        assert spec.stub_marker == f"[ANALYSIS:{task_type.value}]"
        assert spec.max_retries is None  # None = 用全局 analysis_parse_retries

    def test_get_spec_accepts_str(self):
        assert get_spec("summary").type is AnalysisType.SUMMARY

    @pytest.mark.parametrize(
        "task_type",
        [
            AnalysisType.RELATION_MAPPING,
            AnalysisType.TASKS,
            AnalysisType.CONCEPTS,
            AnalysisType.CUSTOM,
        ],
    )
    def test_unregistered_raises_key_error(self, task_type):
        """未注册类型抛 KeyError（API 层转 400）——未交付类型天然不可提交。"""
        with pytest.raises(KeyError):
            get_spec(task_type)

    @pytest.mark.parametrize("value", ["relation_mapping", "tasks", "concepts", "custom"])
    def test_unregistered_str_raises_key_error(self, value):
        with pytest.raises(KeyError):
            get_spec(value)

    def test_invalid_type_str_raises_value_error(self):
        with pytest.raises(ValueError):
            get_spec("bogus")


class TestBuildCustomSpec:
    def test_placeholder_not_implemented(self):
        """声明 / 占位：实现留 Task 22（2026-W44，sanitize + 注入防御）。"""
        with pytest.raises(NotImplementedError):
            build_custom_spec("自由指令", {"type": "object"})
