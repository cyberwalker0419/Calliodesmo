"""Task 1：多格式文档加载器 + LoaderRegistry 测试。"""

import json
import sys

import pytest

from calliodesmo.providers.markup_loader import OrgLoader, RstLoader, TexLoader
from calliodesmo.providers.registry import LoaderRegistry, default_registry
from calliodesmo.providers.structured_loader import (
    CsvLoader,
    HtmlLoader,
    JsonLoader,
    XmlLoader,
    YamlLoader,
)
from calliodesmo.providers.text_loader import TextDocumentLoader

# ---- Step 1: txt/md/log 回归 ----


async def test_text_loader_supports_log(tmp_path):
    f = tmp_path / "run.log"
    f.write_text("line1\nline2\n", encoding="utf-8")
    docs = await TextDocumentLoader().load(f)
    assert len(docs) == 1
    assert docs[0].content == "line1\nline2\n"
    assert docs[0].metadata["suffix"] == ".log"


async def test_text_loader_directory_regression(tmp_path):
    (tmp_path / "a.md").write_text("# A", encoding="utf-8")
    (tmp_path / "b.txt").write_text("B", encoding="utf-8")
    docs = await TextDocumentLoader().load(tmp_path)
    assert {d.doc_id for d in docs} == {"a.md", "b.txt"}


# ---- Step 2: registry 分发与未注册报错 ----


async def test_registry_dispatches_by_suffix(tmp_path):
    (tmp_path / "note.md").write_text("# hi", encoding="utf-8")
    (tmp_path / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    reg = default_registry()
    docs = await reg.load(tmp_path)
    by_suffix = {d.metadata["suffix"] for d in docs}
    assert {".md", ".csv"} <= by_suffix


def test_registry_resolve_unregistered_suffix_suggests_extra():
    reg = LoaderRegistry()  # 空 registry
    with pytest.raises(ValueError, match="documents-pdf"):
        reg.resolve("foo.pdf")


def test_registry_resolve_truly_unknown_suffix():
    reg = LoaderRegistry()
    with pytest.raises(ValueError, match="未注册的文件类型"):
        reg.resolve("foo.xyz")


# ---- Step 3: csv/tsv ----


async def test_csv_loader(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("name,age\nAlice,30\nBob,25\n", encoding="utf-8")
    docs = await CsvLoader().load(f)
    assert len(docs) == 1
    assert "Alice" in docs[0].content and "Bob" in docs[0].content
    assert docs[0].metadata["headers"] == ["name", "age"]
    assert docs[0].metadata["row_count"] == 3


async def test_tsv_loader(tmp_path):
    f = tmp_path / "data.tsv"
    f.write_text("a\tb\n1\t2\n", encoding="utf-8")
    docs = await CsvLoader(delimiter="\t").load(f)
    assert docs[0].metadata["headers"] == ["a", "b"]


async def test_csv_empty_file(tmp_path):
    f = tmp_path / "empty.csv"
    f.write_text("", encoding="utf-8")
    docs = await CsvLoader().load(f)
    assert docs[0].content == ""
    assert docs[0].metadata["row_count"] == 0


# ---- Step 4: json/yaml/xml/html ----


async def test_json_loader(tmp_path):
    f = tmp_path / "data.json"
    f.write_text(json.dumps({"k": "v", "n": 3}, ensure_ascii=False), encoding="utf-8")
    docs = await JsonLoader().load(f)
    assert '"k"' in docs[0].content
    assert docs[0].metadata["json_type"] == "dict"


async def test_yaml_loader(tmp_path):
    f = tmp_path / "data.yaml"
    f.write_text("name: Alice\nage: 30\n", encoding="utf-8")
    docs = await YamlLoader().load(f)
    assert "Alice" in docs[0].content
    assert docs[0].metadata["yaml_type"] == "dict"


async def test_xml_loader(tmp_path):
    f = tmp_path / "data.xml"
    f.write_text("<root><a>hello</a><b>world</b></root>", encoding="utf-8")
    docs = await XmlLoader().load(f)
    assert "hello" in docs[0].content and "world" in docs[0].content


async def test_html_loader(tmp_path):
    f = tmp_path / "page.html"
    f.write_text("<html><body><p>Hello</p><p>World</p></body></html>", encoding="utf-8")
    docs = await HtmlLoader().load(f)
    assert "Hello" in docs[0].content and "World" in docs[0].content


# ---- Step 5: rst/org/tex ----


async def test_rst_loader(tmp_path):
    f = tmp_path / "doc.rst"
    f.write_text("Title\n=====\n\n:role:`link` text", encoding="utf-8")
    docs = await RstLoader().load(f)
    assert "link" in docs[0].content
    assert "Title" in docs[0].content


async def test_org_loader(tmp_path):
    f = tmp_path / "note.org"
    f.write_text("* Heading\nSome [[https://x.com][link]] text", encoding="utf-8")
    docs = await OrgLoader().load(f)
    assert "link" in docs[0].content


async def test_tex_loader(tmp_path):
    f = tmp_path / "paper.tex"
    f.write_text(r"\section{Intro} Hello \textbf{world} % comment", encoding="utf-8")
    docs = await TexLoader().load(f)
    assert "Intro" in docs[0].content
    assert "world" in docs[0].content
    assert "comment" not in docs[0].content


# ---- Step 14: 缺依赖友好报错 ----


def _force_missing(monkeypatch, name):
    monkeypatch.setitem(sys.modules, name, None)


async def test_pdf_missing_dependency_friendly_error(tmp_path, monkeypatch):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 dummy")
    _force_missing(monkeypatch, "pypdf")
    from calliodesmo.providers.pdf_loader import PdfLoader

    loader = PdfLoader()
    with pytest.raises(RuntimeError, match="documents-pdf"):
        await loader.load(f)


def test_office_missing_dependency_friendly_error(tmp_path, monkeypatch):
    f = tmp_path / "doc.docx"
    f.write_bytes(b"PK dummy")
    _force_missing(monkeypatch, "docx")
    from calliodesmo.providers.office_loader import DocxLoader

    with pytest.raises(RuntimeError, match="documents-office"):
        DocxLoader()._extract_text(f)


def test_registry_skips_heavy_when_dep_absent(monkeypatch):
    # 模拟所有重依赖缺失：default_registry 不应注册它们，resolve 给出 extra 提示
    import calliodesmo.providers.registry as registry_mod

    monkeypatch.setattr(registry_mod, "dependency_available", lambda name: False)
    reg = default_registry()
    assert ".pdf" not in reg.registered_suffixes
    assert ".docx" not in reg.registered_suffixes
    with pytest.raises(ValueError, match="documents-pdf"):
        reg.resolve("x.pdf")


# ---- Step 15: 端到端冒烟（内置格式）----


async def test_default_registry_end_to_end(tmp_path):
    (tmp_path / "a.md").write_text("# Title", encoding="utf-8")
    (tmp_path / "b.json").write_text('{"k": 1}', encoding="utf-8")
    (tmp_path / "c.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    reg = default_registry()
    docs = await reg.load(tmp_path)
    suffixes = {d.metadata["suffix"] for d in docs}
    assert {".md", ".json", ".csv"} <= suffixes


def test_new_format_register_one_line():
    reg = LoaderRegistry()
    reg.register(".xyz", TextDocumentLoader())
    assert isinstance(reg.resolve("a.xyz"), TextDocumentLoader)
