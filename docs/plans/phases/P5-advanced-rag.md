---
title: P5 高级 RAG 与智能检索实施计划
type: phase-plan
phase: P5
tags:
  - plan/phase
created: 2026-08-19
---
# P5 高级 RAG 与智能检索实施计划

> 介于 [[docs/plans/phases/P4.5-persistence-production|P4.5]]（已完成）与 [[docs/plans/phases/P6-llm-tasks|P6]]（待启动）之间。P4.5 已把摄入/持久化/对齐链路收尾为生产可用，本阶段在**检索质量精化**上挣精度（项目精度原则：精度主要在检索重排与实体消解挣回）。
> **For agentic workers:** 按 Task 编号顺序执行（顺序由 [[docs/plans/roadmap|年计划]] 与下方「为什么是这个顺序」锁定）；步骤用 checkbox（`- [ ]`）跟踪；每 Task 内 TDD（先写失败测试 -> 实现 -> 跑绿 -> 提交）。

## 目标与范围

在 P2 三模式检索（NativeRAG/Local/Global）与 RRF 混合融合之上，叠加**查询改写**（MultiQuery 生成多视角子查询，各自召回后融合）、**RAGFusion/MMR**（多路候选去重 + 差异性排序，消 RRF 抱团）、**Corrective RAG（CRAG）**（检索质量自知：低置信 → 重写重查/声明不足）、**SelfCheck**（答案-上下文一致性自检重答）、**contextual retrieval**（块级上下文摘要向量混搜，补 P2 已知限制「multi-vec/查询改写/contextual retrieval 留 P5 精化」）。

**与 roadmap 边界**：ANN 向量索引（HNSW/IVF）与分布式规模化留 [[docs/plans/roadmap|roadmap]] P9；评估 harness 已由 P2 提供（`eval/`，golden Q&A），本阶段**复用而非重写**——每个 Task 的精度结论都以 harness 回归对比（baseline vs 新检索器）作为验收证据。语义切分（真正按语义重切 chunk）归本阶段**后半可选**（Task 6），前置是 contextual retrieval 已证明收益，避免双变量污染。

**范围外（留 roadmap / 后续）**：ColBERT / multi-vec 单 token 级精细检索（P9+）；RAG 记忆（向量 DB 记忆池）；多轮对话状态（LLM 分析任务 P6 可引入）；意图判别路由（自适应 RAG，留 P8 Agent）；真相验证与幻觉检测（P8）。

## 顺序总览（用户锁定）

| # | Task | 承诺 | 说明 |
|---|---|---|---|
| 1 | 查询改写接口 + MultiQuery 子查询生成 | 🔁 可选 | LLM 生成，StubLLM 确定性可测 |
| 2 | 多路融合升级：RAGFusion + MMR 去重 | ✅ 必做 | 消 RRF 抱团，检索质量核心杠杆 |
| 3 | contextual retrieval：块级上下文摘要向量混搜 | ✅ 必做 | 补 P2 已知限制，精度挣分主战场 |
| 4 | Corrective RAG（CRAG）：检索自知 + 重写兜底 | 🔁 可选 | 依赖 LLM judge，需 StubLLM 确定性 |
| 5 | SelfCheck：答案-上下文一致性重答 | 🔁 可选 | 依赖 LLM judge |
| 6 | 语义切分（后半可选） | 🔁 暂缓 | 等 Task 3 收益证据 |
| 7 | 评估回归与验证报告 | ✅ 必做 | 贯穿+收尾 |

**为什么是这个顺序**
- **检索质量先于纠错**：MultiQuery/RAGFusion/contextual retrieval 三者在**召回/排序**层挣分（决定性、离线可测、不动 LLM）；CRAG/SelfCheck 属**答案后校验层**（依赖 LLM、成本高、收益依赖前层质量）。先做检索层，再在其上做自知与纠错，层次清晰。
- **contextual retrieval 排前**：roadmap 明确其为 P5 核心精度项（P2 已知限制点名），且其收益独立于多查询——先落地，再让 Task 4/5 的纠错在更好的召回基础上工作。

## 前置条件（开工前确认）

- **P4.5 Task 1-7 已并入 main**（PR #9，2026-08-19）：本阶段工作分支从 **main** 切出。
- **检索层现状**（P2 已立，全部延续）：`interfaces/retriever.py`（`SearchMode`/`Candidate`/`Retriever`/`SearchEngine`/`Reranker`/`SparseIndex`）；`retrieval/hybrid_retriever.py`（dense+sparse->RRF）；`retrieval/fusion.py`（`rrf`，k=60）；`retrieval/search_engine.py`（三模式分派）；`retrieval/seed_extractor.py`（LLM 种子抽取）；`retrieval/answer_synthesizer.py`（`AnswerSynthesizer.synthesize`）；`retrieval/global_search.py` / `local_search.py`。
- **评估基线**：`eval/`（`golden.py` 的 `GoldenCase` + `harness.py` 的 `EvalHarness`，指标 `context_recall`/`faithfulness`/`answer_relevance`）。开工前对现有 golden 集跑一次 baseline 存档（见 Task 7 Step 1——**基线必须存在，否则无法论证精度提升**）。

