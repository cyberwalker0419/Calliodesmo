"""图片 Loader：经 OCR 专职（PaddleOCR-VL）或识图专职（qwen3-vl）把图片文档转为文本。

双 provider 顺序：
- 有 ``OcrProvider`` -> OCR 逐字转录（喂抽取 + 嵌入索引，首选）
- 无 OCR、有 ``VisionProvider`` -> 识图语义描述（降级）
- 两者皆无 -> 抛友好错误（未启用 OCR/识图时该后缀未注册，注册表不会路由到此）

模型调用为 async，故 async ``load`` 只做编排；阻塞式文件 I/O 下沉到同步
``_read_image_bytes``（避免 ASYNC240）。``content_hash`` 按最终文本 sha256 计算，
增量索引可用。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from calliodesmo.interfaces.document_loader import DocumentLoader, LoadedDocument
from calliodesmo.interfaces.ocr import OcrProvider
from calliodesmo.interfaces.vision import VisionProvider

# mime 推断（默认为 image/png）：与 image_loader 后缀注册表对应
_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".gif": "image/gif",
}

# 识图降级时的默认描述提示词（与 config 的 vision_prompt 对齐）
_DEFAULT_VISION_PROMPT = "请描述这张图片的内容：其中的实体、关系、场景、图表信息等。"


class ImageLoader(DocumentLoader):
    """图片文档加载器：OCR 或识图模型把图片转文本。"""

    suffixes = (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp")

    def __init__(
        self,
        ocr: OcrProvider | None = None,
        vision: VisionProvider | None = None,
        vision_prompt: str | None = None,
    ) -> None:
        self._ocr = ocr
        self._vision = vision
        self._vision_prompt = vision_prompt or _DEFAULT_VISION_PROMPT

    @staticmethod
    def _mime(path: Path) -> str:
        return _MIME_BY_SUFFIX.get(path.suffix.lower(), "image/png")

    async def load(self, source: str | Path) -> list[LoadedDocument]:
        path = Path(source)
        image_bytes = self._read_image_bytes(path)
        mime = self._mime(path)

        if self._ocr is not None:
            result = await self._ocr.extract_text(image_bytes, mime=mime)
            text, ocr_model, ocr_flag = result.text, result.model, True
        elif self._vision is not None:
            resp = await self._vision.describe(self._vision_prompt, image_bytes, mime=mime)
            text, ocr_model, ocr_flag = resp.content, resp.model, False
        else:
            raise ValueError(
                "图片解析需启用 OCR 或识图模型：设 CALLIODESMO_OCR_PROVIDER=paddleocr"
                " 或配置 CALLIODESMO_VISION_MODEL（缺依赖时 uv sync --extra documents-ocr）"
            )

        suffix = path.suffix.lower()
        size_bytes = len(image_bytes)
        return [
            LoadedDocument(
                doc_id=path.name,
                content=text,
                metadata={
                    "source_path": str(path),
                    "suffix": suffix,
                    "size_bytes": size_bytes,
                    "mime": mime,
                    "ocr": ocr_flag,
                    "ocr_model": ocr_model,
                    "vision_model": "" if ocr_flag else ocr_model,
                },
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        ]

    @staticmethod
    def _read_image_bytes(path: Path) -> bytes:
        """同步文件 I/O 下沉（与 SingleFileLoader._load_sync 同约定，阻塞式读不落 async 体）。"""
        if not path.exists():
            raise FileNotFoundError(f"文档源不存在: {path}")
        return path.read_bytes()
