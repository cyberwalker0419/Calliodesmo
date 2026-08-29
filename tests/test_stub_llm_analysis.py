"""P6 Task 8 测试：StubLLM 9 类分析标记分发（逐类型契约测试，一次落齐）。

覆盖：

- 9 类各一条契约测试：桩按系统提示中 ``[ANALYSIS:<type>]`` 标记分发固定 JSON
  （含第二批未注册 4 类——桩一次落齐，避免批次间回改桩；注册表分批交付不受影响），
  输出能被 Task 5 对应报告模型 ``model_validate`` 通过；
- 时间线桩输出含 ISO 8601 归一化日期且 ``granularity`` 三值枚举齐备
  （relative 不臆造精确日期）；
- 桩输出不带证据（与输入无关的固定 JSON 无法对应真实源文子串）→ 报告模型
  缺证据自动降置信校验生效（``confidence`` 封顶 ``CONFIDENCE_CAP``）；
- 未知 ``[ANALYSIS:*]`` 标记显式报错（不静默回退抽取输出）——钉死
  「标记写错 → 静默回退抽取输出而测试不红」的坑；
- 标记分发仅认系统提示；非分析提示词保留既有回退行为（抽取 / 摘要 / 未知回退抽取，
  既有桩用例零回归）；
- 真实模板三角联动（第一批 5 类）：``render_prompt`` 产物系统段携带标记 → 桩分发
  → 对应报告模型校验通过，锁定模板 ↔ 标记 ↔ 桩 ↔ 模型四方契约。
"""

import dataclasses
import json

import pytest

from calliodesmo.analysis.prompts import load_template, render_prompt
from calliodesmo.analysis.schemas import (
    CONFIDENCE_CAP,
    ActionItemReport,
    AnalysisType,
    ConceptReport,
    CustomReport,
    EntityRecognitionReport,
    KeyInfoReport,
    QAReport,
    RelationMappingReport,
    SummaryReport,
    TimelineGranularity,
    TimelineReport,
)
from calliodesmo.analysis.specs import BUILTIN_ANALYSIS_SPECS, get_spec
from calliodesmo.interfaces.llm import LLMMessage
from calliodesmo.providers.stub_llm import StubLLMProvider

#: 9 类标记 → 对应报告模型（含第二批未注册类型：桩一次落齐，交付分批由注册表控制）
_TYPE_TO_MODEL: dict[AnalysisType, type] = {
    AnalysisType.SUMMARY: SummaryReport,
    AnalysisType.KEY_INFORMATION: KeyInfoReport,
    AnalysisType.TIMELINE: TimelineReport,
    AnalysisType.ENTITY_RECOGNITION: EntityRecognitionReport,
    AnalysisType.RELATION_MAPPING: RelationMappingReport,
    AnalysisType.TASKS: ActionItemReport,
    AnalysisType.CONCEPTS: ConceptReport,
    AnalysisType.QA: QAReport,
    AnalysisType.CUSTOM: CustomReport,
}

_ALL_TYPES = list(_TYPE_TO_MODEL)


@dataclasses.dataclass(frozen=True)
class _Material:
    """测试用材料替身：满足 render_prompt 的鸭子类型形状（chunk_id / text）。"""

    chunk_id: str
    text: str


def _analysis_messages(task_type: AnalysisType) -> list[LLMMessage]:
    """构造最小分析提示词：系统段仅含标记与角色声明。

    刻意不含「抽取 / 摘要 / entities」等既有分发裸词——本测试验证的是标记分发本身，
    若桩回落到关键词分支（静默回退），对应报告模型校验必红。
    """
    system = f"[ANALYSIS:{task_type.value}]\n你是情报分析引擎。严格只输出一个 JSON 对象。"
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content="请分析以下材料：\n[chunk_id=c0]\n示例材料文本。"),
    ]


async def _validated_report(task_type: AnalysisType):
    """请求桩并经对应报告模型校验（契约测试共用路径）。"""
    resp = await StubLLMProvider().complete(_analysis_messages(task_type))
    return _TYPE_TO_MODEL[task_type].model_validate(json.loads(resp.content))


class TestAnalysisMarkerDispatch:
    """9 类各一条：桩按 [ANALYSIS:<type>] 标记分发，输出过对应报告模型校验。"""

    @pytest.mark.parametrize("task_type", _ALL_TYPES, ids=[t.value for t in _ALL_TYPES])
    async def test_stub_output_passes_report_model(self, task_type):
        report = await _validated_report(task_type)
        assert report is not None

    @pytest.mark.parametrize("task_type", _ALL_TYPES, ids=[t.value for t in _ALL_TYPES])
    async def test_response_metadata(self, task_type):
        """桩响应元数据保持既有形状（模型名与 usage 口径不变）。"""
        resp = await StubLLMProvider().complete(_analysis_messages(task_type))
        assert resp.model == "test/stub"
        assert "total_tokens" in resp.usage