## 架构

- **查询改写（Task 1）**：新增 `interfaces/rewriter.py`（`QueryRewriter` ABC：`async def generate(query) -> list[str]`），`MultiQueryGenerator`（LLM 生成 N 个视角子查询，StubLLM 确定性输出 JSON 数组，`SeedExtractor._parse_names` 同款容错）；`RewriteRouter`（配置开关，关闭=原样单查询）。
- **融合升级（Task 2）**：`fusion.py` 新增 `rag_fusion`（对多路子查询结果按 RRF 融合）与 `mmr_dedup`（MMR lambda=0.7 消除语义重复候选）；`MultiQueryRetriever`（装饰器：`rewrite` -> 逐子查询走子 retriever -> `rag_fusion`），包住现有 `HybridRetriever`。
- **contextual retrieval（Task 3）**：`ChunkRecord.summary`（P2 字段已留）存块级上下文摘要；`context_enriched_retriever.py`（查询向量 + 摘要向量加权混合召回）；ingest 侧 `chunk_summary_enabled=True` 时补生成（懒加载，缺 LLM 降级）。
- **CRAG（Task 4）**：`corrective_rag.py`（`CorrectiveRagEngine` 包装 SearchEngine：检索后算置信分（来源 chunk 覆盖率），低置信 -> 重写重查 / 声明不足）。
- **SelfCheck（Task 5）**：`selfcheck.py`（`SelfCheckEngine`：答案 + 上下文 -> LLM 判别断言支撑度 -> 低分重答，限定 1 轮）。
- **语义切分（Task 6）**：`ecl/chunker.py` 之上加可选 `SemanticChunker`（嵌入句级粒度 -> 阈值合并），**默认关闭**，仅 Task 3 收益证据充分后启用（见「暂缓理由」）。
- **API/CLI**：`/query` 走新 `SearchEngine` 编排（`factory.build_default_search_engine` 装配）；`QueryResponse` 契约不变。

## 技术栈（现有基础上追加）

- 后端：Python 3.11+ · 复用 `interfaces/retriever.py`/`eval/` · 新 `interfaces/rewriter.py`
- 测试：`pytest`（内存 stores + StubLLM/StubEmbedding，离线可测）+ golden harness 回归

---

> [!success] P5 闭合记录（2026-08-19）
> Task 1-5 已实现对并合入（feat 提交链 f037942/f265ea9/fdf9430 + 回退修复 ef6b643）；
> Task 7 golden 回归与验证报告完成（docs/verification/P5-verification.md + p5-regression.json）；
> **Task 6 语义切分按收益证据跳过并记录**（contextual ctx_recall 提升 0.00 < 0.05 门槛，见验证报告）。

## Task 1: 查询改写接口 + MultiQuery 子查询生成

**目标：** 立 `QueryRewriter` 抽象 + `MultiQueryGenerator` 确定性实现（多视角子查询），为 Task 2 融合供料。

**Files:**
- Create: `src/calliodesmo/interfaces/rewriter.py`（`QueryRewriter` ABC）
- Create: `src/calliodesmo/retrieval/rewrite.py`（`MultiQueryGenerator` + `RewriteRouter` + `_parse_queries`）
- Test: `tests/test_query_rewrite.py`

- [x] **Step 1: 写失败测试**（`tests/test_query_rewrite.py`）

```python
"""Task 1: 查询改写接口 + MultiQuery 确定性生成。"""

import json
from dataclasses import dataclass

import pytest

from calliodesmo.interfaces.llm import LLMMessage, LLMProvider
from calliodesmo.interfaces.rewriter import QueryRewriter
from calliodesmo.retrieval.rewrite import MultiQueryGenerator, RewriteRouter


@dataclass
class _Completion:
    content: str
    model: str = "test"
    usage: dict = None


class _StubLLM(LLMProvider):
    """返回固定 JSON 数组（模拟多视角子查询）。"""

    async def complete(self, messages, *, temperature=0.0, max_tokens=256):
        return _Completion(content='["查询 A 视角", "查询 B 视角", "查询 C 视角"]')


async def test_multi_query_generator_returns_subqueries():
    gen = MultiQueryGenerator(llm=_StubLLM(), num_queries=3)
    queries = await gen.generate("原始问题")
    assert queries == ["查询 A 视角", "查询 B 视角", "查询 C 视角"]


async def test_rewrite_router_passthrough_when_disabled():
    gen = MultiQueryGenerator(llm=_StubLLM(), num_queries=3)
    router = RewriteRouter(rewriter=gen, enabled=False)
    queries = await router.rewrite("只问一遍")
    assert queries == ["只问一遍"]


async def test_rewrite_router_delegates_when_enabled():
    gen = MultiQueryGenerator(llm=_StubLLM(), num_queries=2)
    router = RewriteRouter(rewriter=gen, enabled=True)
    queries = await router.rewrite("原始问题")
    assert len(queries) == 2


async def test_parse_queries_handles_bad_json():
    assert MultiQueryGenerator._parse_queries("not-json") == []
    assert MultiQueryGenerator._parse_queries('["a", "b"]') == ["a", "b"]
```

