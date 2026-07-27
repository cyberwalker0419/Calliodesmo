"""Task 5 测试：评估 harness。"""

import uuid

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.eval.golden import GoldenCase, load_golden
from calliodesmo.eval.metrics import _parse_score, context_recall
from calliodesmo.interfaces.llm import LLMProvider, LLMResponse
from calliodesmo.interfaces.retriever import Answer

USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _access():
    return AccessContext(
        user_id=USER_ID,
        username="analyst",
        clearance=ClearanceLevel.INTERNAL,
        permissions=frozenset({Permission.QUERY}),
        library_scopes=frozenset({LibraryScope.PERSONAL}),
    )


class _StubJudge(LLMProvider):
    def __init__(self, score=0.8):
        self._score = score

    async def complete(self, messages, *, temperature=0.2, max_tokens=None):
        return LLMResponse(content=str(self._score), model="test/judge", usage={})


class _StubEngine:
    """返回固定 Answer 的桩 SearchEngine。"""

    def __init__(self, answer_text="answer [c1]", source_ids=None):
        self._answer_text = answer_text
        self._source_ids = source_ids or ["c1"]

    async def query(self, question, *, mode, top_k, access):
        return Answer(
            text=self._answer_text,
            source_chunk_ids=self._source_ids,
            mode=mode,
            context_chunks=[
                {"chunk_id": sid, "content": f"content-{sid}", "score": 0.9}
                for sid in self._source_ids
            ],
            model="test",
            usage={},
        )


class TestGoldenCase:
    def test_data_model(self):
        c = GoldenCase(question="q", expected_answer="a", relevant_chunk_ids=["c1"], mode="local")
        assert c.question == "q"
        assert c.expected_answer == "a"
        assert c.relevant_chunk_ids == ["c1"]
        assert c.mode == "local"

    def test_defaults(self):
        c = GoldenCase(question="q", expected_answer="a")
        assert c.relevant_chunk_ids == []
        assert c.mode == "native_rag"

    def test_load_empty_file(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("", encoding="utf-8")
        assert load_golden(f) == []

    def test_load_nonexistent(self):
        assert load_golden("nonexistent.yaml") == []

    def test_load_yaml(self, tmp_path):
        f = tmp_path / "golden.yaml"
        f.write_text(
            """
cases:
  - question: "What is X?"
    expected_answer: "X is Y"
    relevant_chunk_ids: ["c1", "c2"]
    mode: "native_rag"
  - question: "Who is Z?"
    expected_answer: "Z is W"
""",
            encoding="utf-8",
        )
        cases = load_golden(f)
        assert len(cases) == 2
        assert cases[0].question == "What is X?"
        assert cases[1].mode == "native_rag"


class TestContextRecall:
    def test_full_recall(self):
        assert context_recall(["c1", "c2"], {"c1", "c2"}) == 1.0

    def test_partial_recall(self):
        assert context_recall(["c1", "c3"], {"c1", "c2"}) == 0.5

    def test_no_recall(self):
        assert context_recall(["c3"], {"c1", "c2"}) == 0.0

    def test_no_relevant(self):
        assert context_recall(["c1"], set()) == 0.0

    def test_empty_retrieved(self):
        assert context_recall([], {"c1"}) == 0.0


class TestParseScore:
    def test_valid_float(self):
        assert _parse_score("0.75") == 0.75

    def test_valid_int(self):
        assert _parse_score("1") == 1.0

    def test_clamp(self):
        assert _parse_score("1.5") == 1.0

    def test_invalid(self):
        assert _parse_score("not a number") == 0.0

    def test_embedded(self):
        assert _parse_score("score: 0.8") == 0.8


class TestEvalHarness:
    @pytest.mark.asyncio
    async def test_run_full(self):
        from calliodesmo.eval.harness import EvalHarness

        engine = _StubEngine()
        judge = _StubJudge(0.8)
        harness = EvalHarness(engine, judge)
        cases = [
            GoldenCase(question="q1", expected_answer="a1", relevant_chunk_ids=["c1"]),
            GoldenCase(question="q2", expected_answer="a2", relevant_chunk_ids=["c2"]),
        ]
        report = await harness.run(cases, access=_access())
        assert report.total == 2
        assert 0 <= report.mean_context_recall <= 1
        assert 0 <= report.mean_faithfulness <= 1
        assert 0 <= report.mean_answer_relevance <= 1
        assert len(report.cases) == 2

    @pytest.mark.asyncio
    async def test_empty_cases(self):
        from calliodesmo.eval.harness import EvalHarness

        engine = _StubEngine()
        judge = _StubJudge()
        harness = EvalHarness(engine, judge)
        report = await harness.run([], access=_access())
        assert report.total == 0

    @pytest.mark.asyncio
    async def test_deterministic(self):
        """两次运行同输入同输出（回归基线确定性）。"""
        from calliodesmo.eval.harness import EvalHarness

        engine = _StubEngine()
        judge = _StubJudge(0.8)
        harness = EvalHarness(engine, judge)
        cases = [GoldenCase(question="q", expected_answer="a", relevant_chunk_ids=["c1"])]
        r1 = await harness.run(cases, access=_access())
        r2 = await harness.run(cases, access=_access())
        assert r1.mean_context_recall == r2.mean_context_recall
        assert r1.mean_faithfulness == r2.mean_faithfulness
        assert r1.mean_answer_relevance == r2.mean_answer_relevance
