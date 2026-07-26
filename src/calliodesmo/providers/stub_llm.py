"""离线桩 LLMProvider：``test/*`` 模型路由到此处，零网络、零依赖。

用途：
- CLI 离线演示 / 冒烟测试 —— ``CALLIODESMO_LLM_MODEL=test/stub calliodesmo ingest ...``
- 让 P1 完整管线（Load->Extract->Cognify->Load->社区派生->档案卡）无需任何真实 LLM 即可跑通

实现：依据 system prompt 关键词区分两种调用：
- 抽取（``知识图谱抽取引擎``）-> 返回固定 entities/relations/claims/covariates JSON
- 摘要（``文档摘要引擎``）-> 返回固定 {title, summary} JSON

返回的实体集合是**与输入无关**的示例数据（OpenAI/GPT-4），仅用于验证管线联通，
不代表真实抽取质量。真实抽取请切换到 openai/deepseek/ollama 等后端。
"""

from __future__ import annotations

import json

from calliodesmo.interfaces.llm import LLMMessage, LLMProvider, LLMResponse

# 抽取示例：固定实体/关系（演示用，与输入文本无关）
_EXTRACTION = {
    "entities": [
        {"name": "OpenAI", "type": "organization", "description": "AI 研究与部署公司"},
        {"name": "GPT-4", "type": "model", "description": "大规模语言模型"},
    ],
    "relations": [
        {
            "source": "OpenAI",
            "target": "GPT-4",
            "type": "developed",
            "description": "OpenAI 开发了 GPT-4",
        },
    ],
    "claims": [
        {"text": "GPT-4 由 OpenAI 开发", "entity_name": "GPT-4"},
    ],
    "covariates": [],
}

_SUMMARY = {"title": "示例文档社区", "summary": "由离线桩 LLM 生成的占位摘要（演示管线联通）。"}


class StubLLMProvider(LLMProvider):
    """离线桩 LLM：按 system prompt 关键词分发抽取/摘要两类固定响应。"""

    def __init__(self, model: str = "test/stub") -> None:
        self.model = model

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        system = next((m.content for m in messages if m.role == "system"), "")
        if "知识图谱抽取引擎" in system or ("抽取" in system and "entities" in system):
            payload = _EXTRACTION
        elif "文档摘要引擎" in system or "摘要" in system:
            payload = _SUMMARY
        else:
            # 未知调用：回退为抽取格式，避免管线中断
            payload = _EXTRACTION
        return LLMResponse(
            content=json.dumps(payload, ensure_ascii=False),
            model=self.model,
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