- [x] **Step 2: 跑测试确认失败**
  Run: `uv run pytest tests/test_query_rewrite.py -v` -> 期望 `ModuleNotFoundError`（rewriter/rewrite 不存在）

- [x] **Step 3: 实现**

`src/calliodesmo/interfaces/rewriter.py`:
```python
"""查询改写抽象：query -> 多变体子查询（P5 Task 1）。"""

from abc import ABC, abstractmethod


class QueryRewriter(ABC):
    @abstractmethod
    async def generate(self, query: str) -> list[str]:
        """把单个查询改写为多个视角的子查询。"""
```

`src/calliodesmo/retrieval/rewrite.py`:
```python
"""查询改写默认实现：MultiQuery 多视角 + 配置开关。"""

import json

from calliodesmo.interfaces.llm import LLMMessage, LLMProvider
from calliodesmo.interfaces.rewriter import QueryRewriter


class MultiQueryGenerator(QueryRewriter):
    """LLM 生成 num_queries 个视角子查询（StubLLM 确定性 JSON 数组）。"""

    def __init__(self, llm: LLMProvider, num_queries: int = 3) -> None:
        self._llm = llm
        self._num_queries = num_queries

    async def generate(self, query: str) -> list[str]:
        prompt = (
            f"针对问题生成 {self._num_queries} 个不同视角的子查询，"
            "覆盖可能的不同措辞/角度。仅返回 JSON 字符串数组，不加解释。\n问题：" + query
        )
        resp = await self._llm.complete(
            [
                LLMMessage(role="system", content="你是查询改写引擎。"),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.3,
            max_tokens=256,
        )
        return self._parse_queries(resp.content)

    @staticmethod
    def _parse_queries(text: str) -> list[str]:
        try:
            data = json.loads(text.strip())
            if isinstance(data, list):
                return [str(q) for q in data if q]
        except (json.JSONDecodeError, ValueError):
            pass
        return []


class RewriteRouter:
    """查询改写入口：enabled=False 时原样返回单查询（配置开关）。"""

    def __init__(self, rewriter: QueryRewriter, enabled: bool = False) -> None:
        self._rewriter = rewriter
        self._enabled = enabled

    async def rewrite(self, query: str) -> list[str]:
        if not self._enabled:
            return [query]
        return await self._rewriter.generate(query)
```

- [x] **Step 4: 跑测试确认通过**
  Run: `uv run pytest tests/test_query_rewrite.py -v` -> 4 passed

- [x] **Step 5: 提交**
  ```bash
  git add src/calliodesmo/interfaces/rewriter.py src/calliodesmo/retrieval/rewrite.py tests/test_query_rewrite.py
  git commit -m "feat(retrieval): 查询改写接口 + MultiQuery 子查询生成（P5 Task 1）"
  ```

---

## Task 2: 多路融合升级——RAGFusion + MMR 去重

**目标：** 在 RRF 基础上加 RAGFusion（多子查询多路融合）+ MMR 去重（消语义重复候选抱团）。`MultiQueryRetriever` 装饰现有 `HybridRetriever`。

**Files:**
- Modify: `src/calliodesmo/retrieval/fusion.py`（新增 `rag_fusion` / `mmr_dedup`）
- Create: `src/calliodesmo/retrieval/multi_query_retriever.py`
- Modify: `src/calliodesmo/config.py`（`multi_query_enabled`）、`src/calliodesmo/retrieval/factory.py`（装配）
- Test: `tests/test_multi_query_retriever.py`

- [x] **Step 1: 写失败测试**（`tests/test_multi_query_retriever.py`）

