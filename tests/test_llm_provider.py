import sys
from types import SimpleNamespace

from calliodesmo.interfaces.llm import LLMMessage
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
