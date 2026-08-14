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
