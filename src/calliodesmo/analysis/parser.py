"""解析回退链 + 回喂重试 + 降级：任何 provider 输出走同一条路（P6 Task 7，决策 6）。

链路（计划「解析回退链与重试」落地形态）：

    LLM 原文 → 剥 ```json 围栏 / 前后散文（沿用 ecl/extractor._parse_json 经验）
            → json.loads
            → 失败且装了 extra analysis：json-repair 修复（运行时懒加载，缺依赖跳过不报硬错）
            → 失败回退正则花括号抢救（扫描平衡花括号候选子串逐个试解析）
            → output_cls.model_validate（pydantic 业务校验，第二道闸）
            → 失败：ValidationError 摘要 + 原输出截断片段（200 字）构造回喂消息重试
            → 预算 analysis_parse_retries 耗尽：部分抢救可校验字段 → partial；
              抢救不出 → 失败信号可读

全链纯函数、无夹具、CI 可覆盖；引擎（Task 10，2026-W39）把 ``parse_with_retry`` 的
``produce_raw`` 包到真实 ``LLMProvider.complete`` 上。不引 instructor / LangChain——
吸收 OutputFixingParser / RetryWithErrorOutputParser 模式自实现（计划「范围外」锁定）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, get_args

from pydantic import BaseModel, ValidationError

from calliodesmo.analysis.schemas import AnalysisStatus

#: 回喂重试预算默认值：镜像 ``config.py`` ``Settings.analysis_parse_retries`` 默认值；
#: 引擎侧（Task 10）经 settings 显式传入。配置默认值变更须双同步
#: （``tests/test_analysis_parser.py`` 有对账断言锚点）。
DEFAULT_PARSE_RETRIES = 2

#: 错误信息与回喂消息中原输出截断片段长度（仿 ``ecl/extractor._parse_json`` 惯例）
_SNIPPET_CHARS = 200

#: 回喂消息 / 失败信号中 ValidationError 逐条错误摘要上限（防错误列表撑爆上下文）
_FEEDBACK_MAX_ERRORS = 5

#: 代码围栏块：```<语言行>\n内容```（允许散文包裹在围栏之外）
_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


class AnalysisParseError(ValueError):
    """解析回退链全部失败时抛出：消息与 ``snippet`` 均带原输出截断片段（200 字）。

    仿 ``ecl/extractor.ExtractionError`` 惯例：非法输出不静默吞，片段随错误可读、
    可回喂。``raw`` 保留全文供引擎（Task 10）构造回喂消息时自行截断。
    """

    def __init__(self, message: str, raw: str) -> None:
        super().__init__(message)
        self.raw = raw
        self.snippet = _snippet(raw)


def _snippet(raw: str) -> str:
    """原输出截断片段：前 200 字，换行压空格（仿 ``_parse_json`` 惯例）。"""
    return raw[:_SNIPPET_CHARS].replace("\n", " ")


# ---------------------------------------------------------------------------
# JSON 层：剥围栏 / 散文 → json.loads → json-repair（懒加载）→ 花括号抢救
# ---------------------------------------------------------------------------


def strip_code_fence(raw: str) -> str:
    """剥离 markdown 代码围栏（含散文包裹围栏），返回围栏内文本；无围栏仅 strip。

    收尾围栏缺失的退化形态沿用 ``_parse_json`` 惯例：剥反引号与语言行（``json`` / 空）。
    """
    text = raw.strip()
    if "```" not in text:
        return text
    match = _FENCE_RE.search(text)
    if match is not None:
        return match.group(1).strip()
    stripped = text.strip("`").strip()
    newline = stripped.find("\n")
    if newline != -1 and stripped[:newline].strip().lower() in {"json", ""}:
        stripped = stripped[newline + 1 :].strip()
    return stripped


def _try_loads_object(text: str) -> dict[str, Any] | None:
    """试解析为 JSON 对象；非法或非对象（数组 / 字符串等）返回 None。"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _load_json_repair() -> Callable[[str], Any] | None:
    """懒加载 extra ``analysis`` 的 json-repair；未安装返回 None（缺依赖不报硬错）。

    引入前核对（2026-08-29，tavily + PyPI JSON API）：最新版 0.63.4、MIT 许可、
    纯 Python 零必装依赖（仅可选 ``schema`` extra 需 jsonschema / pydantic）、
    requires-python >=3.10，满足「轻量纯 Python、宽松许可」引入条件。
    """
    try:
        from json_repair import repair_json
    except ImportError:
        return None
    return repair_json


def _try_repair(text: str, repair: Callable[[str], Any]) -> dict[str, Any] | None:
    """json-repair 修复后试解析；修复异常或结果非对象返回 None（静默回退下一路径）。"""
    try:
        repaired = repair(text)
    except Exception:  # 第三方修复库任何异常均静默回退（解析链不断供）
        return None
    if isinstance(repaired, dict):
        return repaired
    if not isinstance(repaired, str):
        return None
    return _try_loads_object(repaired)