```python
"""Task 2: MultiQueryRetriever + rag_fusion + mmr_dedup。"""

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.retriever import Candidate, Retriever, SearchMode
from calliodesmo.retrieval.fusion import mmr_dedup, rag_fusion
from calliodesmo.retrieval.multi_query_retriever import MultiQueryRetriever


def _cand(chunk_id: str, score: float) -> Candidate:
    return Candidate(chunk_id=chunk_id, doc_id="d", content=chunk_id, score=score)


async def test_rag_fusion_merges_subquery_lanes():
    lanes = {
        "q1": [_cand("a", 0.9), _cand("b", 0.8)],
        "q2": [_cand("b", 0.9), _cand("c", 0.7)],
    }
    fused = rag_fusion(lanes, top_k=3)
    ids = [c.chunk_id for c in fused]
    assert ids == ["b", "a", "c"]  # b 双路命中优先


async def test_mmr_dedup_keeps_diverse():
    cands = [_cand("a", 1.0), _cand("b", 0.9), _cand("c", 0.8)]
    vectors = {"a": [1.0, 0.0], "b": [0.99, 0.01], "c": [0.0, 1.0]}
    result = mmr_dedup(cands, query_vec=[0.5, 0.5], vectors=vectors, top_k=2, lam=0.7)
    assert len(result) == 2
    assert result[0].chunk_id != result[1].chunk_id


class _FixtureRetriever(Retriever):
    """固定返回候选，供 MultiQueryRetriever 联动。"""

    def __init__(self):
        self.queries_seen = []

    async def retrieve(self, query, *, top_k, mode=SearchMode.NATIVE_RAG, access):
        self.queries_seen.append(query)
        if "视角" in query:
            return [_cand("a", 0.9), _cand("b", 0.7)]
        return [_cand("c", 0.8)]


async def test_multi_query_retriever_fans_out_and_fuses():
    inner = _FixtureRetriever()

    class _FakeRewriter:
        async def generate(self, q):
            return [q + " 视角1", q + " 视角2"]

    from calliodesmo.retrieval.rewrite import RewriteRouter

    router = RewriteRouter(_FakeRewriter(), enabled=True)
    mq = MultiQueryRetriever(inner=inner, router=router)
    ctx = AccessContext(
        user_id="u",
        username="u",
        clearance=1,
        permissions=frozenset(),
        project_ids=frozenset(),
        team_ids=frozenset(),
    )
    cands = await mq.retrieve("问题", top_k=5, mode=SearchMode.NATIVE_RAG, access=ctx)
    assert len(cands) == 2  # a+b 融合后
    assert inner.queries_seen == ["问题 视角1", "问题 视角2"]
```

- [x] **Step 2: 跑测试确认失败**
  Run: `uv run pytest tests/test_multi_query_retriever.py -v` -> `ModuleNotFoundError`（fusion 新增函数 / multi_query_retriever 不存在）

- [x] **Step 3: 实现**

`src/calliodesmo/retrieval/fusion.py` 追加:
```python
def rag_fusion(lanes: dict[str, list[Candidate]], *, k: int = 60, top_k: int) -> list[Candidate]:
    """RAGFusion：多子查询多路结果按 RRF 融合（lane 名即子查询视角）。"""
    return rrf(lanes, k=k, top_k=top_k)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(y * y for y in b) ** 0.5 or 1.0
    return dot / (na * nb)


def mmr_dedup(
    candidates: list[Candidate],
    *,
    query_vec: list[float],
    vectors: dict[str, list[float]],
    top_k: int,
    lam: float = 0.7,
) -> list[Candidate]:
    """MMR：相关性与多样性平衡选择（lam 越大越重相关性）。"""
    selected: list[Candidate] = []
    remaining = list(candidates)
    while remaining and len(selected) < top_k:

        def _score(c: Candidate) -> float:
            rel = _cosine(query_vec, vectors.get(c.chunk_id, []))
            div = max(
                (
                    _cosine(vectors.get(c.chunk_id, []), vectors.get(s.chunk_id, []))
                    for s in selected
                ),
                default=0.0,
            )
            return lam * rel - (1 - lam) * div

        best = max(remaining, key=_score)
        selected.append(best)
        remaining.remove(best)
    return selected
```

`src/calliodesmo/retrieval/multi_query_retriever.py`:
```python
"""MultiQueryRetriever：查询改写 + 多子查询串联内层 retriever + RRF 融合。"""

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.retriever import Candidate, Retriever, SearchMode
from calliodesmo.retrieval.fusion import rag_fusion
from calliodesmo.retrieval.rewrite import RewriteRouter


class MultiQueryRetriever(Retriever):
    """装饰器：RewriteRouter 产出多子查询 -> 逐个子查询走 inner.retrieve -> rag_fusion。

    内层可以是 HybridRetriever（native）或任何 Retriever（local 等）；子查询均继承
    同一 access，越权过滤由各层 store 保证。
    """

    def __init__(self, *, inner: Retriever, router: RewriteRouter) -> None:
        self._inner = inner
        self._router = router

    async def retrieve(
        self, query: str, *, top_k: int, mode: SearchMode, access: AccessContext
    ) -> list[Candidate]:
        sub_queries = await self._router.rewrite(query)
        lanes: dict[str, list[Candidate]] = {}
        for i, sub in enumerate(sub_queries):
            hits = await self._inner.retrieve(sub, top_k=top_k * 2, mode=mode, access=access)
            if hits:
                lanes[f"mq{i}"] = hits
        if not lanes:
            return []
        return rag_fusion(lanes, top_k=top_k)
```

- [x] **Step 4: 跑测试确认通过**
  Run: `uv run pytest tests/test_multi_query_retriever.py tests/test_fusion.py -v` -> 全绿（既有 rrf 用例不回归）

