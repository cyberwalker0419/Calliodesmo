"""默认 DocumentLoader：从单文件或目录加载 Markdown / 纯文本文档。"""

import hashlib
from pathlib import Path

from calliodesmo.interfaces.document_loader import DocumentLoader, LoadedDocument

SUPPORTED_SUFFIXES = {".txt", ".log", ".md", ".markdown"}


class TextDocumentLoader(DocumentLoader):
    async def load(self, source: str | Path) -> list[LoadedDocument]:
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(f"文档源不存在: {source}")
        if source.is_file():
            if source.suffix.lower() not in SUPPORTED_SUFFIXES:
                raise ValueError(
                    f"不支持的文件类型: {source.suffix}（支持 {sorted(SUPPORTED_SUFFIXES)}）"
                )
            files = [source]
            base = source.parent
        else:
            files = sorted(
                p
                for p in source.rglob("*")
                if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
            )
            base = source

        documents = []
        for path in files:
            content = path.read_text(encoding="utf-8")
            documents.append(
                LoadedDocument(
                    doc_id=str(path.relative_to(base)),
                    content=content,
                    metadata={
                        "source_path": str(path),
                        "suffix": path.suffix.lower(),
                        "size_bytes": path.stat().st_size,
                    },
                    content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                )
            )
        return documents