def _brace_candidates(text: str) -> list[str]:
    """扫描顶层平衡花括号候选子串（识别字符串边界与转义），按出现顺序返回。

    正则花括号抢救的扫描实现：值内花括号（``{"k": "含 } 的文本"}``）不误判为结构边界。
    """
    candidates: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    candidates.append(text[start : index + 1])
                    start = -1
    return candidates


def _salvage_braces(text: str) -> dict[str, Any] | None:
    """正则花括号抢救：对每个平衡花括号候选子串逐个试解析，首个合法对象胜出。

    缺 json-repair 依赖时的回退路径（覆盖散文夹 JSON）；json-repair 修复失败时同样兜底。
    """
    for candidate in _brace_candidates(text):
        data = _try_loads_object(candidate)
        if data is not None:
            return data
    return None


def extract_json_payload(raw: str) -> dict[str, Any]:
    """解析回退链（JSON 层）：剥围栏 / 散文 → json.loads → json-repair → 花括号抢救。

    全链失败抛 ``AnalysisParseError``（消息与 ``snippet`` 含 200 字截断片段，
    仿 ``_parse_json`` 惯例）。
    """
    if not raw or not raw.strip():
        raise AnalysisParseError("LLM 返回空内容", raw or "")
    text = strip_code_fence(raw)
    data = _try_loads_object(text)
    if data is not None:
        return data
    repair = _load_json_repair()
    if repair is not None:
        data = _try_repair(text, repair)
        if data is not None:
            return data
    data = _salvage_braces(text)
    if data is not None:
        return data
    raise AnalysisParseError(
        f"LLM 返回非法 JSON，解析回退链全部失败；原始片段: {_snippet(raw)}", raw
    )


# ---------------------------------------------------------------------------
# 校验层：回喂消息构造 + 部分抢救
# ---------------------------------------------------------------------------


def _validation_error_lines(error: ValidationError) -> list[str]:
    """ValidationError 逐条摘要（错误定位 + 消息），至多 ``_FEEDBACK_MAX_ERRORS`` 条。"""
    return [
        f"{'.'.join(str(part) for part in item['loc']) or '<整体>'}: {item['msg']}"
        for item in error.errors()[:_FEEDBACK_MAX_ERRORS]
    ]


def build_feedback_message(error: Exception, raw: str) -> str:
    """构造回喂重试消息：错误摘要（含定位）+ 原输出截断片段（200 字）+ 纠正指令。

    - ``ValidationError``：逐条错误摘要（``loc`` 定位 + ``msg``）；
    - ``AnalysisParseError``：沿用其消息（已含截断片段）；
    - 其他异常：兜底摘要（防御性分支，解析链只产出前两类）。
    """
    fragment = raw[:_SNIPPET_CHARS]
    if isinstance(error, ValidationError):
        detail = "校验错误摘要：\n" + "\n".join(_validation_error_lines(error))
        if error.error_count() > _FEEDBACK_MAX_ERRORS:
            detail += f"\n（其余 {error.error_count() - _FEEDBACK_MAX_ERRORS} 条从略）"
        header = "你上一次的输出未通过结构校验。"
    elif isinstance(error, AnalysisParseError):
        detail = f"解析错误：{error}"
        header = "你上一次的输出不是合法 JSON 对象。"
    else:
        detail = f"处理错误：{error}"
        header = "你上一次的输出无法处理。"
    return (
        f"{header}\n{detail}\n"
        f"原始输出片段（截断至 {_SNIPPET_CHARS} 字）：\n{fragment}\n"
        "请严格只输出一个合法的 JSON 对象，不要任何解释文字、不要 markdown 代码块标记。"
    )


def _try_validate(model_cls: type[BaseModel], data: Any) -> BaseModel | None:
    """试校验，失败返回 None。"""
    try:
        return model_cls.model_validate(data)
    except ValidationError:
        return None


def _salvage_items(
    work: dict[str, Any], output_cls: type[BaseModel], items_annotation: Any
) -> BaseModel | None:
    """条目形态抢救：保留可单独校验的条目；全部非法即失败（空报告无抢救价值）。"""
    args = get_args(items_annotation)
    item_cls = args[0] if args else None
    raw_items = work.get("items")
    if item_cls is None or not isinstance(raw_items, list):
        return None
    valid_items = [
        validated
        for item in raw_items
        if isinstance(item, dict) and (validated := _try_validate(item_cls, item)) is not None
    ]
    if not valid_items:
        return None
    return _try_validate(output_cls, {**work, "items": valid_items})


