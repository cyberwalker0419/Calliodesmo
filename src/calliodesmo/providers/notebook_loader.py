"""Jupyter 笔记本加载器（extra: documents-notebooks）：ipynb 经 nbformat，cell 拼接。"""

from __future__ import annotations

from pathlib import Path

from calliodesmo.providers._base_loader import SingleFileLoader


class NotebookLoader(SingleFileLoader):
    suffixes = (".ipynb",)
    dependency = "nbformat"
    extra = "documents-notebooks"

    def _extract_text(self, path: Path) -> str:
        nbformat = self._require_dep()
        nb = nbformat.read(str(path), as_version=4)
        parts = []
        for cell in nb.cells:
            src = cell.get("source", "")
            if isinstance(src, list):
                src = "".join(src)
            if src.strip():
                parts.append(f"[{cell.cell_type}]\n{src.strip()}")
        return "\n\n".join(parts)

    def _extra_metadata(self, path: Path) -> dict:
        nbformat = self._require_dep()
        nb = nbformat.read(str(path), as_version=4)
        return {"cell_count": len(nb.cells)}
