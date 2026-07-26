"""开放文档加载器（extra: documents-opendocument）：odt/ods/odp 经 odfpy。"""

from __future__ import annotations

from pathlib import Path

from calliodesmo.providers._base_loader import SingleFileLoader


def _odf_text(path: Path, *, extra: str) -> str:
    from calliodesmo.providers._base_loader import import_optional

    odf = import_optional("odf", extra)
    telem = odf.opendocument.load(str(path))
    paragraphs = odf.text.Paragraph
    texts = []
    for p in telem.getElementsByType(paragraphs):
        t = str(p).strip()
        if t:
            texts.append(t)
    return "\n".join(texts)


class OdtLoader(SingleFileLoader):
    suffixes = (".odt",)
    dependency = "odf"
    extra = "documents-opendocument"

    def _extract_text(self, path: Path) -> str:
        return _odf_text(path, extra=self.extra)


class OdsLoader(SingleFileLoader):
    suffixes = (".ods",)
    dependency = "odf"
    extra = "documents-opendocument"

    def _extract_text(self, path: Path) -> str:
        return _odf_text(path, extra=self.extra)


class OdpLoader(SingleFileLoader):
    suffixes = (".odp",)
    dependency = "odf"
    extra = "documents-opendocument"

    def _extract_text(self, path: Path) -> str:
        return _odf_text(path, extra=self.extra)
