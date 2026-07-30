"""Task 6：ingest CLI 测试（CliRunner + 桩引擎 + 审计落库）。

P4.5 Task 1：走真实 PG（``cli_db`` 唯一 schema 隔离），inspect 经 ``cli_inspect``，
不再用 sqlite3 + sqlite 文件。
"""

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


def _init() -> None:
    """cli_db 已预建 schema 并 patch engine；这里跑 db init 建表。"""
    get_settings.cache_clear()
    try:
        assert runner.invoke(app, ["db", "init"]).exit_code == 0
    finally:
        get_settings.cache_clear()


def test_ingest_success(tmp_path, monkeypatch, cli_db, cli_inspect):
    _init()
    monkeypatch.setattr("calliodesmo.cli.build_default_indexing_engine", _stub_engine_factory)
    (tmp_path / "note.md").write_text("OpenAI 开发了 GPT-4。", encoding="utf-8")
    try:
        result = runner.invoke(app, ["ingest", str(tmp_path / "note.md")])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0, result.output
    assert "文档 1" in result.output
    assert "实体 2" in result.output

    rows = cli_inspect("SELECT action, resource_type, source FROM audit_logs")
    assert rows and rows[0] == ("ingest", "document", "cli")


def test_ingest_path_not_exists(tmp_path, monkeypatch, cli_db):
    _init()
    monkeypatch.setattr("calliodesmo.cli.build_default_indexing_engine", _stub_engine_factory)
    try:
        result = runner.invoke(app, ["ingest", str(tmp_path / "nope.md")])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 1
    assert "不存在" in result.output


def test_ingest_unregistered_suffix(tmp_path, monkeypatch, cli_db):
    _init()
    monkeypatch.setattr("calliodesmo.cli.build_default_indexing_engine", _stub_engine_factory)
    # 用真正未注册的后缀（.pdf 在装了 documents-pdf extra 后会注册，不再适合测未注册）
    f = tmp_path / "doc.xyzunknown"
    f.write_text("dummy", encoding="utf-8")
    try:
        result = runner.invoke(app, ["ingest", str(f)])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 1
    assert "未注册的文件类型" in result.output


def test_ingest_llm_missing_key(tmp_path, monkeypatch, cli_db):
    _init()
    monkeypatch.setenv("CALLIODESMO_LLM_MODEL", "openai/gpt-4o-mini")
    # setenv 空串：环境变量覆盖 .env，使 llm_api_key="" -> not "" 触发缺 key 报错
    # （delenv 无效：Settings() 会重读 .env 取回 key）
    monkeypatch.setenv("CALLIODESMO_LLM_API_KEY", "")
    get_settings.cache_clear()
    (tmp_path / "note.md").write_text("OpenAI 开发了 GPT-4。", encoding="utf-8")
    try:
        result = runner.invoke(app, ["ingest", str(tmp_path / "note.md")])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 1
    assert "CALLIODESMO_LLM_API_KEY" in result.output


def test_ingest_local_apibase_exempt_from_key(tmp_path, monkeypatch, cli_db):
    """指向 localhost 的 api_base（LM Studio / llama.cpp / Ollama）无需 API key。"""
    _init()
    monkeypatch.setattr("calliodesmo.cli.build_default_indexing_engine", _stub_engine_factory)
    monkeypatch.setenv("CALLIODESMO_LLM_MODEL", "openai/local-model")
    monkeypatch.setenv("CALLIODESMO_LLM_API_BASE", "http://localhost:1234/v1")
    monkeypatch.setenv("CALLIODESMO_LLM_API_KEY", "")
    (tmp_path / "note.md").write_text("OpenAI 开发了 GPT-4。", encoding="utf-8")
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["ingest", str(tmp_path / "note.md")])
    finally:
        get_settings.cache_clear()
    # 本地豁免 -> 不因缺 key 报错（桩引擎跑通）
    assert result.exit_code == 0, result.output


def test_ingest_lm_studio_prefix_exempt_from_key(tmp_path, monkeypatch, cli_db):
    """lm-studio/ 前缀同样豁免 key。"""
    _init()
    monkeypatch.setattr("calliodesmo.cli.build_default_indexing_engine", _stub_engine_factory)
    monkeypatch.setenv("CALLIODESMO_LLM_MODEL", "lm-studio/local-model")
    monkeypatch.setenv("CALLIODESMO_LLM_API_KEY", "")
    (tmp_path / "note.md").write_text("OpenAI 开发了 GPT-4。", encoding="utf-8")
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["ingest", str(tmp_path / "note.md")])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0, result.output
