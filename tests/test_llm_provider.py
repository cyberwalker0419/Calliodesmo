import sys
from types import SimpleNamespace

import pytest

from calliodesmo.interfaces.llm import LLMMessage, ToolCall, ToolSpec
from calliodesmo.providers.litellm_provider import LiteLLMProvider


async def test_litellm_provider_complete(monkeypatch):
    calls: dict = {}

    async def acompletion(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="你好，世界"))],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=acompletion))

    provider = LiteLLMProvider(
        model="openai/gpt-4o-mini", api_key="k", api_base="https://api.example.com"
    )
    resp = await provider.complete(
        [LLMMessage(role="user", content="hi")], temperature=0.1, max_tokens=16
    )

    assert resp.content == "你好，世界"
    assert resp.model == "openai/gpt-4o-mini"
    assert resp.usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert calls["messages"] == [{"role": "user", "content": "hi"}]
    assert calls["temperature"] == 0.1
    assert calls["max_tokens"] == 16
    assert calls["api_key"] == "k"
    assert calls["api_base"] == "https://api.example.com"


async def test_litellm_provider_omits_optional_kwargs(monkeypatch):
    calls: dict = {}

    async def acompletion(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=None,
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=acompletion))

    provider = LiteLLMProvider(model="ollama/qwen2.5")
    resp = await provider.complete([LLMMessage(role="user", content="hi")])

    assert resp.usage == {}
    assert "api_key" not in calls
    assert "api_base" not in calls
    assert "max_tokens" not in calls


# ---- P7 T3：原生工具调用契约 ----


def test_tool_spec_and_tool_call_frozen():
    """ToolSpec / ToolCall frozen 结构（注册表与 provider 共用同一份 JSON Schema）。"""
    from dataclasses import FrozenInstanceError

    spec = ToolSpec(name="t", description="d", parameters={"type": "object"})
    call = ToolCall(id="c1", name="t", arguments={"a": 1})
    with pytest.raises(FrozenInstanceError):
        spec.name = "x"  # frozen
    with pytest.raises(FrozenInstanceError):
        call.arguments = {}  # frozen
    assert spec.parameters == {"type": "object"}
    assert call.arguments == {"a": 1}


async def test_complete_tools_passthrough_openai_schema(monkeypatch):
    """tools 转 OpenAI 格式透传；assistant tool_calls / tool 回写消息形态映射。"""
    calls: dict = {}

    async def acompletion(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(
            model="m",
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=None,
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=acompletion))
    provider = LiteLLMProvider(model="openai/gpt-4o-mini")

    spec = ToolSpec(
        name="search_knowledge",
        description="检索",
        parameters={"type": "object", "properties": {"question": {"type": "string"}}},
    )
    messages = [
        LLMMessage(role="user", content="q"),
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=(ToolCall(id="c1", name="search_knowledge", arguments={"question": "q"}),),
        ),
        LLMMessage(role="tool", content="结果", tool_call_id="c1"),
    ]
    resp = await provider.complete(messages, tools=[spec])

    assert calls["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "search_knowledge",
                "description": "检索",
                "parameters": spec.parameters,
            },
        }
    ]
    sent = calls["messages"]
    assert sent[1]["tool_calls"][0]["function"]["name"] == "search_knowledge"
    assert sent[1]["tool_calls"][0]["id"] == "c1"
    assert sent[2]["role"] == "tool"
    assert sent[2]["tool_call_id"] == "c1"
    assert resp.tool_calls is None  # 纯文本响应路径不变


async def test_complete_no_tools_omits_tools_kwarg(monkeypatch):
    """tools 默认 None：旧调用面零变化（不传 tools kwarg）。"""
    calls: dict = {}

    async def acompletion(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(
            model="m",
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=None,
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=acompletion))
    await LiteLLMProvider(model="m").complete([LLMMessage(role="user", content="hi")])
    assert "tools" not in calls


async def test_complete_parses_response_tool_calls(monkeypatch):
    """响应 tool_calls 解析回 ToolCall；参数 JSON 畸形兜底空 dict。"""

    async def acompletion(**kwargs):
        return SimpleNamespace(
            model="m",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="c1",
                                function=SimpleNamespace(
                                    name="search_knowledge", arguments='{"question": "q"}'
                                ),
                            ),
                            SimpleNamespace(
                                id="c2",
                                function=SimpleNamespace(name="bad_tool", arguments="{not json"),
                            ),
                        ],
                    )
                )
            ],
            usage=None,
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=acompletion))
    resp = await LiteLLMProvider(model="m").complete([LLMMessage(role="user", content="q")])

    assert resp.tool_calls is not None
    assert len(resp.tool_calls) == 2
    assert resp.tool_calls[0] == ToolCall(
        id="c1", name="search_knowledge", arguments={"question": "q"}
    )
    assert resp.tool_calls[1].arguments == {}  # 参数幻觉兜底，注册表 schema 校验拒畸形


async def test_complete_backend_without_tool_support_friendly(monkeypatch):
    """后端不支持 tool calling：响应无 tool_calls -> 纯文本降级，不抛错。"""

    async def acompletion(**kwargs):
        assert "tools" in kwargs
        return SimpleNamespace(
            model="m",
            choices=[SimpleNamespace(message=SimpleNamespace(content="直接回答"))],
            usage=None,
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=acompletion))
    resp = await LiteLLMProvider(model="m").complete(
        [LLMMessage(role="user", content="q")],
        tools=[ToolSpec(name="t", description="d", parameters={})],
    )
    assert resp.content == "直接回答"
    assert resp.tool_calls is None
