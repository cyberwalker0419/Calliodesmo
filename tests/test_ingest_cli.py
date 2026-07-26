"""Task 6：ingest CLI 测试（CliRunner + 桩引擎 + 审计落库）。"""

import sqlite3

from typer.testing import CliRunner

from calliodesmo.cli import app
from calliodesmo.config import get_settings

runner = CliRunner()


def _stub_engine_factory(settings):
    import json

    from calliodesmo.ecl.chunker import TextChunker
    from calliodesmo.ecl.cognify import CognifyPipeline
    from calliodesmo.ecl.community_deriver import DocumentCommunityDeriver
    from calliodesmo.ecl.engine import ECLIndexingEngine
    from calliodesmo.ecl.extraction_template import ExtractionTemplateRegistry
    from calliodesmo.ecl.extractor import LLMExtractor
    from calliodesmo.ecl.load import LoadService
    from calliodesmo.interfaces.llm import LLMProvider, LLMResponse
    from calliodesmo.providers.hash_embedding import HashEmbeddingProvider
    from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
    from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
    from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
    from calliodesmo.providers.registry import default_registry

    class _Ext(LLMProvider):
        async def complete(self, messages, *, temperature=0.2, max_tokens=None) -> LLMResponse:
            return LLMResponse(
                content=json.dumps(
                    {
                        "entities": [
                            {"name": "OpenAI", "type": "organization", "description": "AI 公司"},
                            {"name": "GPT-4", "type": "model", "description": "大模型"},
                        ],
                        "relations": [
                            {
                                "source": "OpenAI",
                                "target": "GPT-4",
                                "type": "developed",
                                "description": "",
                            }
                        ],
                        "claims": [],
                        "covariates": [],
                    },
                    ensure_ascii=False,
                ),
                model="stub",
            )

    class _Sum(LLMProvider):
        async def complete(self, messages, *, temperature=0.2, max_tokens=None) -> LLMResponse:
            return LLMResponse(content='{"title":"T","summary":"S"}', model="stub")

    cs = InMemoryCommunityStore()
    return ECLIndexingEngine(
        loader=default_registry(),
        chunker=TextChunker(),
        extractor=LLMExtractor(_Ext(), ExtractionTemplateRegistry()),
        cognify=CognifyPipeline(summarizer=None),
        load_service=LoadService(
            InMemoryVectorStore(), InMemoryGraphStore(), cs, HashEmbeddingProvider(32)
        ),
        deriver=DocumentCommunityDeriver(_Sum(), cs),
    )


def _setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("CALLIODESMO_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    get_settings.cache_clear()
    runner.invoke(app, ["db", "init"])
    return db_path


def test_ingest_success(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path, monkeypatch)
    monkeypatch.setattr("calliodesmo.cli.build_default_indexing_engine", _stub_engine_factory)
    (tmp_path / "note.md").write_text("OpenAI 开发了 GPT-4。", encoding="utf-8")
    try:
        result = runner.invoke(app, ["ingest", str(tmp_path / "note.md")])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0, result.output
    assert "文档 1" in result.output
    assert "实体 2" in result.output

    conn = sqlite3.connect(db_path)
    rows = list(conn.execute("SELECT action, resource_type, source FROM audit_logs"))
    conn.close()
    assert rows and rows[0] == ("ingest", "document", "cli")


def test_ingest_path_not_exists(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    monkeypatch.setattr("calliodesmo.cli.build_default_indexing_engine", _stub_engine_factory)
    try:
        result = runner.invoke(app, ["ingest", str(tmp_path / "nope.md")])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 1
    assert "不存在" in result.output


def test_ingest_unregistered_suffix(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    monkeypatch.setattr("calliodesmo.cli.build_default_indexing_engine", _stub_engine_factory)
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 dummy")
    try:
        result = runner.invoke(app, ["ingest", str(f)])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 1
    assert "documents-pdf" in result.output


def test_ingest_llm_missing_key(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    monkeypatch.setenv("CALLIODESMO_LLM_MODEL", "openai/gpt-4o-mini")
    monkeypatch.delenv("CALLIODESMO_LLM_API_KEY", raising=False)
    get_settings.cache_clear()
    (tmp_path / "note.md").write_text("OpenAI 开发了 GPT-4。", encoding="utf-8")
    try:
        result = runner.invoke(app, ["ingest", str(tmp_path / "note.md")])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 1
    assert "CALLIODESMO_LLM_API_KEY" in result.output


def test_ingest_local_apibase_exempt_from_key(tmp_path, monkeypatch):
    """指向 localhost 的 api_base（LM Studio / llama.cpp / Ollama）无需 API key。"""
    _setup_db(tmp_path, monkeypatch)
    monkeypatch.setattr("calliodesmo.cli.build_default_indexing_engine", _stub_engine_factory)
    monkeypatch.setenv("CALLIODESMO_LLM_MODEL", "openai/local-model")
    monkeypatch.setenv("CALLIODESMO_LLM_API_BASE", "http://localhost:1234/v1")
    monkeypatch.delenv("CALLIODESMO_LLM_API_KEY", raising=False)
    (tmp_path / "note.md").write_text("OpenAI 开发了 GPT-4。", encoding="utf-8")
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["ingest", str(tmp_path / "note.md")])
    finally:
        get_settings.cache_clear()
    # 本地豁免 -> 不因缺 key 报错（桩引擎跑通）
    assert result.exit_code == 0, result.output


def test_ingest_lm_studio_prefix_exempt_from_key(tmp_path, monkeypatch):
    """lm-studio/ 前缀同样豁免 key。"""
    _setup_db(tmp_path, monkeypatch)
    monkeypatch.setattr("calliodesmo.cli.build_default_indexing_engine", _stub_engine_factory)
    monkeypatch.setenv("CALLIODESMO_LLM_MODEL", "lm-studio/local-model")
    monkeypatch.delenv("CALLIODESMO_LLM_API_KEY", raising=False)
    (tmp_path / "note.md").write_text("OpenAI 开发了 GPT-4。", encoding="utf-8")
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["ingest", str(tmp_path / "note.md")])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0, result.output
