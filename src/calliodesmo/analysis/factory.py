"""分析引擎装配工厂：``build_analysis_engine``（P6 Task 10）。

LLM 路由**复用** ``retrieval/factory.build_llm_provider``（单一事实源，不写第二套路由）：

- ``analysis_model`` 空 → 回退 ``llm_model``（配置清单见计划「配置项清单」）；
- ``test/*`` → ``StubLLMProvider``（离线零网络）；
- localhost / ``ollama/`` / ``lm-studio/`` 豁免 API key 校验；
- 缺 key 抛 ``RuntimeError`` 带配置指引（API 层转 503，同 ingest 惯例，Task 14 消费）。

QA 类 ``SearchEngine`` 经入参注入（端点经依赖注入传入，用与请求侧同一份 settings 经
``build_default_search_engine`` 构造）——**不得**在引擎内直调
``api/deps.get_search_engine()``：该调用绕过测试的 dependency override，离线测试会
读到 ``.env`` 真配置（计划架构节「QA 类复用 SearchEngine」锁定）。

已知限制（如实留痕）：QA 检索范围为全可见库，``doc_ids`` 范围限定需检索器谓词下推，
P9 补（2026-W49，与 ``api/deps.py`` ProfileCard/BM25 改 PG 同批）；前端文案明示
（Task 19）。
"""

from __future__ import annotations

from pathlib import Path

from calliodesmo.analysis.engine import DefaultAnalysisEngine
from calliodesmo.config import Settings
from calliodesmo.interfaces.retriever import SearchEngine
from calliodesmo.retrieval.factory import build_llm_provider


def build_analysis_engine(
    settings: Settings,
    *,
    search_engine: SearchEngine | None = None,
    template_dir: str | Path | None = None,
) -> DefaultAnalysisEngine:
    """按配置装配默认分析引擎（请求侧建一次，经依赖注入贯穿 worker 生命周期）。

    参数:
        settings: 与请求侧同一份配置；``analysis_model`` 空回退 ``llm_model``。
        search_engine: QA 类经其 ``.query`` 检索合成（构造注入，见模块注记）。
        template_dir: 模板目录覆盖（默认 ``config/analysis_prompts``）。

    异常:
        RuntimeError: 非本地 / 非豁免模型缺 API key（消息含 ``CALLIODESMO_LLM_API_KEY``
            配置指引；API 层转 503）。
    """
    model = settings.analysis_model or settings.llm_model
    routed = settings.model_copy(update={"llm_model": model})
    llm = build_llm_provider(routed)
    return DefaultAnalysisEngine(
        llm=llm,
        settings=settings,
        search_engine=search_engine,
        template_dir=template_dir,
    )
