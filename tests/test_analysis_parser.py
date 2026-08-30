"""P6 Task 7 测试：解析回退链 + 回喂重试 + 降级（纯函数无夹具，CI 可覆盖）。

覆盖（与计划「解析回退链与重试」链路逐节对应）：

- 围栏剥离（```json 语言行 / 裸围栏 / 散文包裹围栏）与散文夹 JSON 提取；
- 非法 JSON 抛 ``AnalysisParseError`` 带 200 字片段（仿 ``ecl/extractor._parse_json`` 惯例）；
- extra ``analysis``（json-repair）安装时懒加载优先修复；未安装时降级正则花括号抢救，
  两条路径经 ``sys.modules`` 桩确定性覆盖（用例链行为不依赖本机是否安装 extra）；
- pydantic 校验失败时回喂消息含 ValidationError 摘要（错误定位）+ 原输出截断片段（200 字）；
- 重试预算耗尽：部分抢救可校验字段 → status=partial；抢救不出 → 失败信号可读；
- 预算可经配置降 0（退化单次解析），``DEFAULT_PARSE_RETRIES`` 与 ``Settings`` 默认值双同步。
"""

import json
import sys
import types

import pytest
from pydantic import ValidationError

from calliodesmo.analysis.parser import (
    DEFAULT_PARSE_RETRIES,
    AnalysisParseError,
    ParseOutcome,
    build_feedback_message,
    extract_json_payload,
    parse_with_retry,
    salvage_partial_report,
    strip_code_fence,
)
from calliodesmo.analysis.schemas import (
    AnalysisStatus,
    KeyInfoReport,
    SummaryReport,
)
from calliodesmo.config import Settings


@pytest.fixture(autouse=True)
def _block_json_repair(monkeypatch):
    """默认封住 json-repair（import 抛 ImportError）：用例链行为不依赖本机是否装
    extra ``analysis``；需要修复路径的用例显式注入桩模块覆盖本夹具。"""
    monkeypatch.setitem(sys.modules, "json_repair", None)


# ---------------------------------------------------------------------------
# 围栏剥离与散文夹 JSON 提取
# ---------------------------------------------------------------------------


class TestStripCodeFence:
    def test_json_language_fence(self):
        raw = '```json\n{"summary": "摘要"}\n```'
        assert strip_code_fence(raw) == '{"summary": "摘要"}'

    def test_bare_fence(self):
        raw = '```\n{"summary": "摘要"}\n```'
        assert strip_code_fence(raw) == '{"summary": "摘要"}'

    def test_prose_wrapping_fence(self):
        raw = '好的，以下是分析结果：\n```json\n{"summary": "摘要"}\n```\n以上是全部内容。'
        assert strip_code_fence(raw) == '{"summary": "摘要"}'

    def test_no_fence_passthrough(self):
        raw = '{"summary": "摘要"}'
        assert strip_code_fence(raw) == raw

    def test_degenerate_unclosed_fence(self):
        # 收尾围栏缺失的退化形态（_parse_json 惯例：剥反引号与语言行）
        raw = '```json\n{"summary": "摘要"}'
        assert strip_code_fence(raw) == '{"summary": "摘要"}'


class TestExtractJsonPayload:
    def test_plain_object(self):
        assert extract_json_payload('{"summary": "摘要"}') == {"summary": "摘要"}

    def test_fenced_object(self):
        raw = '```json\n{"summary": "摘要", "key_points": []}\n```'
        assert extract_json_payload(raw) == {"summary": "摘要", "key_points": []}

    def test_prose_sandwich_without_fence(self):
        raw = '分析结果如下：\n{"summary": "抢救出的摘要", "key_points": []}\n请查收。'
        assert extract_json_payload(raw) == {"summary": "抢救出的摘要", "key_points": []}

    def test_braces_inside_string_value(self):
        # 花括号扫描须识别字符串边界，值内的 } 不作为结构边界
        raw = '前缀 {"summary": "含 } 与 { 的文本", "key_points": []} 后缀'
        got = extract_json_payload(raw)
        assert got["summary"] == "含 } 与 { 的文本"

    def test_empty_raw_raises(self):
        with pytest.raises(AnalysisParseError):
            extract_json_payload("")
        with pytest.raises(AnalysisParseError):
            extract_json_payload("   \n  ")

    def test_garbage_raises_with_200_char_snippet(self):
        raw = "这根本不是 JSON " * 40
        with pytest.raises(AnalysisParseError) as exc_info:
            extract_json_payload(raw)
        err = exc_info.value
        expected_snippet = raw[:200].replace("\n", " ")
        assert err.snippet == expected_snippet
        assert expected_snippet in str(err)
        assert len(err.snippet) == 200

    def test_non_object_json_raises(self):
        with pytest.raises(AnalysisParseError):
            extract_json_payload("[1, 2, 3]")
        with pytest.raises(AnalysisParseError):
            extract_json_payload('"只是一个字符串"')

    def test_multiline_snippet_replaces_newlines(self):
        raw = "第一行不是 JSON\n第二行也不是"
        with pytest.raises(AnalysisParseError) as exc_info:
            extract_json_payload(raw)
        assert "\n" not in exc_info.value.snippet