class TestTimelineStubContract:
    """时间线桩输出：ISO 8601 归一化日期 + granularity 三值枚举取值齐备。"""

    async def test_timeline_iso_dates_and_granularity_values(self):
        report = await _validated_report(AnalysisType.TIMELINE)
        assert isinstance(report, TimelineReport)
        assert report.items
        # ISO 归一化日期存在（exact / approximate 必须提供）
        assert any(event.date_normalized for event in report.items)
        # granularity 三值枚举齐备（契约测试锁定枚举取值）
        granularities = {event.granularity for event in report.items}
        assert granularities == set(TimelineGranularity)
        for event in report.items:
            if event.granularity is TimelineGranularity.RELATIVE:
                # 模糊时间落 relative 且缺省归一化日期（不臆造精确日期）
                assert event.date_normalized is None
            else:
                assert event.date_normalized


class TestStubOutputIsStructuralOnly:
    """桩固定输出与输入无关 → 不带证据：模型缺证据自动降置信生效（离线只承诺结构）。"""

    async def test_aggregate_confidence_capped_without_evidence(self):
        summary = await _validated_report(AnalysisType.SUMMARY)
        assert summary.evidence == []
        assert summary.confidence == CONFIDENCE_CAP

    async def test_item_confidence_capped_without_evidence(self):
        report = await _validated_report(AnalysisType.ENTITY_RECOGNITION)
        assert report.items
        assert all(item.evidence == [] for item in report.items)
        assert all(item.confidence == CONFIDENCE_CAP for item in report.items)


class TestUnknownAnalysisMarker:
    """未知 [ANALYSIS:*] 标记显式报错——不静默回退抽取输出（钉死标记写错的坑）。"""

    @pytest.mark.parametrize(
        "marker",
        [
            "not_a_type",  # 未定义类型
            "SUMMARY",  # 大小写错误（标记取值 = AnalysisType 值，小写）
            "",  # 空标记
        ],
    )
    async def test_unknown_marker_raises(self, marker):
        msgs = [
            LLMMessage(role="system", content=f"[ANALYSIS:{marker}]\n你是情报分析引擎。"),
            LLMMessage(role="user", content="请分析以下材料"),
        ]
        with pytest.raises(ValueError, match="ANALYSIS"):
            await StubLLMProvider().complete(msgs)


class TestNonAnalysisFallbackPreserved:
    """非分析提示词保留既有回退行为（既有抽取 / 检索桩用例零回归）。"""

    async def test_marker_in_user_message_not_dispatched(self):
        """标记分发仅认系统提示：标记只出现在用户段时按既有行为回退抽取。"""
        msgs = [
            LLMMessage(role="system", content="随机任务"),
            LLMMessage(role="user", content="[ANALYSIS:summary]"),
        ]
        data = json.loads((await StubLLMProvider().complete(msgs)).content)
        assert "entities" in data  # 回退为抽取（既有行为）

    async def test_unknown_prompt_without_marker_still_falls_back(self):
        msgs = [LLMMessage(role="system", content="随机任务"), LLMMessage(role="user", content="?")]
        data = json.loads((await StubLLMProvider().complete(msgs)).content)
        assert "entities" in data  # 回退为抽取（既有行为）

    async def test_extraction_keywords_without_marker_unchanged(self):
        msgs = [
            LLMMessage(role="system", content="你是知识图谱抽取引擎。"),
            LLMMessage(role="user", content="抽取这些文本"),
        ]
        data = json.loads((await StubLLMProvider().complete(msgs)).content)
        assert set(data) >= {"entities", "relations", "claims", "covariates"}


class TestRenderedTemplateDrivesStub:
    """模板三角联动（第一批 5 类）：真实模板渲染产物驱动桩分发并过模型校验。"""

    @pytest.mark.parametrize(
        "task_type",
        list(BUILTIN_ANALYSIS_SPECS),
        ids=[t.value for t in BUILTIN_ANALYSIS_SPECS],
    )
    async def test_rendered_template_system_dispatches(self, task_type):
        spec = get_spec(task_type)
        rendered = render_prompt(
            load_template(spec.template_name),
            task_type,
            materials=[_Material(chunk_id="c0", text="示例材料文本。")],
            question="示例问题（仅 qa 模板消费）",
        )
        msgs = [
            LLMMessage(role="system", content=rendered.system),
            LLMMessage(role="user", content=rendered.user),
        ]
        payload = json.loads((await StubLLMProvider().complete(msgs)).content)
        report = spec.output_cls.model_validate(payload)
        assert report is not None
