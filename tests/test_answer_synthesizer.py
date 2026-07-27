"""Task 4 测试：AnswerSynthesizer 答案合成 + 来源标注。"""

import uuid

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.interfaces.llm import LLMProvider, LLMResponse
from calliodesmo.interfaces.retriever import Candidate, SearchMode
from calliodesmo.retrieval.answer_synthesizer import AnswerSynthesizer

USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _access():
    return AccessContext(
        user_id=USER_ID,
        username="analyst",
        clearance=ClearanceLevel.INTERNAL,
        permissions=frozenset({Permission.QUERY}),
        library_scopes=frozenset({LibraryScope.PERSONAL}),
    )


class _StubLLM(LLMProvider):
    """返回固定带 [chunk_id] 标注答案的桩 LLM。"""

    def __init__(self, answer_text, model="test/stub"):
        self._answer = answer_text
        self._model = model

    async def complete(self, messages, *, temperature=0.2, max_tokens=None):
        return LLMResponse(
            content=self._answer,
            model=self._model,
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )


def _cand(cid, content, score=0.5):
    return Candidate(
        chunk_id=cid,
        doc_id="d",
        content=content,
        score=score,
        rank=1,
    )


class TestAnswerSynthesizer:
    @pytest.mark.asyncio
    async def test_parses_source_chunk_ids(self):
        """桩 LLM 返回带 [chunk_id] 标注的答案 -> 解析出 source_chunk_ids。"""
        llm = _StubLLM("OpenAI 开发了 GPT-4 [c1]。GPT-4 是大规模语言模型 [c2]。")
        synth = AnswerSynthesizer(llm)
        candidates = [_cand("c1", "OpenAI content"), _cand("c2", "GPT-4 content")]
        answer = await synth.synthesize(
            "Who developed GPT-4?", candidates, mode=SearchMode.NATIVE_RAG, access=_access()
        )
        assert "c1" in answer.source_chunk_ids
        assert "c2" in answer.source_chunk_ids
        assert answer.mode == SearchMode.NATIVE_RAG
        assert answer.model == "test/stub"
        assert answer.usage["total_tokens"] == 30

    @pytest.mark.asyncio
    async def test_empty_candidates_no_fabrication(self):
        """候选为空时返回'无可引用证据'而非编造。"""
        llm = _StubLLM("should not be called")
        synth = AnswerSynthesizer(llm)
        answer = await synth.synthesize("test", [], mode=SearchMode.NATIVE_RAG, access=_access())
        assert "无可引用证据" in answer.text
        assert answer.source_chunk_ids == []
        assert answer.context_chunks == []

    @pytest.mark.asyncio
    async def test_context_chunks_populated(self):
        """context_chunks 包含喂模型的上下文摘要。"""
        llm = _StubLLM("answer [c1]")
        synth = AnswerSynthesizer(llm)
        candidates = [_cand("c1", "content", 0.9)]
        answer = await synth.synthesize("q", candidates, mode=SearchMode.LOCAL, access=_access())
        assert len(answer.context_chunks) == 1
        assert answer.context_chunks[0]["chunk_id"] == "c1"
        assert answer.context_chunks[0]["score"] == 0.9

    @pytest.mark.asyncio
    async def test_fallback_all_candidates_when_no_citations(self):
        """LLM 未标注来源时，回退为全部候选。"""
        llm = _StubLLM("This is an answer without citations.")
        synth = AnswerSynthesizer(llm)
        candidates = [_cand("c1", "a"), _cand("c2", "b")]
        answer = await synth.synthesize("q", candidates, mode=SearchMode.GLOBAL, access=_access())
        assert set(answer.source_chunk_ids) == {"c1", "c2"}

    @pytest.mark.asyncio
    async def test_dedup_source_ids(self):
        """重复标注的 chunk_id 去重保序。"""
        llm = _StubLLM("see [c1] and [c1] again [c2] and [c1].")
        synth = AnswerSynthesizer(llm)
        candidates = [_cand("c1", "a"), _cand("c2", "b")]
        answer = await synth.synthesize(
            "q", candidates, mode=SearchMode.NATIVE_RAG, access=_access()
        )
        assert answer.source_chunk_ids == ["c1", "c2"]

    @pytest.mark.asyncio
    async def test_invalid_citations_filtered(self):
        """不在候选中的标注被过滤。"""
        llm = _StubLLM("answer [c1] and [fake_id].")
        synth = AnswerSynthesizer(llm)
        candidates = [_cand("c1", "a")]
        answer = await synth.synthesize(
            "q", candidates, mode=SearchMode.NATIVE_RAG, access=_access()
        )
        assert answer.source_chunk_ids == ["c1"]
        assert "fake_id" not in answer.source_chunk_ids