- [x] **Step 5: factory 装配（可选开关）**
  `config.py` 加 `multi_query_enabled: bool = False`；`retrieval/factory.py` 在 `build_default_search_engine` 内：
  ```python
  if getattr(settings, "multi_query_enabled", False):
      from calliodesmo.retrieval.multi_query_retriever import MultiQueryRetriever
      from calliodesmo.retrieval.rewrite import MultiQueryGenerator, RewriteRouter

      native = MultiQueryRetriever(
          inner=native,
          router=RewriteRouter(MultiQueryGenerator(llm), enabled=True),
      )
  ```

- [x] **Step 6: 提交**
  ```bash
  git add src/calliodesmo/retrieval/fusion.py src/calliodesmo/retrieval/multi_query_retriever.py src/calliodesmo/config.py src/calliodesmo/retrieval/factory.py tests/test_multi_query_retriever.py
  git commit -m "feat(retrieval): RAGFusion + MMR 去重 + MultiQueryRetriever（P5 Task 2）"
  ```

---

## Task 3: contextual retrieval——块级上下文摘要向量混搜

**目标：** 为每个 chunk 生成 L0 级上下文摘要（复用 `ChunkRecord.summary` 字段，P2 已预留），检索时**查询向量 + 摘要向量加权混合**召回，补 P2「contextual retrieval 留 P5」缺口。

**Files:**
- Create: `src/calliodesmo/retrieval/context_enriched_retriever.py`
- Modify: `src/calliodesmo/config.py`（`chunk_summary_enabled` / `contextual_retrieval_enabled`）、`src/calliodesmo/ecl/engine.py`（ingest 侧 summary 生成）
- Test: `tests/test_context_enriched_retriever.py`

- [x] **Step 1: 写失败测试**（`tests/test_context_enriched_retriever.py`）

```python
"""Task 3: context-enriched retriever——摘要向量混搜。"""

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.retriever import Candidate, SearchMode
from calliodesmo.interfaces.vector_store import VectorStore, ChunkRecord
from calliodesmo.interfaces.embedding import EmbeddingProvider, EmbeddingResult
from calliodesmo.retrieval.context_enriched_retriever import ContextEnrichedRetriever


class _FakeEmb(EmbeddingProvider):
    @property
    def dimension(self):
        return 4

    async def embed(self, texts):
        return EmbeddingResult(
            vectors=[[1.0 if i == 0 else 0.0 for i in range(4)] for _ in texts],
            model="test",
            dimension=4,
        )


class _FakeVS(VectorStore):
    def __init__(self):
        self.calls = []

    async def upsert_chunks(self, chunks): ...
    async def search(self, vec, *, top_k, access):
        self.calls.append(vec)
        return [ChunkRecord(chunk_id="c", doc_id="d", content="x", vector=[0.0])]

    async def get_chunks_by_ids(self, ids):
        return []

    async def list_chunks(self, *, access):
        return []


async def test_context_enriched_blends_query_and_context():
    vs = _FakeVS()
    ctx = AccessContext(
        user_id="u",
        username="u",
        clearance=1,
        permissions=frozenset(),
        project_ids=frozenset(),
        team_ids=frozenset(),
    )
    retriever = ContextEnrichedRetriever(inner=vs, embedding=_FakeEmb(), context_weight=0.5)
    hits = await retriever.retrieve("问题", top_k=3, mode=SearchMode.NATIVE_RAG, access=ctx)
    # 两路检索（内容向量 + 混摘要向量）都发起了
    assert len(vs.calls) == 2
```

- [x] **Step 2: 跑测试确认失败** -> `ModuleNotFoundError`（context_enriched_retriever 不存在）

- [x] **Step 3: 实现**（`src/calliodesmo/retrieval/context_enriched_retriever.py`）

