"""InMemoryBM25Index：零依赖内存 BM25 倒排索引，按 visible_to 过滤。

分词策略（中英兼容）：
- 英文：按空白/标点拆词，小写化
- 中文：按单字拆 + 相邻 bigram 兜底（覆盖未登录词）
- 数字/标点：作为分隔符

BM25 参数：k1=1.5, b=0.75（经典默认值），idf 使用 BM25+ 平滑避免负分。
"""

from __future__ import annotations

import math
import re

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.retriever import Candidate, SparseIndex
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.stores.visibility import visible_to

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_TOKEN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff\u3400-\u4dbf]")


def tokenize(text: str) -> list[str]:
    """中英兼容分词：英文按词、中文按字+bigram。"""
    lowered = text.lower()
    tokens: list[str] = []
    for m in _TOKEN.finditer(lowered):
        word = m.group()
        if _CJK.match(word):
            for ch in word:
                tokens.append(ch)
            for i in range(len(word) - 1):
                tokens.append(word[i : i + 2])
        else:
            tokens.append(word)
    return tokens


class InMemoryBM25Index(SparseIndex):
    """内存 BM25 倒排索引：确定性、零依赖、按 visible_to 过滤。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._docs: list[ChunkRecord] = []
        self._doc_tokens: list[list[str]] = []
        self._doc_freqs: list[dict[str, int]] = []
        self._avg_len: float = 0.0
        self._inverted: dict[str, list[int]] = {}  # term -> doc indices
        self._built = False

    async def index(self, chunks: list[ChunkRecord]) -> None:
        """构建倒排索引（替换旧索引）。"""
        self._docs = list(chunks)
        self._doc_tokens = [tokenize(c.content) for c in self._docs]
        self._doc_freqs = []
        self._inverted = {}
        for i, toks in enumerate(self._doc_tokens):
            freq: dict[str, int] = {}
            for t in toks:
                freq[t] = freq.get(t, 0) + 1
            self._doc_freqs.append(freq)
            for t in freq:
                self._inverted.setdefault(t, []).append(i)
        total_len = sum(len(t) for t in self._doc_tokens)
        self._avg_len = total_len / len(self._doc_tokens) if self._doc_tokens else 0.0
        self._built = True

    async def search(self, query: str, *, top_k: int, access: AccessContext) -> list[Candidate]:
        """BM25 检索：按分降序返回 Candidate（source="sparse"，rank 为 1-based）。"""
        if not self._built or not self._docs:
            return []
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        n = len(self._docs)
        scored: list[tuple[float, int]] = []
        for i, doc in enumerate(self._docs):
            if not visible_to(doc, access):
                continue
            score = self._bm25_score(q_tokens, i, n)
            if score > 0:
                scored.append((score, i))
        scored.sort(key=lambda x: (-x[0], self._docs[x[1]].chunk_id))
        result: list[Candidate] = []
        for rank, (score, idx) in enumerate(scored[:top_k], 1):
            doc = self._docs[idx]
            result.append(
                Candidate(
                    chunk_id=doc.chunk_id,
                    doc_id=doc.doc_id,
                    content=doc.content,
                    score=round(score, 6),
                    rank=rank,
                    metadata=dict(doc.metadata),
                    source="sparse",
                )
            )
        return result

    def _bm25_score(self, q_tokens: list[str], doc_idx: int, n: int) -> float:
        freq_map = self._doc_freqs[doc_idx]
        doc_len = len(self._doc_tokens[doc_idx])
        denom = doc_len + self._k1 * (1 - self._b + self._b * (doc_len / (self._avg_len or 1.0)))
        score = 0.0
        for term in q_tokens:
            if term not in freq_map:
                continue
            postings = self._inverted.get(term, [])
            df = len(postings)
            # BM25+ idf 平滑：避免 df=N 时 idf=0 或负值
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            tf = freq_map[term]
            score += idf * (tf * (self._k1 + 1)) / denom
        return score

    def __len__(self) -> int:
        return len(self._docs)
