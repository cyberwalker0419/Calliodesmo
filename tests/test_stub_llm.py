"""离线桩 LLM 契约测试：test/* 模型路由到 StubLLMProvider，零网络。"""

import json

from calliodesmo.interfaces.llm import LLMMessage
from calliodesmo.providers.stub_llm import StubLLMProvider


async def test_stub_extract_response_shape():
    """抽取类 system prompt -> 返回含 entities/relations/claims/covariates 的 JSON。"""
    llm = StubLLMProvider()
    msgs = [
        LLMMessage(role="system", content="你是知识图谱抽取引擎。"),
        LLMMessage(role="user", content="抽取这些文本"),
    ]
    resp = await llm.complete(msgs)
    data = json.loads(resp.content)
    assert set(data) >= {"entities", "relations", "claims", "covariates"}
    assert all("name" in e and "type" in e for e in data["entities"])
    assert resp.model == "test/stub"
    assert "total_tokens" in resp.usage


async def test_stub_summary_response_shape():
    """摘要类 system prompt -> 返回 {title, summary} JSON。"""
    llm = StubLLMProvider()
    msgs = [
        LLMMessage(role="system", content="你是文档摘要引擎。"),
        LLMMessage(role="user", content="文档 X 的实体：..."),
    ]
    resp = await llm.complete(msgs)
    data = json.loads(resp.content)
    assert set(data) == {"title", "summary"}


async def test_stub_unknown_prompt_falls_back_to_extraction():
    """未知调用回退为抽取格式，避免管线中断。"""
    llm = StubLLMProvider()
    msgs = [LLMMessage(role="system", content="随机任务"), LLMMessage(role="user", content="?")]
    resp = await llm.complete(msgs)
    data = json.loads(resp.content)
    assert "entities" in data  # 回退为抽取
