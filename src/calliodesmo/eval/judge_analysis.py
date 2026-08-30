"""G-Eval rubric judge：九类分析报告的四维结构化评分（P6 Task 17）。

rubric 四维（各 1–5 整数分，``AnalysisJudgeScores``）：

- ``completeness`` 完整性：报告是否覆盖材料中与任务相关的关键内容；
- ``evidence_support`` 证据支撑：结论是否有材料 / 证据引用支持；
- ``no_fabrication`` 无编造：是否未引入材料之外的信息（幻觉惩罚维度）；
- ``structure`` 结构规范：结构是否符合该类型报告契约与任务要求。

**judge 自身走 Task 7 解析链**（``analysis/parser.parse_with_retry``）：judge 输出
与分析主链同一套「剥围栏 / json-repair / 花括号抢救 + pydantic 校验」；**解析失败
降级「无分」（返回 ``None``）而非崩溃**——judge 是参考分，不因评估侧故障中断回归。

**离线桩固定分**：系统提示首行携带 ``JUDGE_MARKER``（``[ANALYSIS:judge]``），
``StubLLMProvider`` 按分析标记分发固定评分（四维均 3 的中性分，见
``providers/stub_llm.py``）。**桩对生成质量零区分度，离线证据只承诺结构 / 契约**，
不得表述为「分析质量好」；质量证据由 ``scripts/eval_p6.py --real`` 承担
（用户本机，锚点 2026-W45，与 ``scripts/eval_p5.py --real`` 同批）。

留痕：``--real`` 真实模型补跑 → 用户本机，锚点 2026-W45（连同
``scripts/eval_p5.py --real`` 同批），延误顺延 2026-W46（计划「验收口径」）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from calliodesmo.analysis.parser import parse_with_retry
from calliodesmo.analysis.schemas import AnalysisType
from calliodesmo.interfaces.llm import LLMMessage, LLMProvider

__all__ = [
    "JUDGE_DIMENSIONS",
    "JUDGE_MARKER",
    "AnalysisJudgeScores",
    "judge_analysis_report",
]

#: judge 系统提示首行标记：``StubLLMProvider`` 分析标记分发锚点（离线固定分路径）。
#: 真实模型侧为无害标记文本（沿用分析模板首行标记惯例）。
JUDGE_MARKER = "[ANALYSIS:judge]"

#: rubric 四维（取值与 ``AnalysisJudgeScores`` 字段一一对应，聚合口径锚点）
JUDGE_DIMENSIONS = ("completeness", "evidence_support", "no_fabrication", "structure")

#: judge 提示词中材料文本总字符预算（防御性截断；与 ``analysis_max_input_chars``
#: 默认值同量级——judge 为参考分，不配置化，避免 Settings 面扩张）
_JUDGE_MAX_MATERIAL_CHARS = 24000

#: rubric 说明（user 段）：四维语义与 1–5 分锚点
_RUBRIC_TEXT = """请按以下四个维度为分析报告打分，每个维度取 1–5 的整数（1=最差，5=最佳）：
1. completeness（完整性）：报告是否覆盖了材料中与任务相关的关键内容。
2. evidence_support（证据支撑）：报告结论是否有材料 / 证据引用支持。
3. no_fabrication（无编造）：报告是否未引入材料之外的信息（编造 / 幻觉应扣分）。
4. structure（结构规范）：报告结构是否符合该类型报告的契约与任务要求。
严格只输出一个 JSON 对象，不要任何解释文字、不要 markdown 代码块标记。输出 JSON 结构：
{"completeness": <1-5>, "evidence_support": <1-5>, "no_fabrication": <1-5>, "structure": <1-5>}"""


class AnalysisJudgeScores(BaseModel):
    """G-Eval rubric 四维结构化评分（各维 1–5 整数；extra 键拒绝）。

    ``overall`` 为四维均值（保留调用方自行 round 的口径；聚合见
    ``eval/harness.AnalysisEvalHarness``）。四维均必填——部分维度缺失即整体
    不可比，解析链的部分抢救对本模型不生效（无可选字段），降级「无分」。
    """

    model_config = ConfigDict(extra="forbid")

    completeness: int = Field(ge=1, le=5, description="完整性：材料关键内容覆盖度")
    evidence_support: int = Field(ge=1, le=5, description="证据支撑：结论的证据支持程度")
    no_fabrication: int = Field(ge=1, le=5, description="无编造：未引入材料外信息的程度")
    structure: int = Field(ge=1, le=5, description="结构规范：报告契约符合度")

    @property
    def overall(self) -> float:
        """四维均值（1–5 连续值；聚合均值口径见 harness）。"""
        return sum(getattr(self, dim) for dim in JUDGE_DIMENSIONS) / len(JUDGE_DIMENSIONS)


def _truncate_materials(material_texts: Sequence[str]) -> str:
    """材料文本拼装（逐条编号 + 总字符预算截断；预算见 ``_JUDGE_MAX_MATERIAL_CHARS``）。"""
    joined = "\n".join(f"[材料 {index + 1}] {text}" for index, text in enumerate(material_texts))
    if len(joined) > _JUDGE_MAX_MATERIAL_CHARS:
        joined = joined[:_JUDGE_MAX_MATERIAL_CHARS] + "\n（材料超长，已截断）"
    return joined or "（无材料文本）"


async def judge_analysis_report(
    judge: LLMProvider,
    *,
    task_type: AnalysisType | str,
    payload: Mapping[str, Any],
    material_texts: Sequence[str] = (),
    question: str = "",
) -> AnalysisJudgeScores | None:
    """对一份分析报告做 rubric 四维评分；解析失败降级 ``None``（无分）而非崩溃。

    参数:
        judge: 评分用 LLM（离线为 ``StubLLMProvider`` 固定分；``--real`` 为真实模型）。
        task_type: 被评报告的分析类型（rubric 上下文）。
        payload: 被评报告的负载（对应报告模型的 ``model_dump()``；failed 报告为空字典）。
        material_texts: 源材料文本（证据支撑 / 无编造两维的判定依据）。
        question: QA 类问题（其余类型留空）。

    返回:
        ``AnalysisJudgeScores``；judge 输出经 Task 7 解析链（``parse_with_retry``，
        单次尝试不回喂——评估侧不消耗重试预算）仍不可校验时返回 ``None``。

    异常:
        judge 传输层异常（网络 / provider 故障）不在本函数内吞掉，向上传播由
        调用方处置（与引擎同口径，见 ``analysis/engine.py`` 模块注记）。
    """
    t = AnalysisType(task_type)
    report_text = json.dumps({"task_type": t.value, "payload": dict(payload)}, ensure_ascii=False)
    user_parts = [
        _RUBRIC_TEXT,
        f"待评估的分析类型：{t.value}",
        f"待评估的分析报告（JSON）：\n{report_text}",
        f"分析所依据的材料：\n{_truncate_materials(material_texts)}",
    ]
    if question.strip():
        user_parts.append(f"用户问题（QA 类）：{question.strip()}")
    messages = [
        LLMMessage(
            role="system",
            content=f"{JUDGE_MARKER}\n你是情报分析报告质量评估器（G-Eval rubric judge）。",
        ),
        LLMMessage(role="user", content="\n\n".join(user_parts)),
    ]

    async def produce_raw(_feedback: str | None) -> str:
        resp = await judge.complete(messages, temperature=0.0)
        return resp.content

    # judge 单次尝试（预算 0）：评估侧不消耗回喂重试；解析 / 校验失败 → failed → 无分
    outcome = await parse_with_retry(produce_raw, AnalysisJudgeScores, max_retries=0)
    if outcome.report is None:
        return None
    return outcome.report  # type: ignore[return-value]
