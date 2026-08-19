"""LiteLLMVisionProvider：image_url data URI 构造与多模态 content part 列表（sys.modules 桩）。"""

import sys
from types import SimpleNamespace

from calliodesmo.providers.litellm_vision import LiteLLMVisionProvider, _data_uri


async def test_litellm_vision_describe_builds_multimodal_content(monkeypatch):
    """桩 litellm 断言：content 含 text part + image_url part（base64 data URI）。"""
    calls: dict = {}

    async def acompletion(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(
            model=kwargs["model"],
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="图里有一份合同，包含甲乙方名称"))
            ],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20),
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=acompletion))

    provider = LiteLLMVisionProvider(model="ollama/qwen3-vl:8b")
    pic = b"\x89PNG fake-image-bytes"
    resp = await provider.describe("描述这张图", pic, mime="image/png")

    assert resp.content == "图里有一份合同，包含甲乙方名称"
    assert resp.content == "图里有一份合同，包含甲乙方名称"
    # _short_model：含 ':' 的模型串（ollama/qwen3-vl:8b）取 basename，与 LLM provider 一致
    assert resp.model == "qwen3-vl:8b"
    assert resp.usage == {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}

    # content part 列表：text + image_url(base64 data URI)
    content = calls["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "描述这张图"}
    assert content[1]["type"] == "image_url"
    url = content[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert url == _data_uri(pic, "image/png")
    assert calls["model"] == "ollama/qwen3-vl:8b"


async def test_data_uri_encoding():
    """_data_uri：字节 -> mime + base64 前缀。"""
    uri = _data_uri(b"hello", "image/jpeg")
    assert uri == "data:image/jpeg;base64,aGVsbG8="
