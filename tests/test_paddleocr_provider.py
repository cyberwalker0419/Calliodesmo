"""PaddleOcrProvider：懒加载 + 缺依赖友好报错 + save_to_json 解析（sys.modules 桩）。"""

import sys
from types import SimpleNamespace

import pytest

from calliodesmo.providers.paddleocr_provider import (
    PaddleOcrProvider,
    _extract_text_from_result,
)


class _FakePaddle:  # fake `paddleocr` 模块（PaddleOCRVL）
    def __init__(self, res):
        self._res = res

    def predict(self, path):
        return [self._res]


class _FakePipeline:
    def __init__(self, res, **kwargs):
        self.kwargs = kwargs
        self._res = res

    def predict(self, path):
        return [self._res]


def _stub_module(monkeypatch, res):
    module = SimpleNamespace(
        PaddleOCRVL=lambda **kw: _FakePipeline(res, **kw),
    )
    monkeypatch.setitem(sys.modules, "paddleocr", module)
    return module


def _result_with(text):
    """伪造一份 PaddleOCR-VL predict 结果（save_to_json 返回 dict）。"""
    return SimpleNamespace(
        save_to_json=lambda: {"rec_texts": [text, "第二行"]},
    )


def _result_without_json():
    return SimpleNamespace(save_to_json=lambda: {"text": "单文本回退"})


async def test_paddleocr_local_extract_text(monkeypatch):
    """本地模式：predict -> save_to_json rec_texts 拼多行。"""
    _stub_module(monkeypatch, _result_with("第一行"))
    provider = PaddleOcrProvider(
        pipeline_version="v1.6", vl_backend="llama-cpp-server", model="PaddleOCR-VL-1.6"
    )
    res = await provider.extract_text(b"\x89PNG fake", mime="image/png")
    assert res.text == "第一行\n第二行"
    assert res.model == "PaddleOCR-VL-1.6"
    assert res.metadata == {"remote": False}


def test_paddleocr_missing_dependency_raises_friendly(monkeypatch):
    """缺 paddleocr 依赖 -> RuntimeError 引导安装 extra。"""
    monkeypatch.setitem(sys.modules, "paddleocr", None)
    provider = PaddleOcrProvider()
    with pytest.raises(RuntimeError, match="documents-ocr"):
        provider._get_pipeline()


def test_extract_text_from_result_rec_texts():
    """结果解析：rec_texts 优先，text 回退。"""
    assert _extract_text_from_result(_result_with("A")) == "A\n第二行"
    assert _extract_text_from_result(_result_without_json()) == "单文本回退"


_REMOTE_RESPONSE = {
    "model": "paddle-ocr-vl-1.6",
    "results": [
        {
            "markdown": {"markdown_texts": "Calliodesmo OCR Test 2026\n\n三层知识图谱"},
            "json": {
                "res": {
                    "parsing_res_list": [
                        {"block_label": "text", "block_content": "Calliodesmo OCR Test 2026"},
                        {"block_label": "text", "block_content": "三层知识图谱"},
                    ]
                }
            },
        }
    ],
}


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _RecordingClient:
    """记录请求的 url/json，返回固定响应；模拟 httpx.AsyncClient 上下文。"""

    last: dict | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        _RecordingClient.last = {"url": url, **kwargs}
        return _FakeResponse(_REMOTE_RESPONSE)


async def test_paddleocr_remote_uses_v1_ocr_endpoint(monkeypatch):
    """remote 模式：POST {base}/v1/ocr，JSON body 为裸 base64 image（非 multipart）。"""
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _RecordingClient)
    provider = PaddleOcrProvider(
        server_url="http://example.test:8084", remote=True, model="PaddleOCR-VL-1.6"
    )
    res = await provider.extract_text(b"\x89PNG fake", mime="image/png")

    recorded = _RecordingClient.last
    assert recorded["url"] == "http://example.test:8084/v1/ocr"
    body = recorded["json"]
    assert set(body.keys()) == {"image"}
    # 裸 base64（无 data: 前缀），且可解回原字节
    assert not body["image"].startswith("data:")
    assert __import__("base64").b64decode(body["image"]) == b"\x89PNG fake"
    # markdown_texts 优先；有 markdown 时不重复拼 parsing_res_list
    assert res.text == "Calliodesmo OCR Test 2026\n\n三层知识图谱"
    assert res.metadata == {"remote": True}


async def test_paddleocr_remote_missing_url_raises():
    """remote 模式缺 server_url -> RuntimeError 引导配置。"""
    provider = PaddleOcrProvider(remote=True)
    with pytest.raises(RuntimeError, match="CALLIODESMO_OCR_SERVER_URL"):
        await provider.extract_text(b"x", mime="image/png")
