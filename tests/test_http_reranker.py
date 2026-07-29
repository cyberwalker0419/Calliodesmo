"""HttpReranker：远端 /rerank 重排（离线 MockTransport，不触网）。"""

import json

import httpx

from calliodesmo.config import Settings
from calliodesmo.interfaces.retriever import Candidate
from calliodesmo.retrieval.http_reranker import HttpReranker


def _c(cid: str, content: str) -> Candidate:
    return Candidate(chunk_id=cid, doc_id="d", content=content, score=0.0)


def _mock(handler):
    return httpx.MockTransport(handler)


async def test_http_reranker_orders_by_relevance_desc():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.92},
                    {"index": 0, "relevance_score": 0.10},
                ]
            },
        )

    rr = HttpReranker("http://rerank-host:8083", transport=_mock(handler))
    out = await rr.rerank("张三是谁", [_c("c0", "李四在北京"), _c("c1", "张三是工程师")], top_k=10)
    assert [c.chunk_id for c in out] == ["c1", "c0"]
    assert out[0].rank == 1
    assert out[0].score == 0.92


async def test_http_reranker_top_k_truncation():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.1},
                ]
            },
        )

    rr = HttpReranker("http://x:8083", transport=_mock(handler))
    out = await rr.rerank("q", [_c("c0", "a"), _c("c1", "b")], top_k=1)
    assert [c.chunk_id for c in out] == ["c1"]


async def test_http_reranker_empty_candidates():
    rr = HttpReranker("http://x:8083", transport=_mock(lambda r: httpx.Response(200, json={})))
    out = await rr.rerank("q", [], top_k=10)
    assert out == []


async def test_http_reranker_posts_query_and_documents():
    captured = {}

    def handler(request):
        captured["payload"] = request.content.decode()
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.5}]})

    rr = HttpReranker("http://x:8083", model="bge-reranker-v2-m3", transport=_mock(handler))
    await rr.rerank("query", [_c("c0", "doc text")], top_k=5)
    payload = json.loads(captured["payload"])
    assert payload["query"] == "query"
    assert payload["documents"] == ["doc text"]
    assert payload["model"] == "bge-reranker-v2-m3"
    assert captured["url"].endswith("/rerank")


async def test_http_reranker_negative_logits_order():
    # llama.cpp 返回原始 logit（可为负），仍按降序
    def handler(request):
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": -0.37},
                    {"index": 1, "relevance_score": -0.59},
                ]
            },
        )

    rr = HttpReranker("http://x:8083", transport=_mock(handler))
    out = await rr.rerank("q", [_c("c0", "a"), _c("c1", "b")], top_k=10)
    assert [c.chunk_id for c in out] == ["c0", "c1"]  # -0.37 > -0.59


# --- build_reranker 路由（factory 按 reranker_provider 选择实现）---


def test_build_reranker_none_defaults_to_identity():
    from calliodesmo.retrieval.factory import build_reranker
    from calliodesmo.retrieval.identity_reranker import IdentityReranker

    assert isinstance(build_reranker(Settings(reranker_provider="none")), IdentityReranker)


def test_build_reranker_remote_returns_http_reranker():
    from calliodesmo.retrieval.factory import build_reranker
    from calliodesmo.retrieval.http_reranker import HttpReranker

    r = build_reranker(
        Settings(reranker_provider="remote", reranker_api_base="http://rerank-host:8083")
    )
    assert isinstance(r, HttpReranker)
    assert r._api_base == "http://rerank-host:8083"