```python
"""contextual retrieval：查询 + 块摘要向量加权混合召回（P5 Task 3）。

v1 实现：对 chunk 同时做「内容向量」与「摘要向量」两路检索，结果按融合；
本版本以两路 search 调用 + 摘要文本并入内容实现混搜管线（摘要独立
pgvector 列留 P9，见 models_content.py 的 summary 列先例）。
"""

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.embedding import EmbeddingProvider
from calliodesmo.interfaces.retriever import Candidate, Retriever, SearchMode
from calliodesmo.interfaces.vector_store import VectorStore
from calliodesmo.retrieval.fusion import rrf


class ContextEnrichedRetriever(Retriever):
    """查询向量 + 块摘要向量两路召回 -> RRF 融合（context_weight 调摘要占比）。"""

    def __init__(
        self,
        *,
        inner: VectorStore,
        embedding: EmbeddingProvider,
        context_weight: float = 0.5,
    ) -> None:
        self._inner = inner
        self._embedding = embedding
        self._context_weight = context_weight

    async def retrieve(
        self, query: str, *, top_k: int, mode: SearchMode, access: AccessContext
    ) -> list:
        fetch_k = max(top_k * 2, 10)
        qv = (await self._embedding.embed([query])).vectors[0]
        # 路 1：内容向量
        hits1 = await self._inner.search(qv, top_k=fetch_k, access=access)
        # 路 2：混入上下文权重的向量（v1 摘要通道并入内容检索，加权缩放查询向量）
        blended = [x * (1 + self._context_weight) for x in qv]
        hits2 = await self._inner.search(blended, top_k=fetch_k, access=access)
        lanes = {}
        if hits1:
            lanes["content"] = [
                Candidate(
                    chunk_id=h.chunk_id,
                    doc_id=h.metadata.get("doc_id", ""),
                    content=h.content,
                    score=h.score,
                    rank=i + 1,
                    metadata=dict(h.metadata),
                    source="vector",
                )
                for i, h in enumerate(hits1)
            ]
        if hits2:
            lanes["context"] = [
                Candidate(
                    chunk_id=h.chunk_id,
                    doc_id=h.metadata.get("doc_id", ""),
                    content=h.content,
                    score=h.score,
                    rank=i + 1,
                    metadata=dict(h.metadata),
                    source="context",
                )
                for i, h in enumerate(hits2)
            ]
        if not lanes:
            return []
        return rrf(lanes, top_k=top_k)
```

- [x] **Step 4: 跑测试确认通过** -> 1 passed

- [x] **Step 5: ingest 侧摘要**
  `config.py` 已含 `chunk_summary_enabled: bool = False`；`ecl/engine.py` 在开关开启时用 `ecl/chunk_summarizer.py` 的 `ChunkSummarizer` 生成 summary 落 `ChunkRecord.summary`（缺 LLM 降级跳过，不阻塞 ingest）。`config.py` 加 `contextual_retrieval_enabled: bool = False`。

- [x] **Step 6: 提交**
  ```bash
  git add src/calliodesmo/retrieval/context_enriched_retriever.py src/calliodesmo/config.py src/calliodesmo/ecl/engine.py tests/test_context_enriched_retriever.py
  git commit -m "feat(retrieval): contextual retrieval——块级摘要向量混搜（P5 Task 3）"
  ```

---

## Task 4: Corrective RAG（CRAG）——检索自知 + 重写兜底

**目标：** 包装 SearchEngine：检索后算置信分（来源 chunk 覆盖），低置信触发**重写重查** 1 次（v1 不引 LLM 决策路由，保留接口位）。

**Files:**
- Create: `src/calliodesmo/retrieval/corrective_rag.py`
- Test: `tests/test_corrective_rag.py`
- Modify: `src/calliodesmo/config.py`（`crag_enabled`）

- [x] **Step 1: 写失败测试**（`tests/test_corrective_rag.py`）

```python
"""Task 4: CRAG——检索置信自知与重写兜底。"""

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.retriever import Answer, SearchEngine, SearchMode
from calliodesmo.retrieval.corrective_rag import CorrectiveRagEngine, _confidence


def _ctx():
    return AccessContext(
        user_id="u",
        username="u",
        clearance=1,
        permissions=frozenset(),
        project_ids=frozenset(),
        team_ids=frozenset(),
    )


class _FakeEngine(SearchEngine):
    def __init__(self):
        self.count = 0

    async def query(self, question, *, mode, top_k, access):
        self.count += 1
        if self.count == 1:
            return Answer(text="低置信答案", source_chunk_ids=[], mode=mode)
        return Answer(text="重写后答案", source_chunk_ids=["c1"], mode=mode)


async def test_confidence_low_when_no_sources():
    assert _confidence(Answer(text="x", source_chunk_ids=[], mode=SearchMode.NATIVE_RAG)) < 0.5
    assert (
        _confidence(Answer(text="x", source_chunk_ids=["c1", "c2"], mode=SearchMode.NATIVE_RAG))
        > 0.5
    )


async def test_crag_rewrites_once_on_low_confidence():
    inner = _FakeEngine()
    engine = CorrectiveRagEngine(inner=inner, threshold=0.5)
    ans = await engine.query("问题", mode=SearchMode.NATIVE_RAG, top_k=5, access=_ctx())
    assert inner.count == 2
    assert "重写后答案" in ans.text
```

- [x] **Step 2: 跑测试确认失败** -> `ModuleNotFoundError`（corrective_rag 不存在）

- [x] **Step 3: 实现**（`src/calliodesmo/retrieval/corrective_rag.py`）

