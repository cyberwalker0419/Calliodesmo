"""PDF 加载器（extra: documents-pdf）：按页切分 LoadedDocument，仅支持文本型。"""

from __future__ import annotations

from pathlib import Path

from calliodesmo.interfaces.document_loader import LoadedDocument
from calliodesmo.providers._base_loader import SingleFileLoader


class PdfLoader(SingleFileLoader):
    suffixes = (".pdf",)
    dependency = "pypdf"
    extra = "documents-pdf"

    def _load_sync(self, path: Path) -> list[LoadedDocument]:
        pypdf = self._require_dep()
        reader = pypdf.PdfReader(str(path))
        page_count = len(reader.pages)
        docs: list[LoadedDocument] = []
        for i, page in enumerate(reader.pages):
            docs.append(
                LoadedDocument(
                    doc_id=f"{path.name}#page{i + 1}",
                    content=page.extract_text() or "",
                    metadata={
                        "source_path": str(path),
                        "suffix": ".pdf",
                        "page": i + 1,
                        "page_count": page_count,
                    },
                )
            )
        return docs
