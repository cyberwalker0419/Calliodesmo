"""富文本/电子书加载器（extra: documents-rich）：rtf 经 striprtf / epub 经 ebooklib。"""

from __future__ import annotations

from pathlib import Path

from calliodesmo.interfaces.document_loader import LoadedDocument
from calliodesmo.providers._base_loader import SingleFileLoader


class RtfLoader(SingleFileLoader):
    suffixes = (".rtf",)
    dependency = "striprtf"
    extra = "documents-rich"

    def _extract_text(self, path: Path) -> str:
        striprtf = self._require_dep()
        return striprtf.striprtf(path.read_text(encoding="utf-8", errors="ignore"))


class EpubLoader(SingleFileLoader):
    suffixes = (".epub",)
    dependency = "ebooklib"
    extra = "documents-rich"

    def _load_sync(self, path: Path) -> list[LoadedDocument]:
        ebooklib = self._require_dep()
        from bs4 import BeautifulSoup  # ebooklib 依赖 BeautifulSoup

        book = ebooklib.epub.read_epub(str(path))
        docs: list[LoadedDocument] = []
        for i, item in enumerate(book.get_items_of_type(ebooklib.epub.ITEM_DOCUMENT)):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text = soup.get_text(separator="\n").strip()
            if text:
                docs.append(
                    LoadedDocument(
                        doc_id=f"{path.name}#part{i + 1}",
                        content=text,
                        metadata={"source_path": str(path), "suffix": ".epub"},
                    )
                )
        return docs