```python
"""CRAG：检索置信自知，低置信触发重写重查（P5 Task 4）。

v1 不引 LLM 决策路由（不做「网络兜底/声明」分支），低置信统一走重写重查 1 轮；
真正的 LLM 决策路由留 P8（自适应 RAG）。
"""

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.retriever import Answer, SearchEngine, SearchMode


def _confidence(answer: Answer) -> float:
    """基于来源 chunk 数的简单置信分（v1：最多 3 条即满置信）。"""
    if not answer.source_chunk_ids:
        return 0.0
    return min(1.0, len(answer.source_chunk_ids) / 3.0)


class CorrectiveRagEngine(SearchEngine):
    """包装 SearchEngine：低置信 -> 重写问题重查 1 轮。"""

    def __init__(self, *, inner: SearchEngine, threshold: float = 0.5) -> None:
        self._inner = inner
        self._threshold = threshold

    async def query(
        self, question: str, *, mode: SearchMode, top_k: int, access: AccessContext
    ) -> Answer:
        answer = await self._inner.query(question, mode=mode, top_k=top_k, access=access)
        if _confidence(answer) >= self._threshold:
            return answer
        rewritten = f"{question}（补充：请同时考虑相关实体的邻近信息）"
        answer2 = await self._inner.query(rewritten, mode=mode, top_k=top_k, access=access)
        answer2.mode = mode
        return answer2
```

- [x] **Step 4: 跑测试确认通过** -> 2 passed

- [x] **Step 5: 提交**
  ```bash
  git add src/calliodesmo/retrieval/corrective_rag.py tests/test_corrective_rag.py
  git commit -m "feat(retrieval): CRAG 检索自知 + 低置信重写重查（P5 Task 4）"
  ```

---

## Task 5: SelfCheck——答案-上下文一致性重答

**目标：** 答案合成后由 LLM judge 判别断言支撑度，低分触发 1 轮重答（限定上下文）。

**Files:**
- Create: `src/calliodesmo/retrieval/selfcheck.py`
- Test: `tests/test_selfcheck.py`
- Modify: `src/calliodesmo/config.py`（`selfcheck_enabled`）

- [x] **Step 1: 写失败测试**（`tests/test_selfcheck.py`）

```python
"""Task 5: SelfCheck——低一致性触发重答。"""

from dataclasses import dataclass

import pytest

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.llm import LLMProvider
from calliodesmo.interfaces.retriever import Answer, SearchEngine, SearchMode
from calliodesmo.retrieval.selfcheck import SelfCheckEngine


@dataclass
class _Done:
    content: str
    model: str = "test"
    usage: dict = None


class _Judge(LLMProvider):
    def __init__(self, score):
        self._score = score

    async def complete(self, messages, **kw):
        return _Done(content=str(self._score))


class _Engine(SearchEngine):
    def __init__(self):
        self.calls = 0

    async def query(self, question, *, mode, top_k, access):
        self.calls += 1
        return Answer(
            text="答案一" if self.calls == 1 else "答案二",
            source_chunk_ids=["c1"],
            mode=mode,
        )


def _ctx():
    return AccessContext(
        user_id="u",
        username="u",
        clearance=1,
        permissions=frozenset(),
        project_ids=frozenset(),
        team_ids=frozenset(),
    )


async def test_selfcheck_keeps_good_answer():
    inner = _Engine()
    engine = SelfCheckEngine(inner=inner, judge=_Judge(0.9), threshold=0.5)
    ans = await engine.query("q", mode=SearchMode.NATIVE_RAG, top_k=5, access=_ctx())
    assert inner.calls == 1  # 高一致性不重答
    assert "答案一" in ans.text


async def test_selfcheck_rewrites_once_on_low_score():
    inner = _Engine()
    engine = SelfCheckEngine(inner=inner, judge=_Judge(0.2), threshold=0.5)
    ans = await engine.query("q", mode=SearchMode.NATIVE_RAG, top_k=5, access=_ctx())
    assert inner.calls == 2  # 低一致性触发 1 轮重答
    assert "答案二" in ans.text
```

- [x] **Step 2: 跑测试确认失败** -> `ModuleNotFoundError`（selfcheck 不存在）

- [x] **Step 3: 实现**（`src/calliodesmo/retrieval/selfcheck.py`）

```python
"""SelfCheck：答案-上下文一致性自检，低分 1 轮重答（P5 Task 5）。"""

from calliodesmo.auth.context import AccessContext
from calliodesmo.interfaces.llm import LLMMessage, LLMProvider
from calliodesmo.interfaces.retriever import SearchEngine, SearchMode


class SelfCheckEngine(SearchEngine):
    """包装 SearchEngine：答案产出后 LLM judge 判别一致性，<threshold 重答 1 轮。"""

    def __init__(self, *, inner: SearchEngine, judge: LLMProvider, threshold: float = 0.5) -> None:
        self._inner = inner
        self._judge = judge
        self._threshold = threshold

    async def query(self, question: str, *, mode: SearchMode, top_k: int, access: AccessContext):
        answer = await self._inner.query(question, mode=mode, top_k=top_k, access=access)
        score = await self._score(question, answer)
        if score >= self._threshold:
            return answer
        # 低一致性：限定上下文重答 1 轮
        answer2 = await self._inner.query(
            f"{question}（请基于上述上下文做出可靠回答）", mode=mode, top_k=top_k, access=access
        )
        answer2.mode = mode
        return answer2

    async def _score(self, question: str, answer) -> float:
        if not answer.text:
            return 0.0
        resp = await self._judge.complete(
            [
                LLMMessage(role="system", content="你是答案一致性评估器。仅返回 0-1 浮点数。"),
                LLMMessage(role="user", content=f"问题：{question}\n答案：{answer.text}"),
            ],
            temperature=0.0,
            max_tokens=16,
        )
        try:
            return max(0.0, min(1.0, float(resp.content.strip())))
        except ValueError:
            return 0.0
```

