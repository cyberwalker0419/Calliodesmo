"""DefaultAnalysisEngine：prompt → LLM → 解析 → 回喂重试 → 证据自验 → 信封（P6 Task 10）。

第一批 5 类离线端到端的执行体（第二批 3 类接线留 Task 21，custom 留 Task 22）：

- **模板驱动类型**（摘要 / 关键信息 / 时间线 / 实体识别，第二批 + 关系映射 / 任务 /
  概念）：``get_spec`` 取注册表 → ``load_template`` / ``render_prompt`` 渲染
  （预算双闸经 settings 传入）→ ``parse_with_retry`` 包真实 ``LLMProvider.complete``
  （回喂消息作为追加 user 消息）→ ``verify_evidence`` 证据自验 → ``AnalysisReport``。
- **问答类型**（QA）：经**构造注入的** ``SearchEngine`` 调 ``.query``（NATIVE_RAG 模式）
  得 ``Answer``，包装为 ``QAReport``——来源标注沿用 ``answer_synthesizer`` 的
  ``[chunk_id]`` 强制引注约定，空候选输出「无可引用证据」。**不得**在引擎内直调
  ``api/deps.get_search_engine()``（该调用绕过测试的 dependency override，离线测试会
  读到 ``.env`` 真配置），注入链见 ``analysis/factory.py`` 模块注记。

口径留痕：

- QA 的 ``prompt_version`` 固定 ``QA_PROMPT_VERSION = "qa.v1"``：QA 经检索合成链路、
  不渲染分析模板，版本号与 ``config/analysis_prompts/qa.txt`` 对齐供评估按版本切片；
  模板直连 QA 路径是否复用随 QA ``doc_ids`` 范围（谓词下推，P9，2026-W49）一并重评。
- QA 报告 ``evidence`` 恒空（``citations`` 仅材料块 ID 列表；引文级证据需源文映射，
  随谓词下推补，P9，2026-W49），故 QA 路径跳过 ``verify_evidence``（空证据下为无操作）。
- 实体 / 关系类的图谱上下文由 ``gather_materials`` 采集（Task 9），worker（Task 13，
  2026-W40）折入材料后进引擎；引擎自身不读 ``graph_store``——保引擎纯逻辑可测。
- LLM 传输层异常（网络 / provider 故障）不在引擎内吞掉，向上传播由调用方
  （worker，Task 13）按 job failed 处置；解析预算耗尽则返回 ``status=failed`` 的
  ``AnalysisReport``，warnings 携带可读失败信号。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from calliodesmo.analysis.evidence import verify_evidence
from calliodesmo.analysis.parser import parse_with_retry
from calliodesmo.analysis.prompts import load_template, render_prompt
from calliodesmo.analysis.schemas import (
    AnalysisEnvelope,
    AnalysisStatus,
    AnalysisType,
    QAReport,
)
from calliodesmo.analysis.specs import get_spec
from calliodesmo.auth.context import AccessContext
from calliodesmo.config import Settings
from calliodesmo.interfaces.analysis import (
    AnalysisEngine,
    AnalysisMaterial,
    AnalysisReport,
    AnalysisSpec,
)
from calliodesmo.interfaces.llm import LLMMessage, LLMProvider, LLMResponse
from calliodesmo.interfaces.retriever import SearchEngine, SearchMode

#: QA 类提示词版本：QA 经 SearchEngine 合成、不渲染分析模板，版本号与
#: ``config/analysis_prompts/qa.txt`` 对齐，评估按此切片（口径留痕见模块 docstring）。
QA_PROMPT_VERSION = "qa.v1"


def _sum_usage(responses: Sequence[LLMResponse]) -> dict[str, int]:
    """token 用量跨回喂重试累计（按键求和，保键序稳定：按首次出现顺序）。"""
    total: dict[str, int] = {}
    for resp in responses:
        for key, value in (resp.usage or {}).items():
            total[key] = total.get(key, 0) + int(value)
    return total


def _last_model(responses: Sequence[LLMResponse], fallback: str) -> str:
    """模型名：取末次响应回显，空则回退配置名（本地服务回显可能为空串）。"""
    for resp in reversed(responses):
        if resp.model:
            return resp.model
    return fallback


class DefaultAnalysisEngine(AnalysisEngine):
    """默认分析引擎：注册表驱动模板渲染 + 解析回喂重试 + 证据自验。

    构造注入（全部依赖显式传入，离线可测）：

    - ``llm``：分析用 LLM provider（``build_analysis_engine`` 经
      ``retrieval/factory.build_llm_provider`` 路由构造）；
    - ``settings``：预算与温度配置（``analysis_max_chunks`` / ``analysis_max_input_chars``
      / ``analysis_parse_retries`` / ``analysis_temperature``）与模型名回退；
    - ``search_engine``：QA 类专用（缺省时提交 QA 抛 ``RuntimeError`` 可读）；
    - ``template_dir``：模板目录覆盖（默认 ``config/analysis_prompts``，测试可注临时目录）。
    """

    def __init__(
        self,
        *,
        llm: LLMProvider,
        settings: Settings,
        search_engine: SearchEngine | None = None,
        template_dir: str | Path | None = None,
    ) -> None:
        self._llm = llm
        self._settings = settings
        self._search_engine = search_engine
        self._template_dir = template_dir

    async def run(
        self,
        spec: AnalysisSpec,
        materials: Sequence[AnalysisMaterial],
        access: AccessContext,
    ) -> AnalysisReport:
        """执行一次分析（分派见模块 docstring；材料必须已经 ``visible_to`` 过滤）。"""
        task_type = AnalysisType(spec.task_type)
        if task_type is AnalysisType.QA:
            return await self._run_qa(spec, access)
        return await self._run_template(task_type, spec, materials)

    # ------------------------------------------------------------------
    # 模板驱动路径（第一批 4 类 + 第二批 3 类注册后自动生效）
    # ------------------------------------------------------------------

    async def _run_template(
        self,
        task_type: AnalysisType,
        spec: AnalysisSpec,
        materials: Sequence[AnalysisMaterial],
    ) -> AnalysisReport:
        task_spec = get_spec(task_type)
        template = load_template(task_spec.template_name, template_dir=self._template_dir)
        rendered = render_prompt(
            template,
            task_type,
            materials=materials,
            question=spec.question,
            schema=spec.custom_schema,
            max_chunks=self._settings.analysis_max_chunks,
            max_input_chars=self._settings.analysis_max_input_chars,
        )
        llm = self._resolve_llm(spec.model_override)
        base_messages = [
            LLMMessage(role="system", content=rendered.system),
            LLMMessage(role="user", content=rendered.user),
        ]
        responses: list[LLMResponse] = []

        async def produce_raw(feedback: str | None) -> str:
            """单次补全：回喂消息作为追加 user 消息（与首轮 system / user 隔离）。"""
            messages = list(base_messages)
            if feedback is not None:
                messages.append(LLMMessage(role="user", content=feedback))
            resp = await llm.complete(messages, temperature=self._settings.analysis_temperature)
            responses.append(resp)
            return resp.content

        max_retries = (
            task_spec.max_retries
            if task_spec.max_retries is not None
            else self._settings.analysis_parse_retries
        )
        outcome = await parse_with_retry(produce_raw, task_spec.output_cls, max_retries=max_retries)

        fallback_model = self._settings.analysis_model or self._settings.llm_model
        model = _last_model(responses, fallback_model)
        usage = _sum_usage(responses)
        source_chunk_ids = list(rendered.included_chunk_ids)

        if outcome.status is AnalysisStatus.FAILED:
            # 完全失败：不落报告行（仅 ok / partial 落，见计划「报告落库口径」），
            # 但引擎仍返回可读失败信号，worker（Task 13）据此落 Job.error 与审计
            return AnalysisReport(
                task_type=task_type,
                status=AnalysisStatus.FAILED.value,
                payload={},
                model=model,
                prompt_version=rendered.prompt_version,
                usage=usage,
                warnings=[f"分析失败：{outcome.error_message or '解析预算耗尽且无可抢救字段'}"],
                source_chunk_ids=source_chunk_ids,
            )

        warnings: list[str] = []
        if outcome.status is AnalysisStatus.PARTIAL:
            warnings.append(f"报告为部分抢救（解析校验未全量通过）：{outcome.error_message}")

        envelope = AnalysisEnvelope(
            task_type=task_type,
            status=outcome.status,
            generated_at=datetime.now(UTC),  # 占位装配；worker 落库时以真实时刻重建（信封装配）
            model=model,
            prompt_version=rendered.prompt_version,
            usage=usage,
            warnings=warnings,
            source_chunk_ids=source_chunk_ids,
            payload=outcome.report.model_dump(),
        )
        # 证据自验（轻量：quote 去空白子串匹配）；源文映射取引擎实际消费的材料文本
        verified = verify_evidence(envelope, {m.chunk_id: m.text for m in materials})
        return AnalysisReport(
            task_type=task_type,
            status=verified.status.value,
            payload=verified.payload,
            model=model,
            prompt_version=rendered.prompt_version,
            usage=usage,
            warnings=verified.warnings,
            source_chunk_ids=source_chunk_ids,
        )

    def _resolve_llm(self, model_override: str | None) -> LLMProvider:
        """本次运行的 provider：无 override 用装配好的；有则经同一路由规则临时构造。"""
        if not model_override:
            return self._llm
        from calliodesmo.retrieval.factory import build_llm_provider

        routed = self._settings.model_copy(update={"llm_model": model_override})
        return build_llm_provider(routed)

    # ------------------------------------------------------------------
    # QA 路径：构造注入的 SearchEngine（注入链见模块 docstring 与 factory 注记）
    # ------------------------------------------------------------------

    async def _run_qa(self, spec: AnalysisSpec, access: AccessContext) -> AnalysisReport:
        if self._search_engine is None:
            raise RuntimeError(
                "QA 分析需要经构造注入的 SearchEngine："
                "build_analysis_engine(settings, search_engine=...)（不得直调 api/deps）"
            )
        question = spec.question.strip()
        if not question:
            raise ValueError("QA 分析问题不得为空（question 必填）")

        answer = await self._search_engine.query(
            question, mode=SearchMode.NATIVE_RAG, top_k=spec.top_k, access=access
        )
        report = QAReport(
            question=question,
            answer=answer.text,
            citations=list(answer.source_chunk_ids),
        )
        fallback_model = self._settings.analysis_model or self._settings.llm_model
        model = answer.model or fallback_model
        # QA evidence 恒空（口径留痕见模块 docstring）：verify_evidence 无操作，跳过
        return AnalysisReport(
            task_type=AnalysisType.QA,
            status=AnalysisStatus.OK.value,
            payload=report.model_dump(),
            model=model,
            prompt_version=QA_PROMPT_VERSION,
            usage=dict(answer.usage or {}),
            source_chunk_ids=list(answer.source_chunk_ids),
        )
