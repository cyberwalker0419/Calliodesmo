"""结构化文本加载器：csv/tsv/json/yaml/xml/html（标准库 + PyYAML，内置）。"""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path

from calliodesmo.providers._base_loader import SingleFileLoader


class CsvLoader(SingleFileLoader):
    """CSV/TSV：表头 + 多行拼为正文，空文件返回空串。"""

    suffixes = (".csv", ".tsv")

    def __init__(self, delimiter: str = ",") -> None:
        self.delimiter = delimiter

    def _read_rows(self, path: Path) -> list[list[str]]:
        raw = path.read_text(encoding="utf-8-sig")
        if not raw.strip():
            return []
        return list(csv.reader(StringIO(raw), delimiter=self.delimiter))

    def _extract_text(self, path: Path) -> str:
        rows = self._read_rows(path)
        return "\n".join("\t".join(row) for row in rows)

    def _extra_metadata(self, path: Path) -> dict:
        rows = self._read_rows(path)
        return {"row_count": len(rows), "headers": rows[0] if rows else []}


class JsonLoader(SingleFileLoader):
    """JSON：解析后 pretty-print 为正文，保留结构。"""

    suffixes = (".json",)

    def _read(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _extract_text(self, path: Path) -> str:
        return json.dumps(self._read(path), ensure_ascii=False, indent=2)

    def _extra_metadata(self, path: Path) -> dict:
        return {"json_type": type(self._read(path)).__name__}


class YamlLoader(SingleFileLoader):
    """YAML：经 PyYAML 解析后 pretty-print 为正文。"""

    suffixes = (".yaml", ".yml")

    def _read(self, path):
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8-sig"))

    def _extract_text(self, path: Path) -> str:
        import yaml

        data = self._read(path)
        if data is None:
            return ""
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

    def _extra_metadata(self, path: Path) -> dict:
        data = self._read(path)
        return {"yaml_type": type(data).__name__ if data is not None else "null"}


class XmlLoader(SingleFileLoader):
    """XML：抽取所有元素文本，拼为正文。"""

    suffixes = (".xml",)

    def _extract_text(self, path: Path) -> str:
        tree = ET.parse(path)
        texts = [el.text.strip() for el in tree.iter() if el.text and el.text.strip()]
        return "\n".join(texts)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self._chunks.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self._chunks)


class HtmlLoader(SingleFileLoader):
    """HTML：经 html.parser 抽取可见文本。"""

    suffixes = (".html", ".htm")

    def _extract_text(self, path: Path) -> str:
        extractor = _TextExtractor()
        extractor.feed(path.read_text(encoding="utf-8-sig"))
        return extractor.text