# ---------------------------------------------------------------------------
# json-repair 双路径：装了 extra 走修复，缺依赖降级正则花括号抢救
# ---------------------------------------------------------------------------


class TestJsonRepairFallback:
    def test_repair_path_when_extra_installed(self, monkeypatch):
        """装了 extra analysis：json.loads 失败后懒加载 json-repair 修复成功。"""
        repaired = json.dumps({"summary": "修复后的摘要"})
        calls: list[str] = []

        def fake_repair(text: str) -> str:
            calls.append(text)
            return repaired

        # 覆盖 autouse 夹具的封锁，注入桩模块模拟已安装 extra
        fake_module = types.SimpleNamespace(repair_json=fake_repair)
        monkeypatch.setitem(sys.modules, "json_repair", fake_module)

        broken = "{'summary': '修复后的摘要',}"  # 单引号 + 尾逗号，loads 必失败
        got = extract_json_payload(broken)
        assert got == {"summary": "修复后的摘要"}
        assert len(calls) == 1

    def test_regex_salvage_when_extra_missing(self):
        """未装 extra（autouse 夹具已封锁）：正则花括号抢救仍可提取散文夹 JSON。"""
        raw = '结果：\n{"summary": "抢救出的摘要", "key_points": []}\n完毕。'
        assert extract_json_payload(raw) == {"summary": "抢救出的摘要", "key_points": []}

    def test_missing_extra_unrepairable_raises_friendly(self):
        """未装 extra 且花括号抢救不出：抛可读的 AnalysisParseError，不泄漏 ImportError。"""
        broken = "{'summary': '单引号且尾逗号',}"
        with pytest.raises(AnalysisParseError) as exc_info:
            extract_json_payload(broken)
        message = str(exc_info.value)
        assert "ImportError" not in message
        assert "json_repair" not in message
        assert exc_info.value.snippet


# ---------------------------------------------------------------------------
# 回喂消息构造（ValidationError 摘要 + 原输出截断 200 字）
# ---------------------------------------------------------------------------


class TestBuildFeedbackMessage:
    def test_validation_error_summary_and_truncation(self):
        raw = json.dumps({"summary": ""})  # summary 空白 -> 校验失败
        with pytest.raises(ValidationError) as exc_info:
            SummaryReport.model_validate(json.loads(raw))
        message = build_feedback_message(exc_info.value, raw)
        # 错误定位（字段名）+ 可读摘要
        assert "summary" in message
        # 原输出截断片段
        assert raw[:200] in message

    def test_long_raw_truncated_to_200_chars(self):
        raw = "A" * 500
        with pytest.raises(ValidationError) as exc_info:
            SummaryReport.model_validate({"summary": ""})
        message = build_feedback_message(exc_info.value, raw)
        assert "A" * 200 in message
        assert "A" * 201 not in message

    def test_parse_error_feedback_contains_snippet(self):
        raw = "完全不是 JSON 的输出"
        with pytest.raises(AnalysisParseError) as exc_info:
            extract_json_payload(raw)
        message = build_feedback_message(exc_info.value, raw)
        assert raw in message
        assert "JSON" in message


# ---------------------------------------------------------------------------
# 部分抢救（预算耗尽后的降级）
# ---------------------------------------------------------------------------


class TestSalvagePartialReport:
    def test_items_shape_keeps_valid_items(self):
        data = {
            "items": [
                {"label": "地点", "value": "北京"},
                {"label": "", "value": ""},  # 空白核心字段 -> 非法条目
            ]
        }
        got = salvage_partial_report(data, KeyInfoReport)
        assert got is not None
        assert len(got.items) == 1
        assert got.items[0].label == "地点"

    def test_items_shape_none_when_all_invalid(self):
        data = {"items": [{"label": ""}, {"value": ""}]}
        assert salvage_partial_report(data, KeyInfoReport) is None

    def test_aggregate_shape_drops_bad_optional_field(self):
        data = {"summary": "合法摘要", "key_points": "不是列表"}
        got = salvage_partial_report(data, SummaryReport)
        assert got is not None
        assert got.summary == "合法摘要"
        assert got.key_points == []

    def test_aggregate_shape_none_when_required_missing(self):
        data = {"key_points": ["只有可选字段"]}
        assert salvage_partial_report(data, SummaryReport) is None

    def test_non_dict_returns_none(self):
        assert salvage_partial_report([1, 2], SummaryReport) is None
        assert salvage_partial_report("字符串", KeyInfoReport) is None

    def test_fully_valid_passthrough(self):
        data = {"summary": "合法摘要", "key_points": ["要点"]}
        got = salvage_partial_report(data, SummaryReport)
        assert isinstance(got, SummaryReport)
        assert got.summary == "合法摘要"


