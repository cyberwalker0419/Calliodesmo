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
