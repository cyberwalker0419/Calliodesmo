"""OcrProvider / VisionProvider 接口契约测试（离线：test/* 走桩）。"""

from calliodesmo.interfaces.ocr import OcrProvider, OcrResult
from calliodesmo.interfaces.vision import VisionProvider, VisionResponse
from calliodesmo.providers.stub_ocr import StubOcrProvider
from calliodesmo.providers.stub_vision import StubVisionProvider


async def test_stub_ocr_returns_result():
    """StubOCR：可调用、返回 OcrResult（text/model/metadata）。"""
    ocr = StubOcrProvider()
    res = await ocr.extract_text(b"\x89PNG", mime="image/png", prompt="OCR:")
    assert isinstance(res, OcrResult)
    assert "OCR" in res.text
    assert res.model == "test/stub-ocr"
    assert res.metadata["stub"] is True


async def test_stub_vision_returns_response():
    """StubVision：可调用、返回 VisionResponse（content/model/usage）。"""
    vision = StubVisionProvider()
    resp = await vision.describe("描述一下", b"\x89PNG", mime="image/png")
    assert isinstance(resp, VisionResponse)
    assert "描述一下" in resp.content
    assert resp.usage["total_tokens"] == 0


def test_contract_abstract_methods():
    """契约：两个 ABC 各有一个抽象方法（不可实例化检查由 ABC 保证）。"""
    assert hasattr(OcrProvider, "extract_text")
    assert hasattr(VisionProvider, "describe")
