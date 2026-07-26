"""Task 2 Step 1-2：TextChunker 结构感知切分测试。"""

import uuid

from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.ecl.chunker import TextChunker
from calliodesmo.interfaces.document_loader import LoadedDocument


def _doc(content: str, **meta) -> LoadedDocument:
    return LoadedDocument(doc_id="d.md", content=content, metadata=meta or {})


async def test_empty_doc_returns_empty():
    assert await TextChunker().chunk(_doc("")) == []
    assert await TextChunker().chunk(_doc("   \n\n  ")) == []


async def test_short_doc_single_chunk():
    doc = _doc("短文档一句话。")
    chunks = await TextChunker(chunk_size=1200, overlap=100).chunk(doc)
    assert len(chunks) == 1
    assert chunks[0].content == "短文档一句话。"
    assert chunks[0].chunk_id == "d.md#0"
    assert chunks[0].ordinal == 0


async def test_deterministic():
    doc = _doc("段落一。\n\n段落二。\n\n段落三。")
    a = await TextChunker(chunk_size=20, overlap=5).chunk(doc)
    b = await TextChunker(chunk_size=20, overlap=5).chunk(doc)
    assert [c.content for c in a] == [c.content for c in b]


async def test_no_lost_coverage():
    sentences = [f"句子编号{i}内容。" for i in range(20)]
    doc = _doc("\n\n".join(sentences))
    chunks = await TextChunker(chunk_size=40, overlap=10).chunk(doc)
    combined = "\n".join(c.content for c in chunks)
    for s in sentences:
        assert s in combined, f"丢失内容: {s}"


async def test_chunk_size_bound():
    doc = _doc("\n\n".join(f"段落{i}。" * 10 for i in range(10)))
    chunks = await TextChunker(chunk_size=50, overlap=10).chunk(doc)
    for c in chunks:
        # 允许单个原子单元超长，否则应 <= chunk_size
        assert len(c.content) <= 50 or len(c.content.split("\n\n")) == 1


async def test_adjacent_chunks_share_overlap():
    doc = _doc("\n\n".join(f"内容块编号{i}结尾。" for i in range(30)))
    chunks = await TextChunker(chunk_size=60, overlap=15).chunk(doc)
    assert len(chunks) >= 2
    for i in range(len(chunks) - 1):
        tail = chunks[i].content[-15:]
        assert chunks[i + 1].content.startswith(tail), f"chunk {i} 与 {i + 1} 无 overlap 接缝"


async def test_code_block_kept_intact():
    code = "```python\nfor i in range(10):\n    print(i)\n```"
    doc = _doc(f"# 标题\n\n正文前。\n\n{code}\n\n正文后。")
    chunks = await TextChunker(chunk_size=30, overlap=5).chunk(doc)
    # 代码块应完整出现在某 chunk 中（不被切断）
    full = "\n".join(c.content for c in chunks)
    assert "```python\nfor i in range(10):\n    print(i)\n```" in full


async def test_chunk_carries_access_fields():
    owner = uuid.uuid4()
    team = uuid.uuid4()
    doc = _doc(
        "内容。",
        owner_id=owner,
        access_level=ClearanceLevel.CONFIDENTIAL,
        library_scope=LibraryScope.TEAM,
        team_id=team,
    )
    chunks = await TextChunker().chunk(doc)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.owner_id == owner
    assert c.access_level == ClearanceLevel.CONFIDENTIAL
    assert c.library_scope == LibraryScope.TEAM
    assert c.team_id == team
    # summary 预留字段 P1 不生成
    assert c.summary is None


def test_overlap_must_be_less_than_chunk_size():
    import pytest

    with pytest.raises(ValueError):
        TextChunker(chunk_size=100, overlap=100)
