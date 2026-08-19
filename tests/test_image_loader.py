"""ImageLoader：OCR/识图双 provider 加载合成 PNG，注册后缀可分发。"""

import hashlib

import pytest

from calliodesmo.providers.image_loader import ImageLoader
from calliodesmo.providers.registry import default_registry
from calliodesmo.providers.stub_ocr import StubOcrProvider
from calliodesmo.providers.stub_vision import StubVisionProvider

# 1x1 透明 PNG（合法最小 PNG）
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000100ffffff8455a17c0000000049454e44ae426082"
)


async def test_image_loader_uses_ocr_by_default(tmp_path):
    """有 OCR provider：OCR 转录文本进 LoadedDocument.content，metadata 记 ocr:true。"""
    f = tmp_path / "scan.png"
    f.write_bytes(PNG_BYTES)
    loader = ImageLoader(ocr=StubOcrProvider(), vision=StubVisionProvider())
    docs = await loader.load(f)
    assert len(docs) == 1
    assert "OCR" in docs[0].content
    assert docs[0].metadata["ocr"] is True
    assert docs[0].metadata["suffix"] == ".png"
    assert docs[0].metadata["mime"] == "image/png"
    # content_hash 按 OCR 文本计算（增量索引可用）
    assert docs[0].content_hash == hashlib.sha256(docs[0].content.encode()).hexdigest()


async def test_image_loader_falls_back_to_vision(tmp_path):
    """无 OCR、有识图：降级用识图描述作 content（ocr:false）。"""
    f = tmp_path / "photo.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0 fake jpeg")
    loader = ImageLoader(vision=StubVisionProvider())
    docs = await loader.load(f)
    assert len(docs) == 1
    assert "占位" in docs[0].content
    assert docs[0].metadata["ocr"] is False
    assert docs[0].metadata["mime"] == "image/jpeg"


async def test_image_loader_requires_provider(tmp_path):
    """无 provider -> 友好 ValueError。"""
    f = tmp_path / "a.png"
    f.write_bytes(PNG_BYTES)
    loader = ImageLoader()
    with pytest.raises(ValueError, match=r"OCR_PROVIDER|VISION_MODEL"):
        await loader.load(f)


async def test_registry_registers_image_suffixes_with_providers(tmp_path):
    """default_registry(ocr=..., vision=...) 注册图片后缀，可分发加载。"""
    f = tmp_path / "doc.png"
    f.write_bytes(PNG_BYTES)
    reg = default_registry(ocr=StubOcrProvider(), vision=StubVisionProvider())
    assert {".png", ".jpg", ".webp", ".tiff"} <= reg.registered_suffixes
    docs = await reg.load(f)
    assert len(docs) == 1
    assert "OCR" in docs[0].content


async def test_registry_no_provider_skips_images(tmp_path):
    """无 provider：不注册图片后缀（离线兼容，resolve 给未注册提示）。"""
    reg = default_registry()
    assert ".png" not in reg.registered_suffixes
    f = tmp_path / "doc.png"
    f.write_bytes(PNG_BYTES)
    with pytest.raises(ValueError, match="未注册的文件类型"):
        reg.resolve(f)