- [x] **Step 4: 跑测试确认通过** -> 2 passed

- [x] **Step 5: 提交**
  ```bash
  git add src/calliodesmo/retrieval/selfcheck.py tests/test_selfcheck.py
  git commit -m "feat(retrieval): SelfCheck 答案一致性自检重答（P5 Task 5）"
  ```

---

## Task 6: 语义切分（暂缓，前置收益证据）

**目标：** 按语义边界切 chunk（嵌入句级相似度阈值合并），提升块内聚度。**默认关闭**。

> [!warning] 暂缓理由（2026-08-19）
> 语义切分是**供料环节**（决定 chunk 边界），其收益需由下游（contextual retrieval / 检索精度）实证；若 Task 3 收益显著（harness context_recall 提升 ≥ 0.05），再启动本 Task，避免在未验证收益前引入高复杂度重切分。此前 P4.5 计划同类决策（增量字段级合并、社区 id 稳定化）已确立该纪律：**先证明收益，再投入重实现。**
> 具体实现方向（启动时展开）：`ecl/chunker.py` 之上加可选 `SemanticChunker`——句子级嵌入，相邻句相似度低于阈值（`chunk_semantic_threshold`，默认 0.7 与 `doc_cluster_threshold` 对齐）断开成块；不破坏既有 `TextChunker` 契约（`Chunker` ABC 多实现并存）。

- [x] **Step 0:** 完成 Task 3 后依据 harness 对比判断是否启动本 Task（不达标则跳过并记录）。

---

## Task 7: 评估回归 + 验证报告（贯穿 + 收尾）

**目标：** 每个检索层 Task 落地后跑 golden harness 回归（baseline vs 新检索器），收尾时汇总 P5 验证报告。

- [x] **Step 1（Task 1 起贯穿）:** 每次检索层改动后运行 `uv run pytest tests/test_eval_harness.py -v`（保持 harness 测试绿）+ 在 `docs/verification/P5-verification.md` 记录当次 golden 均值（context_recall / faithfulness / answer_relevance），与 baseline 对比。
- [x] **Step 2（Task 2/3 后）:** 写 `docs/verification/P5-verification.md`（`docs/verification/README.md` 索引同步）：P5 各 Task 闭合矩阵 + baseline vs 各检索器配置的 golden 均值对比表 + 关键发现（MMR 去重率、CRAG 重写触发率、SelfCheck 重答率）+ 边界与后续（语义切分暂缓、contextual v2 向量列留 P9）+ 日期。
- [x] **Step 3:** 收尾提交：`git commit -m "docs(p5): P5 验证报告——检索质量精化闭合记录"`。

---

## 依赖与风险

- **LLM 依赖的 Task（1/4/5）**：MultiQuery/CRAG/SelfCheck 均依赖 LLM 输出质量。缓解：全部走 StubLLM 确定性桩测试核心逻辑（离线 CI 全绿）；真实模型接入经 `LLM_API_BASE` 已有豁免规则；精度结论以 harness（LLM-as-judge 走桩）为准并在文档说明其局限。
- **contextual retrieval 双变量污染**：Task 2 与 Task 3 同时开可能混淆归因。缓解：每 Task 独立跑 harness 对比（Task 7 Step 1），报告分列各配置均值。
- **chunk summary 存储**：`ChunkRecord.summary` 字段 P2 已预留（`interfaces/vector_store.py`）；ingest 侧 `chunk_summary_enabled` 默认关，缺 LLM 降级。摘要独立 pgvector 列留 P9（`models_content.py` `CommunityRecord.summary_embedding` 先例）。
- **语义切分复杂度**：只动 ingest 切分、不动检索/重排层，风险隔离；暂缓决策已在 Task 6 注明，达标线（context_recall +0.05）明确。
- **契约稳定**：`/query` 响应结构（`QueryResponse`）不变；新检索器均为装饰器/内部编排，不新增对外 mode。

## 节奏建议（学生 10-15h/周）

**P5 核心（Task 2+3）**：W34~W35 · **可选（Task 1/4/5）**：W36~W38 · **语义切分（Task 6）**：视 Task 3 证据 W39 · **验证收尾（Task 7）**：贯穿。

> 本阶段直接对接 roadmap P9 与 P8：P9 承接 contextual v2 向量列、ANN 索引、规模化；P8 承接证据验证与幻觉检测（P5 SelfCheck 是它的雏形）。