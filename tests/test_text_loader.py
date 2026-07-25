from pathlib import Path

import pytest

from calliodesmo.providers.text_loader import TextDocumentLoader


async def test_load_directory(tmp_path):
    (tmp_path / "a.md").write_text("# 标题", encoding="utf-8")
    (tmp_path / "b.txt").write_text("正文", encoding="utf-8")
    (tmp_path / "c.py").write_text("print('skip')", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "d.md").write_text("子目录文档", encoding="utf-8")

    docs = await TextDocumentLoader().load(tmp_path)

    assert {d.doc_id for d in docs} == {"a.md", "b.txt", str(Path("sub") / "d.md")}
    by_id = {d.doc_id: d for d in docs}
    assert by_id["a.md"].content == "# 标题"
    assert by_id["a.md"].metadata["suffix"] == ".md"
    assert by_id["a.md"].metadata["size_bytes"] > 0


async def test_load_single_file(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("单文件", encoding="utf-8")
    docs = await TextDocumentLoader().load(f)
    assert len(docs) == 1
    assert docs[0].doc_id == "note.md"


async def test_unsupported_suffix(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("a,b", encoding="utf-8")
    with pytest.raises(ValueError, match="不支持的文件类型"):
        await TextDocumentLoader().load(f)


async def test_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        await TextDocumentLoader().load(tmp_path / "nope")
