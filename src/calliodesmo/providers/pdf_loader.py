"""PDF 加载器（extra: documents-pdf）：按页切分 LoadedDocument。

默认仅支持文本型 PDF（pypdf ``extract_text``）；当传入 ``OcrProvider`` 且开启
``prefer_ocr`` 时，对文本提取为空的页（缩放件/扫描件）渲染成图并经 OCR 转录
（需本机装 ``pymupdf`` 渲染 + OCR extra ``documents-ocr``；缺依赖友好报错）。
"""

from __future__ import annotations

from pathlib import Path

from calliodesmo.interfaces.document_loader import DocumentLoader, LoadedDocument
from calliodesmo.interfaces.ocr import OcrProvider
from calliodesmo.providers._base_loader import import_optional

_FITZ_DEP = "fitz"  # PyMuPDF
_FITZ_EXTRA = "documents-pdf"


class PdfLoader(DocumentLoader):
    suffixes = (".pdf",)
    dependency = "pypdf"
    extra = "documents-pdf"

    def __init__(
        self,
        ocr: OcrProvider | None = None,
        *,
        prefer_ocr: bool = False,
        ocr_prompt: str | None = None,
        ocr_image_max_bytes: int | None = None,
    ) -> None:
        self._ocr = ocr
        self._prefer_ocr = prefer_ocr and ocr is not None
        self._ocr_prompt = ocr_prompt or "OCR:"
        self._ocr_max_bytes = ocr_image_max_bytes

    async def load(self, source: str | Path) -> list[LoadedDocument]:
        path = Path(source)
        self._require_path(path)
        pypdf = import_optional(self.dependency, self.extra)
        reader = pypdf.PdfReader(str(path))
        page_count = len(reader.pages)
        docs: list[LoadedDocument] = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            ocr_used = False
            if self._prefer_ocr and not text.strip():
                # 扫描件：渲染成图 -> OCR 转录
                ocr_text = await self._ocr_page(path, i)
                if ocr_text.strip():
                    text, ocr_used = ocr_text, True
            docs.append(
                LoadedDocument(
                    doc_id=f"{path.name}#page{i + 1}",
                    content=text,
                    metadata={
                        "source_path": str(path),
                        "suffix": ".pdf",
                        "page": i + 1,
                        "page_count": page_count,
                        "ocr": ocr_used,
                    },
                )
            )
        return docs

    @staticmethod
    def _require_path(path: Path) -> None:
        """同步文件系统检查（阻塞式 Path 方法不落 async 体）。"""
        if not path.exists():
            raise FileNotFoundError(f"文档源不存在: {path}")

    async def _ocr_page(self, path: Path, page_index: int) -> str:
        """渲染指定页为 PNG 并经 OcrProvider 转录（懒加载 PyMuPDF）。"""
        import_optional(_FITZ_DEP, _FITZ_EXTRA)
        import fitz  # PyMuPDF 懒导入

        doc = fitz.open(str(path))
        try:
            page = doc.load_page(page_index)
            mat = fitz.Matrix(2, 2)  # 2x 缩放提高 OCR 质量（真机验证边界，可按需调）
            pix = page.get_pixmap(matrix=mat)
            png_bytes = pix.tobytes("png")
            if self._ocr_max_bytes and len(png_bytes) > self._ocr_max_bytes:
                # 超上限：降采样重试一次（避免超大页拉爆 OCR）
                pix = page.get_pixmap(matrix=fitz.Matrix(1, 1))
                png_bytes = pix.tobytes("png")
        finally:
            doc.close()
        result = await self._ocr.extract_text(png_bytes, mime="image/png", prompt=self._ocr_prompt)
        return result.text
