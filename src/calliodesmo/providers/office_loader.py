"""Office 加载器（extra: documents-office）：docx 按段落 / xlsx 按 sheet / pptx 按幻灯片。"""

from __future__ import annotations

from pathlib import Path

from calliodesmo.interfaces.document_loader import LoadedDocument
from calliodesmo.providers._base_loader import SingleFileLoader


class DocxLoader(SingleFileLoader):
    suffixes = (".docx",)
    dependency = "docx"
    extra = "documents-office"

    def _extract_text(self, path: Path) -> str:
        docx = self._require_dep()
        doc = docx.Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)

    def _extra_metadata(self, path: Path) -> dict:
        docx = self._require_dep()
        doc = docx.Document(str(path))
        return {"paragraph_count": len(doc.paragraphs)}


class XlsxLoader(SingleFileLoader):
    suffixes = (".xlsx",)
    dependency = "openpyxl"
    extra = "documents-office"

    def _load_sync(self, path: Path) -> list[LoadedDocument]:
        openpyxl = self._require_dep()
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        docs: list[LoadedDocument] = []
        for sheet in wb.worksheets:
            rows = []
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if c is None else str(c) for c in row]
                if any(c.strip() for c in cells):
                    rows.append("\t".join(cells))
            docs.append(
                LoadedDocument(
                    doc_id=f"{path.name}#{sheet.title}",
                    content="\n".join(rows),
                    metadata={
                        "source_path": str(path),
                        "suffix": ".xlsx",
                        "sheet_name": sheet.title,
                    },
                )
            )
        wb.close()
        return docs


class PptxLoader(SingleFileLoader):
    suffixes = (".pptx",)
    dependency = "pptx"
    extra = "documents-office"

    def _load_sync(self, path: Path) -> list[LoadedDocument]:
        pptx = self._require_dep()
        prs = pptx.Presentation(str(path))
        docs: list[LoadedDocument] = []
        for i, slide in enumerate(prs.slides):
            texts = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        t = para.text.strip()
                        if t:
                            texts.append(t)
            docs.append(
                LoadedDocument(
                    doc_id=f"{path.name}#slide{i + 1}",
                    content="\n".join(texts),
                    metadata={
                        "source_path": str(path),
                        "suffix": ".pptx",
                        "slide_number": i + 1,
                    },
                )
            )
        return docs
