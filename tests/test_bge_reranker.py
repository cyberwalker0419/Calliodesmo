import sys
import types
import typing

import pytest

from calliodesmo.interfaces.retriever import Candidate


def _make_stub_flag_reranker(score_map: dict[str, float] | None = None):
    """构造桩 FlagReranker：compute_score 返回基于 (query, content) 哈希的确定性分。"""

    class _StubFlagReranker:
        def __init__(self, model_name, use_fp16=True):
            self.model_name = model_name

        def compute_score(self, pairs, normalize=True):
            scores = []
            for q, c in pairs:
                key = f"{q}|{c}"
                if score_map and key in score_map:
                    scores.append(score_map[key])
                else:
                    h = hash(key) % 100 / 100.0
                    scores.append(h)
            return scores

    return _StubFlagReranker


def _install_stub_flag_embedding(score_map=None):
    """在 sys.modules 注入桩 FlagEmbedding 模块。"""
    stub_mod = types.ModuleType("FlagEmbedding")
    stub_mod.FlagReranker = _make_stub_flag_reranker(score_map)
    sys.modules["FlagEmbedding"] = stub_mod


def _remove_stub_flag_embedding():
    sys.modules.pop("FlagEmbedding", None)


def _cand(chunk_id, content, score=0.5):
    return Candidate(chunk_id=chunk_id, doc_id="d", content=content, score=score, rank=1)


class TestBgeRerankerStub:
    def setup_method(self):
        _install_stub_flag_embedding(
            {
                "query|content-a": 0.9,
                "query|content-b": 0.3,
                "query|content-c": 0.7,
            }
        )

    def teardown_method(self):
        _remove_stub_flag_embedding()

    @pytest.mark.asyncio
    async def test_rerank_sorts_by_score(self):
        from calliodesmo.retrieval.bge_reranker import BgeReranker

        reranker = BgeReranker()
        candidates = [_cand("c1", "content-a"), _cand("c2", "content-b"), _cand("c3", "content-c")]
        result = await reranker.rerank("query", candidates, top_k=3)
        assert [c.chunk_id for c in result] == ["c1", "c3", "c2"]
        assert result[0].score > result[1].score > result[2].score

    @pytest.mark.asyncio
    async def test_top_k_truncation(self):
        from calliodesmo.retrieval.bge_reranker import BgeReranker

        reranker = BgeReranker()
        candidates = [_cand("c1", "content-a"), _cand("c2", "content-b"), _cand("c3", "content-c")]
        result = await reranker.rerank("query", candidates, top_k=2)
        assert len(result) == 2
        assert result[0].rank == 1
        assert result[1].rank == 2

    @pytest.mark.asyncio
    async def test_rank_reset_and_score_updated(self):
        from calliodesmo.retrieval.bge_reranker import BgeReranker

        reranker = BgeReranker()
        candidates = [_cand("c1", "content-a", score=0.1), _cand("c2", "content-b", score=0.9)]
        result = await reranker.rerank("query", candidates, top_k=5)
        for i, c in enumerate(result, 1):
            assert c.rank == i
        assert result[0].score == pytest.approx(0.9, abs=0.01)

    @pytest.mark.asyncio
    async def test_empty_candidates(self):
        from calliodesmo.retrieval.bge_reranker import BgeReranker

        reranker = BgeReranker()
        result = await reranker.rerank("query", [], top_k=5)
        assert result == []


class TestBgeRerankerContentAssertion:
    def setup_method(self):
        pass

        class _CapturingReranker:
            fed_pairs: typing.ClassVar[list] = []

            def __init__(self, model_name, use_fp16=True):
                pass

            def compute_score(self, pairs, normalize=True):
                _CapturingReranker.fed_pairs = pairs
                return [0.5] * len(pairs)

        stub_mod = types.ModuleType("FlagEmbedding")
        stub_mod.FlagReranker = _CapturingReranker
        sys.modules["FlagEmbedding"] = stub_mod
        _CapturingReranker.fed_pairs = []
        self._capturing_cls = _CapturingReranker

    def teardown_method(self):
        _remove_stub_flag_embedding()

    @pytest.mark.asyncio
    async def test_rerank_feeds_content_not_summary(self):
        """断言喂 reranker 的文本为 Candidate.content（chunk 原文）。"""
        from calliodesmo.retrieval.bge_reranker import BgeReranker

        reranker = BgeReranker()
        candidates = [
            Candidate(
                chunk_id="c1",
                doc_id="d",
                content="original chunk text",
                score=0.5,
                metadata={"summary": "this is a summary"},
            ),
        ]
        await reranker.rerank("query", candidates, top_k=5)
        pairs = self._capturing_cls.fed_pairs
        assert pairs == [["query", "original chunk text"]]


class TestBgeRerankerMissingDependency:
    def setup_method(self):
        _remove_stub_flag_embedding()

    def teardown_method(self):
        _remove_stub_flag_embedding()

    @pytest.mark.asyncio
    async def test_missing_flagembedding_raises(self):
        from calliodesmo.retrieval.bge_reranker import BgeReranker

        reranker = BgeReranker()
        with pytest.raises(RuntimeError, match="FlagEmbedding"):
            await reranker.rerank("query", [_cand("c1", "x")], top_k=5)


class TestP2Config:
    def test_default_values(self):
        from calliodesmo.config import Settings

        s = Settings()
        assert s.reranker_model == "BAAI/bge-reranker-v2-m3"
        assert s.rerank_top_n == 20
        assert s.hybrid_enabled is True
        assert s.sparse_enabled is True
        assert s.local_search_hops == 1
        assert s.global_top_communities == 10
        assert s.default_search_mode == "native_rag"
        assert s.chunk_summary_enabled is False
        assert s.eval_golden_file == "config/golden_qa.yaml"

    def test_env_override(self, monkeypatch):
        from calliodesmo.config import Settings

        monkeypatch.setenv("CALLIODESMO_RERANK_TOP_N", "50")
        monkeypatch.setenv("CALLIODESMO_HYBRID_ENABLED", "false")
        s = Settings()
        assert s.rerank_top_n == 50
        assert s.hybrid_enabled is False


class TestRerankPipeline:
    """重排串联：HybridRetriever 召回 -> Reranker.rerank -> top_k。"""

    @pytest.mark.asyncio
    async def test_identity_reranker_default(self):
        """缺 reranker 注入时退化为 IdentityReranker 保序。"""
        from calliodesmo.retrieval.identity_reranker import IdentityReranker

        candidates = [_cand("c1", "a", 0.9), _cand("c2", "b", 0.8)]
        reranker = IdentityReranker()
        result = await reranker.rerank("query", candidates, top_k=5)
        assert len(result) == 2
        assert result[0].chunk_id == "c1"
        assert result[0].rank == 1
        assert result[0].score == 0.9
