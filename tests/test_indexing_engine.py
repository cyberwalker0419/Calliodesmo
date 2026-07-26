"""Task 6：ECLIndexingEngine 端到端串联测试（桩 LLM + Hash 嵌入 + 内存 stores）。"""

import json
import uuid

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
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


class _ExtractionLLM(LLMProvider):
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
                            "description": "开发",
                        }
                    ],
                    "claims": [{"text": "OpenAI 开发了 GPT-4", "entity_name": "OpenAI"}],
                    "covariates": [{"name": "role", "entity_name": "OpenAI", "value": "developer"}],
                },
                ensure_ascii=False,
            ),
            model="stub",
        )


class _SummaryLLM(LLMProvider):
    async def complete(self, messages, *, temperature=0.2, max_tokens=None) -> LLMResponse:
        return LLMResponse(
            content='{"title":"文档生态","summary":"OpenAI 与 GPT-4 概览。"}', model="stub"
        )


def _build_engine():
    vector_store = InMemoryVectorStore()
    graph_store = InMemoryGraphStore()
    community_store = InMemoryCommunityStore()
    extractor = LLMExtractor(_ExtractionLLM(), ExtractionTemplateRegistry())
    cognify = CognifyPipeline(summarizer=None)
    load_service = LoadService(
        vector_store, graph_store, community_store, HashEmbeddingProvider(32)
    )
    deriver = DocumentCommunityDeriver(_SummaryLLM(), community_store)
    return (
        ECLIndexingEngine(
            loader=default_registry(),
            chunker=TextChunker(chunk_size=1200, overlap=100),
            extractor=extractor,
            cognify=cognify,
            load_service=load_service,
            deriver=deriver,
        ),
        vector_store,
        graph_store,
        community_store,
    )


async def test_engine_end_to_end(tmp_path):
    (tmp_path / "note.md").write_text("OpenAI 开发了 GPT-4。OpenAI 是 AI 公司。", encoding="utf-8")
    owner = uuid.uuid4()
    access = AccessContext(
        user_id=owner,
        username="u",
        clearance=ClearanceLevel.INTERNAL,
        library_scopes=frozenset({LibraryScope.PERSONAL}),
    )
    engine, vs, gs, cs = _build_engine()
    stats = await engine.ingest(tmp_path, access=access)
    assert stats.documents == 1
    assert stats.chunks >= 1
    assert stats.entities == 2
    assert stats.relations == 1
    assert stats.communities >= 1  # 实体社区 + 文档社区
    # 三 store 有数据
    assert len(vs) >= 1
    assert len(gs) >= 1
    assert len(cs) >= 1


async def test_engine_personal_scope_isolation(tmp_path):
    (tmp_path / "note.md").write_text("OpenAI 开发了 GPT-4。", encoding="utf-8")
    owner = uuid.uuid4()
    access = AccessContext(user_id=owner, username="u", clearance=ClearanceLevel.INTERNAL)
    engine, vs, _gs, cs = _build_engine()
    await engine.ingest(tmp_path, access=access)
    # 另一用户检索不可见（personal scope 隔离）
    other = AccessContext(user_id=uuid.uuid4(), username="other", clearance=ClearanceLevel.INTERNAL)
    embed = await HashEmbeddingProvider(32).embed(["OpenAI"])
    hits = await vs.search(embed.vectors[0], top_k=10, access=other)
    assert hits == []
    comms = await cs.list_communities(access=other)
    assert comms == []


async def test_engine_empty_directory(tmp_path):
    access = AccessContext(user_id=uuid.uuid4(), username="u", clearance=ClearanceLevel.INTERNAL)
    engine, *_ = _build_engine()
    stats = await engine.ingest(tmp_path, access=access)
    assert stats.documents == 0
    assert stats.chunks == 0