# ---------------------------------------------------------------------------
# 回喂重试编排（预算配置化，可降 0）
# ---------------------------------------------------------------------------


def _make_producer(outputs: list[str]):
    """构造记录调用的假 produce_raw：依次返回脚本化输出，入参为上轮回喂消息。"""
    calls: list[str | None] = []

    async def produce(feedback: str | None) -> str:
        calls.append(feedback)
        return outputs[min(len(calls) - 1, len(outputs) - 1)]

    return produce, calls


class TestParseWithRetry:
    async def test_ok_first_try(self):
        produce, calls = _make_producer(['{"summary": "一次通过"}'])
        outcome = await parse_with_retry(produce, SummaryReport)
        assert isinstance(outcome, ParseOutcome)
        assert outcome.status is AnalysisStatus.OK
        assert isinstance(outcome.report, SummaryReport)
        assert outcome.report.summary == "一次通过"
        assert outcome.feedback_messages == ()
        assert outcome.attempts == 1
        assert calls == [None]

    async def test_retry_recovery_with_feedback(self):
        """首次校验失败 -> 构造回喂消息 -> 二次正常。"""
        produce, calls = _make_producer(['{"summary": ""}', '{"summary": "二次修复"}'])
        outcome = await parse_with_retry(produce, SummaryReport, max_retries=2)
        assert outcome.status is AnalysisStatus.OK
        assert outcome.report.summary == "二次修复"
        assert outcome.attempts == 2
        assert len(outcome.feedback_messages) == 1
        assert calls[0] is None
        assert calls[1] is not None
        assert "summary" in calls[1]  # 回喂消息含错误定位

    async def test_budget_exhausted_salvage_partial(self):
        """预算耗尽且部分字段可校验 -> status=partial，抢救出合法条目。"""
        bad = json.dumps(
            {
                "items": [
                    {"label": "时间", "value": "2026-08-29"},
                    {"label": "", "value": ""},
                ]
            }
        )
        produce, calls = _make_producer([bad])
        outcome = await parse_with_retry(produce, KeyInfoReport, max_retries=1)
        assert outcome.status is AnalysisStatus.PARTIAL
        assert outcome.report is not None
        assert len(outcome.report.items) == 1
        assert outcome.report.items[0].label == "时间"
        assert outcome.attempts == 2  # 预算 1 -> 共 2 次尝试
        assert len(outcome.feedback_messages) == 1
        assert len(calls) == 2

    async def test_budget_exhausted_no_salvage_readable_failure(self):
        """预算耗尽且抢救不出 -> failed，失败信号可读（不静默）。"""
        produce, _ = _make_producer(['{"items": [{"label": ""}]}'])
        outcome = await parse_with_retry(produce, KeyInfoReport, max_retries=1)
        assert outcome.status is AnalysisStatus.FAILED
        assert outcome.report is None
        assert outcome.error_message  # 失败信号可读
        assert outcome.attempts == 2

    async def test_all_attempts_unparseable_failed(self):
        """全部尝试均非合法 JSON -> failed，回喂消息按重试次数构造。"""
        produce, calls = _make_producer(["这根本不是 JSON"])
        outcome = await parse_with_retry(produce, SummaryReport, max_retries=2)
        assert outcome.status is AnalysisStatus.FAILED
        assert outcome.report is None
        assert outcome.attempts == 3
        assert len(outcome.feedback_messages) == 2
        assert len(calls) == 3
        assert outcome.error_message

    async def test_budget_zero_single_attempt(self):
        """预算可降 0：单次解析，不重试。"""
        produce, calls = _make_producer(['{"summary": "零预算直出"}', '{"summary": "不会被调用"}'])
        outcome = await parse_with_retry(produce, SummaryReport, max_retries=0)
        assert outcome.status is AnalysisStatus.OK
        assert outcome.attempts == 1
        assert len(calls) == 1

    async def test_budget_zero_still_degrades(self):
        """预算 0 仍走降级：单次失败后部分抢救 -> partial。"""
        bad = json.dumps({"summary": "合法摘要", "key_points": "不是列表"})
        produce, calls = _make_producer([bad])
        outcome = await parse_with_retry(produce, SummaryReport, max_retries=0)
        assert outcome.status is AnalysisStatus.PARTIAL
        assert outcome.report.summary == "合法摘要"
        assert len(calls) == 1
        assert outcome.feedback_messages == ()

    async def test_negative_budget_clamped_to_zero(self):
        produce, calls = _make_producer(['{"summary": "负预算当零"}'])
        outcome = await parse_with_retry(produce, SummaryReport, max_retries=-3)
        assert outcome.status is AnalysisStatus.OK
        assert outcome.attempts == 1
        assert len(calls) == 1


def test_default_retries_mirrors_settings():
    """DEFAULT_PARSE_RETRIES 与 Settings.analysis_parse_retries 默认值双同步锚点。"""
    assert DEFAULT_PARSE_RETRIES == 2
    assert Settings.model_fields["analysis_parse_retries"].default == DEFAULT_PARSE_RETRIES
