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


# ---- P7 T4：[AGENT:*] 脚本化工具序列 ----


def _agent_msgs(system: str, history=None) -> list:
    msgs = [LLMMessage(role="system", content=system), LLMMessage(role="user", content="问题")]
    if history:
        msgs.extend(history)
    return msgs


async def test_stub_agent_two_step_search():
    """两步检索脚本：首回合发 search_knowledge，喂回工具结果后次回合收尾。"""
    from calliodesmo.interfaces.llm import ToolCall

    llm = StubLLMProvider()
    system = "你是情报分析助手。[AGENT:two_step_search]"

    first = await llm.complete(_agent_msgs(system))
    assert first.tool_calls is not None and len(first.tool_calls) == 1
    call = first.tool_calls[0]
    assert call.name == "search_knowledge"
    assert call.arguments["mode"] == "native_rag"

    # 喂回工具结果（assistant tool_calls + tool 回写）-> 次回合收尾直答
    second = await llm.complete(
        _agent_msgs(
            system,
            history=[
                LLMMessage(role="assistant", content="", tool_calls=(call,)),
                LLMMessage(role="tool", content="OpenAI 开发了 GPT-4。", tool_call_id=call.id),
            ],
        )
    )
    assert second.tool_calls is None
    assert "OpenAI" in second.content
    assert isinstance(call, ToolCall)


async def test_stub_agent_forbidden_probe():
    """越权探测脚本：脚本化调用未授权工具（注册表将拒派，见 T5）。"""
    llm = StubLLMProvider()
    resp = await llm.complete(_agent_msgs("[AGENT:forbidden_probe]"))
    assert resp.tool_calls is not None
    assert resp.tool_calls[0].name == "run_analysis"


async def test_stub_agent_insufficient_direct():
    """证据不足直答脚本：零工具调用，直接收尾。"""
    llm = StubLLMProvider()
    resp = await llm.complete(_agent_msgs("[AGENT:insufficient_direct]"))
    assert resp.tool_calls is None
    assert "证据不足" in resp.content


async def test_stub_agent_unknown_marker_raises():
    """未知 agent 标记显式 ValueError，不静默回退（同分析标记口径）。"""
    import pytest

    llm = StubLLMProvider()
    with pytest.raises(ValueError, match="AGENT:nope"):
        await llm.complete(_agent_msgs("[AGENT:nope]"))


async def test_stub_agent_step_order_stateless():
    """步序按 messages 已有 assistant tool_calls 轮数判定（纯函数无状态）。"""
    from calliodesmo.interfaces.llm import ToolCall

    llm = StubLLMProvider()
    system = "[AGENT:two_step_search]"
    first = await llm.complete(_agent_msgs(system))
    # 相同输入重现相同输出（无内部状态）
    again = await llm.complete(_agent_msgs(system))
    assert again.tool_calls == first.tool_calls
    # 伪造已完成一轮 -> 直接收尾
    done = await llm.complete(
        _agent_msgs(
            system,
            history=[
                LLMMessage(
                    role="assistant",
                    content="",
                    tool_calls=(ToolCall(id="x", name="search_knowledge", arguments={}),),
                ),
                LLMMessage(role="tool", content="r", tool_call_id="x"),
            ],
        )
    )
    assert done.tool_calls is None
