"""Task 6 测试：L0 chunk 摘要按需补生。"""

import pytest

from calliodesmo.ecl.chunk_summarizer import LLMChunkSummarizer
from calliodesmo.interfaces.llm import LLMProvider, LLMResponse


class _StubLLM(LLMProvider):
    def __init__(self, summary="short summary"):
        self._summary = summary

    async def complete(self, messages, *, temperature=0.2, max_tokens=None):
        return LLMResponse(content=self._summary, model="test/stub", usage={})


class TestLLMChunkSummarizer:
    @pytest.mark.asyncio
    async def test_generates_summary(self):
        llm = _StubLLM("This is a short summary.")
        summarizer = LLMChunkSummarizer(llm, enabled=True)
        result = await summarizer.summarize("A" * 200)
        assert result == "This is a short summary."

    @pytest.mark.asyncio
    async def test_empty_content(self):
        llm = _StubLLM()
        summarizer = LLMChunkSummarizer(llm, enabled=True)
        result = await summarizer.summarize("")
        assert result == ""

    @pytest.mark.asyncio
    async def test_short_content_returns_truncated(self):
        llm = _StubLLM()
        summarizer = LLMChunkSummarizer(llm, enabled=True)
        result = await summarizer.summarize("short")
        assert result == "short"

    @pytest.mark.asyncio
    async def test_disabled_by_default(self):
        llm = _StubLLM()
        summarizer = LLMChunkSummarizer(llm, enabled=False)
        result = await summarizer.summarize("A" * 200)
        assert result == ""

    @pytest.mark.asyncio
    async def test_enabled_generates(self):
        llm = _StubLLM("generated summary")
        summarizer = LLMChunkSummarizer(llm, enabled=False)
        assert await summarizer.summarize("A" * 200) == ""
        summarizer2 = LLMChunkSummarizer(llm, enabled=True)
        assert await summarizer2.summarize("A" * 200) == "generated summary"


class TestLoadServiceChunkSummaryIntegration:
    """Task 6 Step 2/3/4：LoadService 集成 + content 不被替换 + 开关。"""

    @pytest.mark.asyncio
    async def test_summary_fills_metadata_not_content(self):
        """摘要入 metadata["summary"]，content 保持原文不被替换。"""
        import uuid

        from calliodesmo.auth.context import AccessContext
        from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
        from calliodesmo.ecl.chunk_summarizer import LLMChunkSummarizer
        from calliodesmo.ecl.load import LoadService
        from calliodesmo.interfaces.chunker import Chunk
        from calliodesmo.interfaces.extractor import ExtractionResult
        from calliodesmo.providers.hash_embedding import HashEmbeddingProvider
        from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
        from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
        from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore

        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        llm = _StubLLM("this is a short summary")
        summarizer = LLMChunkSummarizer(llm, enabled=True)
        vs = InMemoryVectorStore()
        emb = HashEmbeddingProvider(dimension=64)
        load = LoadService(
            vs, InMemoryGraphStore(), InMemoryCommunityStore(), emb, chunk_summarizer=summarizer
        )

        chunk = Chunk(
            chunk_id="c1",
            doc_id="d1",
            content="Sufficiently long original chunk content for testing summary gen",
            ordinal=0,
            access_level=ClearanceLevel.INTERNAL,
            library_scope=LibraryScope.PERSONAL,
            owner_id=user_id,
        )
        access = AccessContext(
            user_id=user_id,
            username="u",
            clearance=ClearanceLevel.INTERNAL,
            permissions=frozenset({Permission.INGEST}),
            library_scopes=frozenset({LibraryScope.PERSONAL}),
        )
        await load.load([chunk], ExtractionResult(), [], access=access)

        records = await vs.get_chunks_by_ids(["c1"])
        assert len(records) == 1
        rec = records[0]
        # content 保持原文，不被摘要替换
        assert rec.content == "Sufficiently long original chunk content for testing summary gen"
        # 摘要入 metadata
        assert rec.metadata.get("summary") == "this is a short summary"

    @pytest.mark.asyncio
    async def test_summary_disabled_no_metadata(self):
        """chunk_summary_enabled=False 时 metadata 无 summary。"""
        import uuid

        from calliodesmo.auth.context import AccessContext
        from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
        from calliodesmo.ecl.load import LoadService
        from calliodesmo.interfaces.chunker import Chunk
        from calliodesmo.interfaces.extractor import ExtractionResult
        from calliodesmo.providers.hash_embedding import HashEmbeddingProvider
        from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
        from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
        from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore

        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        vs = InMemoryVectorStore()
        emb = HashEmbeddingProvider(dimension=64)
        # 不注入 summarizer -> 等同关闭
        load = LoadService(
            vs, InMemoryGraphStore(), InMemoryCommunityStore(), emb, chunk_summarizer=None
        )

        chunk = Chunk(
            chunk_id="c1",
            doc_id="d1",
            content="original chunk content long enough",
            ordinal=0,
            access_level=ClearanceLevel.INTERNAL,
            library_scope=LibraryScope.PERSONAL,
            owner_id=user_id,
        )
        access = AccessContext(
            user_id=user_id,
            username="u",
            clearance=ClearanceLevel.INTERNAL,
            permissions=frozenset({Permission.INGEST}),
            library_scopes=frozenset({LibraryScope.PERSONAL}),
        )
        await load.load([chunk], ExtractionResult(), [], access=access)

        records = await vs.get_chunks_by_ids(["c1"])
        assert "summary" not in records[0].metadata

    @pytest.mark.asyncio
    async def test_native_rag_candidate_carries_summary(self):
        """Candidate 召回后可携带 metadata["summary"] 供 UI 预览。"""
        import uuid

        from calliodesmo.auth.context import AccessContext
        from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
        from calliodesmo.interfaces.retriever import SearchMode
        from calliodesmo.interfaces.vector_store import ChunkRecord
        from calliodesmo.providers.hash_embedding import HashEmbeddingProvider
        from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
        from calliodesmo.retrieval.hybrid_retriever import HybridRetriever

        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        emb = HashEmbeddingProvider(dimension=64)
        vs = InMemoryVectorStore()
        vec = emb._embed_one("AI research content")
        await vs.upsert_chunks(
            [
                ChunkRecord(
                    chunk_id="c1",
                    doc_id="d1",
                    content="AI research content",
                    vector=vec,
                    metadata={"summary": "AI summary for preview"},
                    owner_id=user_id,
                )
            ]
        )
        retriever = HybridRetriever(vector_store=vs, embedding_provider=emb, sparse_index=None)
        access = AccessContext(
            user_id=user_id,
            username="u",
            clearance=ClearanceLevel.INTERNAL,
            permissions=frozenset({Permission.QUERY}),
            library_scopes=frozenset({LibraryScope.PERSONAL}),
        )
        results = await retriever.retrieve("AI", top_k=5, mode=SearchMode.NATIVE_RAG, access=access)
        assert len(results) >= 1
        assert results[0].metadata.get("summary") == "AI summary for preview"