def _salvage_aggregate(work: dict[str, Any], output_cls: type[BaseModel]) -> BaseModel | None:
    """聚合形态抢救：迭代剔除致错的可选字段 / 未知键后重试；必填字段缺失即失败。"""
    fields = output_cls.model_fields
    required = [name for name, field in fields.items() if field.is_required()]
    if required and not any(name in work for name in required):
        return None
    for _ in range(len(fields) + 1):
        try:
            return output_cls.model_validate(work)
        except ValidationError as exc:
            loc = exc.errors()[0]["loc"]
            top = loc[0] if loc else None
            if (
                isinstance(top, str)
                and top in work
                and top in fields
                and not fields[top].is_required()
            ):
                work = {key: value for key, value in work.items() if key != top}
                continue
            if top is None:
                # 模型级校验失败（loc 为空）：按字段声明顺序逐个试剔可选字段
                for name, field in fields.items():
                    if not field.is_required() and name in work:
                        candidate = {key: value for key, value in work.items() if key != name}
                        validated = _try_validate(output_cls, candidate)
                        if validated is not None:
                            return validated
            return None
    return None


def salvage_partial_report(data: Any, output_cls: type[BaseModel]) -> BaseModel | None:
    """预算耗尽后的部分抢救：尽最大努力校验可校验字段，抢救不出返回 None。

    - 条目形态（模型含 ``items`` 字段）：保留可单独校验的条目，全部非法即失败；
    - 聚合形态：剔除未知键与致错的可选字段后重试校验；必填字段缺失即失败；
    - 非字典输入直接返回 None。

    保守口径：抢救产物仅代表可校验子集，调用方须把报告状态降为 ``partial`` 并留
    降级原因（引擎 / worker 侧，Task 10 / 13）。
    """
    if not isinstance(data, dict):
        return None
    fields = output_cls.model_fields
    work = {key: value for key, value in data.items() if key in fields}
    validated = _try_validate(output_cls, work)
    if validated is not None:
        return validated
    if "items" in fields:
        return _salvage_items(work, output_cls, fields["items"].annotation)
    return _salvage_aggregate(work, output_cls)


# ---------------------------------------------------------------------------
# 回喂重试编排（预算配置化，可降 0）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParseOutcome:
    """解析回退链 + 回喂重试的终局产物。

    - ``status``：ok 全量校验通过 / partial 部分抢救成功 / failed 彻底失败；
    - ``report``：ok / partial 时的报告模型实例（partial 为抢救子集）；
    - ``feedback_messages``：历次回喂消息（引擎按序追加进对话，供审计与调试）；
    - ``attempts``：实际尝试次数（预算内调用 ``produce_raw`` 的次数）；
    - ``error_message``：failed 时可读失败信号（不静默，worker 落 ``Job.error``，Task 13）。
    """

    status: AnalysisStatus
    report: BaseModel | None
    feedback_messages: tuple[str, ...] = ()
    attempts: int = 0
    error_message: str = ""


async def parse_with_retry(
    produce_raw: Callable[[str | None], Awaitable[str]],
    output_cls: type[BaseModel],
    *,
    max_retries: int = DEFAULT_PARSE_RETRIES,
) -> ParseOutcome:
    """回喂重试编排（纯函数）：``produce_raw(feedback)`` 返回 LLM 原文。

    首次调用 ``produce_raw(None)``；此后每次失败把 ``build_feedback_message`` 产物
    作为下一轮入参回喂。``max_retries`` 为重试预算（配置 ``analysis_parse_retries``，
    可降 0 退化单次解析；负数按 0 收敛）。预算耗尽：部分抢救可校验字段 →
    ``status=partial``；抢救不出 → ``status=failed`` + 可读 ``error_message``。

    ``produce_raw`` 自身的异常（网络 / provider 层）不在本函数职责内，引擎（Task 10）
    按 job failed 路径处置。
    """
    budget = max(0, max_retries)
    total_attempts = budget + 1
    feedback: str | None = None
    feedbacks: list[str] = []
    error_message = ""
    last_data: dict[str, Any] | None = None

    for attempt in range(1, total_attempts + 1):
        raw = await produce_raw(feedback)
        try:
            last_data = extract_json_payload(raw)
        except AnalysisParseError as exc:
            error_message = str(exc)
            last_data = None
            if attempt < total_attempts:
                feedback = build_feedback_message(exc, raw)
                feedbacks.append(feedback)
            continue
        try:
            report = output_cls.model_validate(last_data)
        except ValidationError as exc:
            error_message = "；".join(_validation_error_lines(exc))
            if attempt < total_attempts:
                feedback = build_feedback_message(exc, raw)
                feedbacks.append(feedback)
            continue
        return ParseOutcome(
            status=AnalysisStatus.OK,
            report=report,
            feedback_messages=tuple(feedbacks),
            attempts=attempt,
        )

    # 预算耗尽：有可解析数据则部分抢救，否则彻底失败
    salvaged = salvage_partial_report(last_data, output_cls) if last_data is not None else None
    if salvaged is not None:
        return ParseOutcome(
            status=AnalysisStatus.PARTIAL,
            report=salvaged,
            feedback_messages=tuple(feedbacks),
            attempts=total_attempts,
        )
    if not error_message:
        error_message = "解析预算耗尽且无可抢救字段"
    return ParseOutcome(
        status=AnalysisStatus.FAILED,
        report=None,
        feedback_messages=tuple(feedbacks),
        attempts=total_attempts,
        error_message=error_message,
    )
