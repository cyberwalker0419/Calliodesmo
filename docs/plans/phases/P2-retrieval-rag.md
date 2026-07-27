---
title: P2 基础检索与 RAG 实施计划
type: phase-plan
phase: P2
tags:
  - plan/phase
created: 2026-07-27
---
# P2 基础检索与 RAG 实施计划

> **For agentic workers:** 按 Task 顺序逐任务执行；步骤用 checkbox（`- [ ]`）跟踪。每个 Task 内按 TDD：先写失败测试 -> 实现 -> 跑绿 -> 提交。关联：[[docs/plans/roadmap|年计划]] / [[docs/plans/phases/P1-ecl-pipeline|P1]] / [[docs/plans/phases/P3-web-ui|P3]]。

**Goal:** 打通“能问能答”主链路。在 P1 落库的三层知识图谱之上，实现三种检索模式——**NativeRAG**（情景层：向量+稀疏混合，查原始文本块）、**LocalSearch**（语义层：图邻居，查实体-关系子图）、**GlobalSearch**（摘要层：社区摘要，查整体主题）。检索全程按 `AccessContext` 过滤可见语料；混合检索走 稠密 ∪ 稀疏 ∪ 图 三路 `RRF` 融合，交叉编码器重排；答案合成经 `LLMProvider` 并标注来源文本块。FastAPI `/query` 端点 + CLI `ask` 命令暴露 Q&A。**本阶段为“基础功能完善节点”**——混合检索与重排的精度精化（multi-vec/ColBERT、contextual retrieval、查询改写）推迟 P5，本阶段先把“能检索、能融合、能重排、能合成、可评估”跑通。

**Architecture:** 沿用 P1 的可插拔接口策略，新增四个检索域抽象（`SparseIndex` / `Reranker` / `Retriever` / `SearchEngine`），与 `VectorStore` / `GraphStore` / `CommunityStore` 同构，均接收 `AccessContext` 并复用 `visible_to` 做越权过滤。默认实现保持**确定性、零重依赖、离线可测**：稀疏用内存 BM25（`rank_bm25` 列 optional 或自建倒排），重排默认 `IdentityReranker`（保序，重依赖缺失时降级），`bge-reranker-v2-m3` 真模型列为 `extra`（与 BGE-M3 同 FlagEmbedding 依赖族）。检索引擎按 `SearchMode`（`native_rag` / `local` / `global`）编排：多路召回 -> `RRF` 融合 -> 重排 -> `AnswerSynthesizer`（LLM + 来源标注）。**评估 harness 作为贯穿项自本阶段起建立**：golden Q&A 集 + RAGAS 式指标（忠实度 / 上下文召回 / 答案相关性），每次检索改动跑回归——“精度由数据判定，不靠猜”。

**Tech Stack（P1 基础上追加）:**
- 混合检索融合：自建 `RRF`（倒数秩融合，零依赖）
- 稀疏索引：内存 BM25 倒排（默认零依赖）；`rank_bm25` 列 optional extra `search-bm25`
- 交叉编码器重排：`bge-reranker-v2-m3`（FlagEmbedding，列 extra `search-rerank`，与 `embedding-local` 同族），默认 `IdentityReranker` 降级
- 答案合成：复用 `LLMProvider`（LiteLLM，离线测试用 `sys.modules` 桩）
- 评估 harness：自建轻量指标（忠实度/上下文召回/答案相关性，LLM-as-judge 走桩）；`ragas` 列 optional extra `eval-ragas`
- L0/L1 摘要补生：复用 `LLMProvider` + `ExtractionTemplateRegistry` 的 team 上下文
- 测试：`pytest` + 内存 stores + `HashEmbeddingProvider` + 桩 LLM/reranker

---

### Task 1: 检索域抽象接口与确定性默认实现

**目标：** 立 `SparseIndex` / `Reranker` / `Retriever` / `SearchEngine` 四抽象接口（路线图“六个可插拔接口”之检索域扩展），与 P1 三 store 同构，全程接收 `AccessContext` 并复用 `visible_to` 做越权过滤。默认实现确定性、零重依赖、离线可测，作为 P2 全程的 dev/test 基座，pgvector/Neo4j 真后端与 bge 重模型列为 extra（不阻塞验收）。

> [!note] 本任务引入的 `Candidate` / `Answer` / `SearchMode` 为 P2 全局共享类型，Task 2-7 直接引用。`Candidate` 统一承载多路召回结果（向量/稀疏/图三路产出同一类型），便于 RRF 融合。

**Files:**
- Create: `src/calliodesmo/interfaces/retriever.py`（`Candidate` / `SearchMode` / `SparseIndex` / `Reranker` / `Retriever` / `SearchEngine` ABC + `Answer` dataclass）
- Create: `src/calliodesmo/retrieval/__init__.py`
- Create: `src/calliodesmo/retrieval/in_memory_sparse_index.py`（`InMemoryBM25Index`，零依赖倒排 + RRF 友好的秩输出）
- Create: `src/calliodesmo/retrieval/identity_reranker.py`（`IdentityReranker`，缺重模型时保序降级）
- Modify: `src/calliodesmo/stores/__init__.py`（如有必要补导出）
- Test: `tests/test_retrieval_interfaces.py`

**共享类型与接口（`interfaces/retriever.py`）：**

```python
class SearchMode(enum.StrEnum):
    NATIVE_RAG = "native_rag"  # 情景层：向量+稀疏混合，查原始文本块
    LOCAL = "local"  # 语义层：图邻居子图
    GLOBAL = "global"  # 摘要层：社区摘要主题


@dataclass
class Candidate:
    """多路召回的统一候选：chunk 为最小粒度（图/社区召回最终也归一到关联 chunk）。"""

    chunk_id: str
    doc_id: str
    content: str
    score: float  # 融合前的单路分数（相似度/BM25/图亲和）
    rank: int | None = None  # 单路秩（1-based），RRF 融合用
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = ""  # "vector" / "sparse" / "graph" / "community"，调试与融合诊断用


@dataclass
class Answer:
    text: str
    source_chunk_ids: list[str]  # 来源标注（证据溯源，供 UI 高亮与审计）
    mode: SearchMode
    context_chunks: list[dict[str, Any]] = field(
        default_factory=list
    )  # 喂模型的上下文摘要（id/content/score）
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)


class SparseIndex(ABC):
    @abstractmethod
    async def index(self, chunks: list[ChunkRecord]) -> None: ...

    @abstractmethod
    async def search(self, query: str, *, top_k: int, access: AccessContext) -> list[Candidate]: ...


class Reranker(ABC):
    @abstractmethod
    async def rerank(
        self, query: str, candidates: list[Candidate], *, top_k: int
    ) -> list[Candidate]: ...


class Retriever(ABC):
    @abstractmethod
    async def retrieve(
        self, query: str, *, top_k: int, mode: SearchMode, access: AccessContext
    ) -> list[Candidate]: ...


class SearchEngine(ABC):
    @abstractmethod
    async def query(
        self, question: str, *, mode: SearchMode, top_k: int, access: AccessContext
    ) -> Answer: ...
```

> [!note] `Candidate` 统一到 chunk 粒度：图检索（LocalSearch）与社区检索（GlobalSearch）召回到实体/社区后，**沿 `source_chunk_ids` 归一到关联 chunk**，使三路候选可同一口径 RRF 融合、同一口径重排与来源标注。归一时保留 `source` 字段标记原始召回来源，便于诊断“哪一路贡献了证据”。

- [ ] **Step 1:** `Candidate` / `Answer` / `SearchMode` 数据模型失败测试（字段齐全、默认值、`SearchMode` 三值）-> 实现跑绿
- [ ] **Step 2:** `InMemoryBM25Index`：index 建 token 倒排（小写化 + 简单分词，中英兼容：英文按空白/标点、中文按字 + bigram 兜底）；search 返回按 BM25 分降序的 `Candidate`（`source="sparse"`、`rank` 为 1-based 秩）；空索引 search 返空测试 -> 实现跑绿
- [ ] **Step 3:** `InMemoryBM25Index` 按 `visible_to` 过滤（越权 chunk 不进索引、不出召回）测试 -> 实现跑绿
- [ ] **Step 4:** `IdentityReranker`：保序（按传入顺序，`rank` 重置为 1..n、`score` 不变）、`top_k` 截断测试 -> 实现跑绿
- [ ] **Step 5:** 四接口 ABC 不可直接实例化（`abstractmethod` 生效）、子类需实现全部方法测试 -> 实现跑绿

**验收：**
- `SparseIndex` / `Reranker` / `Retriever` / `SearchEngine` 四抽象 + `Candidate` / `Answer` / `SearchMode` 共享类型齐全
- [ ] `InMemoryBM25Index` 零依赖、确定性、按 `visible_to` 过滤；`IdentityReranker` 保序降级
- 全程经 `AccessContext`，越权记录不出召回（与 P1 三 store 同构）

---

### Task 2: 混合检索融合（稠密 ∪ 稀疏 ∪ 图，RRF）

**目标：** 实现 `HybridRetriever`（`native_rag` 模式）：稠密向量（`VectorStore`，复用 `EmbeddingProvider`）∪ 稀疏（`InMemoryBM25Index`）两路召回 -> **倒数秩融合（RRF）** 合并 -> 重排前 top-N。融合基于 `rank` 而非原始分数（各路分数量纲不同），RRF 经典公式 `score = Σ 1/(k + rank_i)`，`k=60`。全程 `AccessContext` 过滤。

> [!note] RRF 用秩不用分数：向量余弦（0-1）与 BM25（无界）量纲不同，按秩融合更稳健（GraphRAG / BEIR 实践一致）。P2 的图召回（LocalSearch）独立成路在 Task 4；本任务的 RRF 工具与融合器为 Task 3/4 复用。

**Files:**
- Create: `src/calliodesmo/retrieval/fusion.py`（`rrf(candidates_by_lane, *, k=60, top_k) -> list[Candidate]`）
- Create: `src/calliodesmo/retrieval/hybrid_retriever.py`（`HybridRetriever`，编排 dense + sparse）
- Modify: `src/calliodesmo/retrieval/__init__.py`（导出）
- Test: `tests/test_fusion.py`、`tests/test_hybrid_retriever.py`

**RRF 融合（`retrieval/fusion.py`）：**

```python
def rrf(
    candidates_by_lane: dict[str, list[Candidate]], *, k: int = 60, top_k: int
) -> list[Candidate]:
    """倒数秩融合：按各路 rank 累加 1/(k+rank)，同 chunk_id 跨路合并。

    输入：lane -> 已赋 rank（1-based）的候选列表。
    输出：按融合分降序、top_k 截断；平局按 chunk_id 确定性排序。
    """
```

- [ ] **Step 1:** `rrf` 单路（退化为按原秩排序）、双路相同 chunk 合并（分数相加）、平局按 `chunk_id` 确定性排序、`top_k` 截断测试 -> 实现跑绿
- [ ] **Step 2:** `rrf` 稀疏命中稠密未命中（或反之）的 chunk 仍被保留（并集，不交）测试 -> 实现跑绿
- [ ] **Step 3:** `HybridRetriever` 编排：query 经 `EmbeddingProvider.embed` 走 `VectorStore.search`（dense）+ `SparseIndex.search`（sparse）-> 赋 `rank` -> `rrf` -> 返回融合候选（`source` 标注每候选主导来源）测试 -> 实现跑绿
- [ ] **Step 4:** `HybridRetriever` 全程 `visible_to` 过滤（dense 由 store 过滤、sparse 由 index 过滤；融合后不再二次过滤，因两路已过滤）测试 -> 实现跑绿
- [ ] **Step 5:** 单路降级：缺 sparse index（注入 `None`）时仅走 dense，不报错（容错）测试 -> 实现跑绿

**验收：**
- `rrf` 基于秩融合、并集不交、确定性平局、`top_k` 截断
- `HybridRetriever` 编排 dense+sparse，`native_rag` 模式可用，越权记录不出召回
- 缺一路时优雅降级

---

### Task 3: 交叉编码器重排（bge-reranker-v2-m3，打原文不打摘要）

**目标：** 引入 `Reranker` 真模型实现 `BgeReranker`（`bge-reranker-v2-m3`，与 BGE-M3 同 FlagEmbedding 依赖族，列 extra `search-rerank`）。重排**打原文**（`Candidate.content` = chunk 原文），**不打社区摘要**——摘要不含事实细节，重排需可对照原文判断相关性。默认 `IdentityReranker` 在重模型缺失时降级保序；缺依赖友好报错（沿用 BGE-M3 模式）。

> [!note] “向量与 rerank 均打原文不打摘要”是路线图明确的精度约束：社区/实体摘要供 GlobalSearch 的主题召回与 LLM 上下文，但不进稠密索引、不进 rerank 打分——避免摘要的概括性稀释重排的判别力。

**Files:**
- Create: `src/calliodesmo/retrieval/bge_reranker.py`（`BgeReranker`，extra `search-rerank`，懒加载 FlagEmbedding）
- Modify: `src/calliodesmo/retrieval/identity_reranker.py`（已有，作为默认降级）
- Modify: `pyproject.toml`（新增 optional-dependencies `search-rerank`、`search-bm25`）
- Modify: `src/calliodesmo/config.py`（新增 `reranker_model`、`rerank_top_n`、`hybrid_enabled`、`sparse_enabled`，默认 `bge-reranker-v2-m3` / `20` / `true` / `true`）
- Test: `tests/test_bge_reranker.py`（桩 FlagEmbedding，零真实模型）

**接口与降级（`retrieval/bge_reranker.py`）：**

```python
class BgeReranker(Reranker):
    """bge-reranker-v2-m3 交叉编码器重排（extra: search-rerank）。

    打 chunk 原文（Candidate.content），不打摘要；缺依赖抛友好错误并提示
    `uv sync --extra search-rerank`。离线测试用 sys.modules 桩 FlagEmbedding。
    """

    def __init__(self, model: str = "BAAI/bge-reranker-v2-m3") -> None: ...

    async def rerank(
        self, query: str, candidates: list[Candidate], *, top_k: int
    ) -> list[Candidate]: ...
```

- [ ] **Step 1:** `BgeReranker` 桩 FlagEmbedding：`rerank` 对 `(query, content)` 打分、按分降序、`top_k` 截断、`rank` 重置、`score` 更新为重排分测试 -> 实现跑绿
- [ ] **Step 2:** 打原文约束：断言喂 reranker 的文本为 `Candidate.content`（chunk 原文），不喂社区/实体摘要测试 -> 实现跑绿
- [ ] **Step 3:** 缺依赖友好报错（`monkeypatch`/`sys.modules` 卸载 FlagEmbedding -> `RuntimeError("重排需 FlagEmbedding：uv sync --extra search-rerank")`）测试 -> 实现跑绿
- [ ] **Step 4:** `config` 新增项（`reranker_model` / `rerank_top_n` / `hybrid_enabled` / `sparse_enabled`）默认值与环境覆盖测试 -> 实现跑绿
- [ ] **Step 5:** 重排串联：`HybridRetriever` 召回 -> `Reranker.rerank`（默认 `IdentityReranker`，可注入 `BgeReranker`）-> top_k；缺 reranker 注入时退化为保序测试 -> 实现跑绿

**验收：**
- `BgeReranker` 经 FlagEmbedding 重排，打原文不打摘要，`top_k` 截断与分更新
- 缺依赖友好报错（与 BGE-M3 同模式）；默认 `IdentityReranker` 降级保序
- `config` 暴露重排/混合开关，离线全桩测试

---

### Task 4: 三检索模式与答案合成（NativeRAG / Local / Global）

**目标：** 实现三种检索模式，对应三层知识图谱的访问面：
- **NativeRAG**（情景层）：`HybridRetriever`（dense+sparse RRF）-> rerank，查原始文本块
- **LocalSearch**（语义层）：从 query 抽取的种子实体出发，沿 `GraphStore.neighbors` 扩 K 跳子图，归一到关联 chunk -> rerank
- **GlobalSearch**（摘要层）：`CommunityStore.list_communities` 按社区摘要向量召回相关社区，社区成员实体归一到 chunk；社区摘要进 LLM 上下文但**不进重排/稠密索引**

各模式召回后统一经 `Reranker`（Global 的社区级召回不经 chunk rerank，仅 Local/Native 走 rerank），交 `AnswerSynthesizer`（`LLMProvider`）生成带来源标注的 `Answer`。

**Files:**
- Create: `src/calliodesmo/retrieval/local_search.py`（`LocalSearchRetriever`，图邻居 K 跳）
- Create: `src/calliodesmo/retrieval/global_search.py`（`GlobalSearchRetriever`，社区摘要向量召回）
- Create: `src/calliodesmo/retrieval/seed_extractor.py`（从 query 抽种子实体名：模板引导复用 `ExtractionTemplateRegistry` 的 team 上下文；轻量 NER/LLM，桩）
- Create: `src/calliodesmo/retrieval/answer_synthesizer.py`（`AnswerSynthesizer`，LLM + 来源标注 prompt）
- Create: `src/calliodesmo/retrieval/search_engine.py`（`DefaultSearchEngine`，按 `SearchMode` 编排 retriever + synthesizer）
- Modify: `src/calliodesmo/config.py`（新增 `local_search_hops`、`global_top_communities`，默认 `1` / `10`）
- Test: `tests/test_local_search.py`、`tests/test_global_search.py`、`tests/test_answer_synthesizer.py`、`tests/test_search_engine.py`

**接口设计：**

```python
class LocalSearchRetriever(Retriever):
    async def retrieve(self, query, *, top_k, mode=SearchMode.LOCAL, access) -> list[Candidate]:
        seeds = await self.seed_extractor.extract(query, access=access)  # 种子实体名
        subgraph = await expand(seeds, hops=self.hops, graph=self.graph, access=access)
        return to_candidates(subgraph)  # 沿 source_chunk_ids 归一到 chunk


class GlobalSearchRetriever(Retriever):
    async def retrieve(self, query, *, top_k, mode=SearchMode.GLOBAL, access) -> list[Candidate]:
        # 社区摘要向量召回相关社区 -> 成员实体归一 chunk；摘要进上下文不进重排
        communities = await self.community_store.list_communities(access=access)
        ranked = await rank_communities_by_vector(query, communities, access=access)
        return to_candidates(ranked[: self.top_communities])


class AnswerSynthesizer:
    async def synthesize(
        self, question: str, candidates: list[Candidate], *, mode: SearchMode, access: AccessContext
    ) -> Answer:
        # prompt 含来源标注要求：答案须标注引用的 chunk_id；忠实度约束（不编造）
        ...
```

- [ ] **Step 1:** `SeedExtractor` 从 query 抽种子实体名（桩 LLM 返回实体名列表）；命中 `GraphStore.get_entity` 的为有效种子、未命中的过滤测试 -> 实现跑绿
- [ ] **Step 2:** `LocalSearchRetriever` K 跳扩展（默认 `hops=1`）：从种子沿 `GraphStore.neighbors` 收集实体+关系 -> 沿 `source_chunk_ids` 归一 chunk -> 去重；越权邻居被 `GraphStore` 过滤不可见测试 -> 实现跑绿
- [ ] **Step 3:** `GlobalSearchRetriever`：`CommunityStore.list_communities`（已按 `visible_to` 过滤）-> query 向量对社区摘要标题+摘要文本余弦召回 -> 取 top-N 社区 -> 成员实体归一 chunk 测试 -> 实现跑绿
- [ ] **Step 4:** `GlobalSearch` 的社区摘要进 LLM 上下文但**不进 rerank、不进稠密索引**（断言 reranker 仅在 Local/Native 通路被调用；Global 不喂 reranker）测试 -> 实现跑绿
- [ ] **Step 5:** `AnswerSynthesizer` prompt 含来源标注与忠实度约束；桩 LLM 返回带 `[chunk_id]` 标注的答案 -> 解析出 `source_chunk_ids`；候选为空时返回“无可引用证据”而非编造测试 -> 实现跑绿
- [ ] **Step 6:** `DefaultSearchEngine` 按 `SearchMode` 分派（`native_rag`->`HybridRetriever`、`local`->`LocalSearchRetriever`、`global`->`GlobalSearchRetriever`）-> rerank（仅 Local/Native）-> `AnswerSynthesizer` -> `Answer`（含 `mode` / `source_chunk_ids` / `context_chunks`）端到端测试 -> 实现跑绿
- [ ] **Step 7:** 三模式全程 `visible_to`：低 clearance 用户跨模式检索均不可见越权 chunk（构造 mixed-access 语料断言）测试 -> 实现跑绿

**验收：**
- NativeRAG（dense+sparse+rerank）、Local（图邻居 K 跳+rerank）、Global（社区摘要向量召回，摘要不进重排）三模式可用
- 种子实体抽取命中图、未命中过滤；社区召回按向量相关性排序
- `Answer` 标注 `source_chunk_ids`，候选为空时不编造
- 全程 `visible_to`，越权记录三模式皆不可见

---

### Task 5: 评估 harness（golden 集 + RAGAS 式指标回归）

**目标：** 建**贯穿项评估 harness**——路线图“精度由数据判定”的核心尺子。维护 golden Q&A 集（问题 + 标准答案 + 相关 chunk_id），每次检索改动跑回归，指标含：**上下文召回**（相关 chunk 是否被召回）、**忠实度**（答案是否由召回上下文支撑，LLM-as-judge）、**答案相关性**（答案是否切题）。自建轻量指标（LLM-as-judge 走桩），`ragas` 列 optional extra `eval-ragas`。

> [!note] 评估 harness 是 P1/P2 起的贯穿项：没有尺子不知检索改动是变好还是变坏。P1 验证以功能测试+离线桩为主，质量评测自本 Task 接入，后续每个检索改动（hybrid 开关、rerank 模型、k 值）跑回归对照。golden 集起步小（~10-20 条），随用随扩。

**Files:**
- Create: `src/calliodesmo/eval/__init__.py`
- Create: `src/calliodesmo/eval/golden.py`（`GoldenCase` dataclass + 从 YAML 加载 `golden_qa.yaml`）
- Create: `src/calliodesmo/eval/metrics.py`（`context_recall` / `faithfulness` / `answer_relevance`，LLM-as-judge 走 `LLMProvider`）
- Create: `src/calliodesmo/eval/harness.py`（`EvalHarness.run(engine, cases) -> EvalReport`，跑全集统计均值）
- Create: `config/golden_qa.example.yaml`（golden 样例）
- Modify: `src/calliodesmo/config.py`（新增 `eval_golden_file`，默认 `config/golden_qa.yaml`）
- Test: `tests/test_eval_harness.py`

**指标（`eval/metrics.py`）：**

```python
def context_recall(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    """相关 chunk 的召回比例（确定性，0-1）。"""


async def faithfulness(answer: str, context: list[str], *, judge: LLMProvider) -> float:
    """忠实度：答案断言能否由 context 支撑（LLM-as-judge，0-1）。"""


async def answer_relevance(answer: str, question: str, *, judge: LLMProvider) -> float:
    """答案相关性：答案是否切题（LLM-as-judge，0-1）。"""
```

- [ ] **Step 1:** `GoldenCase` 数据模型 + 从 YAML 加载（问题/标准答案/相关 chunk_id/模式）；空文件 -> 空集测试 -> 实现跑绿
- [ ] **Step 2:** `context_recall` 确定性计算（召回相关 chunk 占比；无相关 -> 0；全召回 -> 1）测试 -> 实现跑绿
- [ ] **Step 3:** `faithfulness` / `answer_relevance` LLM-as-judge（桩 LLM 返回 0-1 分数；非法返回 -> 0 且不抛）测试 -> 实现跑绿
- [ ] **Step 4:** `EvalHarness.run`：对每 golden case 跑 `engine.query` -> 取 `source_chunk_ids` 算 `context_recall`、取 `text` 算 `faithfulness`/`answer_relevance` -> 汇总均值与每条详情 `EvalReport` 测试 -> 实现跑绿
- [ ] **Step 5:** 回归断言：给定固定语料 + 桩 LLM/reranker，harness 输出确定性（两次运行同输入同输出），可作回归基线测试 -> 实现跑绿

**验收：**
- golden Q&A 集从 YAML 加载；`context_recall` 确定性、`faithfulness`/`answer_relevance` LLM-as-judge
- `EvalHarness.run` 跑全集出 `EvalReport`（均值+详情），离线全桩可跑
- 回归基线确定性，可对照“改动前后精度是否退化”

---

### Task 6: L0/L1 分层摘要按需补生（Chunk.summary）

**目标：** P1 仅在 `Chunk.summary` 预留可选字段（填 None，不写生成逻辑）。本 Task **按需补生** L0 短摘要（~100 token）：ingest 时为每个 chunk 生成超短摘要供向量粗筛/rerank 参照与用户侧列表预览；L1 社区摘要 P1 已有（`Community.title`+`summary`）。补生经 `LLMProvider`，**摘要不进稠密索引/不进 rerank 打分**（仅 NativeRAG 的 chunk 原文与 Global 的社区摘要各自进对应通路），供展示层与粗筛。

> [!note] L0/L1 参考 OpenViking 三层理念（L0 超短/L1 中/L2 长），但本项目为图+社区非树形目录，取其“分层摘要”理念非目录递归：L0=chunk 短摘要（本 Task）、L1=社区摘要（P1 已有）、L2=全库主题（P6）。P1 预留 `Chunk.summary=None` 即为本 Task 的接入点。

**Files:**
- Create: `src/calliodesmo/ecl/chunk_summarizer.py`（`LLMChunkSummarizer`，经 `LLMProvider` 生成 ~100 token 摘要，带 `summary_enabled` 开关）
- Modify: `src/calliodesmo/ecl/load.py`（`LoadService`：`ChunkRecord` 写入前按需填 `metadata["summary"]`；与 `Chunk.summary` 对齐）
- Modify: `src/calliodesmo/ecl/engine.py`（`ECLIndexingEngine` 可选串联摘要生成，开关 `chunk_summary_enabled` 默认 `false`，P2 验收时按需开）
- Modify: `src/calliodesmo/config.py`（新增 `chunk_summary_enabled: bool = False`）
- Test: `tests/test_chunk_summarizer.py`

- [ ] **Step 1:** `LLMChunkSummarizer` 桩 LLM 生成 ~100 token 摘要；空 chunk / 超短 chunk 返原文截断测试 -> 实现跑绿
- [ ] **Step 2:** 摘要不进稠密索引：`LoadService` 写 `ChunkRecord` 时 `content` 仍为 chunk 原文，摘要入 `metadata["summary"]`，断言 `VectorStore` 收到的 `content` 不被摘要替换测试 -> 实现跑绿
- [ ] **Step 3:** 开关默认关：`chunk_summary_enabled=False` 时 `ECLIndexingEngine` 不调 LLM、`metadata["summary"]` 缺省；开启时按需生测试 -> 实现跑绿
- [ ] **Step 4:** 展示层消费：`Candidate` 召回后可携带 `metadata["summary"]` 供 UI 列表预览（NativeRAG 模式断言候选含摘要）测试 -> 实现跑绿

**验收：**
- L0 chunk 短摘要按需生成（~100 token），默认关，开关开时 ingest 触发
- 摘要不进稠密索引/不进 rerank 打分，仅入 `metadata["summary"]` 供展示与粗筛
- 与 P1 `Chunk.summary` 预留字段对齐，L1 社区摘要复用 P1 既有

---

### Task 7: API `/query` 端点与 CLI `ask` 命令

**目标：** 把 P2 检索能力经 FastAPI `/query` 端点 + Typer `ask` 命令暴露，支持 `mode` 选择与 `top_k` 调参，返回带来源标注的 `Answer`，全程 `AccessContext` 过滤（需 `query` 权限）并记审计。

**Files:**
- Modify: `src/calliodesmo/api/app.py`（新增 `POST /query`，`Depends(get_current_context)` + `Permission.QUERY` 守卫）
- Modify: `src/calliodesmo/api/schemas.py`（`QueryRequest` / `QueryResponse`）
- Modify: `src/calliodesmo/api/deps.py`（如需 `get_search_engine` 依赖工厂）
- Modify: `src/calliodesmo/cli.py`（新增 `ask` 命令）
- Modify: `src/calliodesmo/config.py`（如需 `default_search_mode`，默认 `native_rag`）
- Test: `tests/test_query_api.py`、`tests/test_ask_cli.py`

**API 接口：**

```python
class QueryRequest(BaseModel):
    question: str
    mode: str = "native_rag"  # native_rag / local / global
    top_k: int = 10


class QueryResponse(BaseModel):
    answer: str
    mode: str
    source_chunk_ids: list[str]
    context_chunks: list[dict[str, Any]]
    model: str
```

```python
@app.post("/query", response_model=QueryResponse)
async def query(
    req: QueryRequest,
    context: AccessContext = Depends(get_current_context),
    engine: SearchEngine = Depends(get_search_engine),
    session: AsyncSession = Depends(get_session),
) -> QueryResponse:
    require_permission(context, Permission.QUERY)  # 缺权限 403
    answer = await engine.query(
        req.question, mode=SearchMode(req.mode), top_k=req.top_k, access=context
    )
    await record_audit(
        session,
        user_id=context.user_id,
        action="query",
        resource_type="answer",
        detail={"mode": req.mode, "sources": len(answer.source_chunk_ids)},
        source="api",
    )
    await session.commit()
    return QueryResponse(...)
```

- [ ] **Step 1:** `POST /query`：认证 + `Permission.QUERY` 守卫（缺权限 403）；桩 `SearchEngine` 返回固定 `Answer` -> `QueryResponse`；来源标注透传测试 -> 实现跑绿
- [ ] **Step 2:** 三模式参数路由（`mode` 取 `native_rag`/`local`/`global`，非法值 400）；`top_k` 边界（<=0 -> 422）测试 -> 实现跑绿
- [ ] **Step 3:** 审计：`/query` 记 `action="query"`、`detail={mode, sources_count}`、`source="api"` 测试 -> 实现跑绿
- [ ] **Step 4:** CLI `ask <question> [--mode] [--top-k]`：构造默认引擎（内存 stores + `HashEmbeddingProvider` + `IdentityReranker` + 桩 LLM）-> 打印答案 + 来源 chunk_id；`CliRunner` 断言退出码 0 测试 -> 实现跑绿
- [ ] **Step 5:** CLI 失败友好报错（无 `query` 权限用户 -> 提示；LLM 缺 key -> 指引 `CALLIODESMO_LLM_API_KEY`）测试 -> 实现跑绿
- [ ] **Step 6:** 端到端（离线）：ingest 样例语料 -> `/query`（native_rag）召回相关 chunk + 答案标注来源；低 clearance 用户不可见越权 chunk 测试 -> 实现跑绿

**验收：**
- `POST /query` 认证 + `query` 权限守卫 + 三模式 + `top_k` + 来源标注 + 审计
- CLI `ask` 一问一答，打印答案与来源 chunk_id
- 离线端到端：ingest -> query 召回相关 chunk 且越权不可见

---

## 精度策略与跨阶段改进（前瞻）

> [!note] 延续 P1 的精度杠杆排序，本阶段落地“检索精度”这一第一杠杆的过门槛部分，更重的留 P5；评估 harness 自本阶段起作为贯穿尺子。全部经可插拔接口接入，不动核心。

**本阶段落地的精度投资：**
1. **评估 harness（贯穿项，最大缺口）**——golden 集 + 三指标回归，每次检索改动对照基线（本阶段从 0 到 1 建立，是后续一切精度判断的前提）。
2. **混合检索（第一精度杠杆，过门槛）**——dense+sparse RRF 融合 + 交叉编码器重排；打原文不打摘要（判别力约束）。
3. **来源标注 + 忠实度约束**——答案须由召回上下文支撑，候选为空不编造（AnswerSynthesizer prompt + `faithfulness` 指标双重把关）。
4. **三模式分层**——Native/Local/Global 对应情景/语义/摘要三层，避免“一把向量查全部”的粒度错配。

**留待后续阶段（不阻塞 P2 验收）：**
- **multi-vec / ColBERT**（BGE-M3 第三输出，token 级迟交互）：P5 精化。P2 先用 dense+sparse+图+交叉编码器；路线图“三输出全用”的第三路（multi-vec）推迟 P5 成熟。
- **查询改写**（MultiQuery / RAGFusion / SubQuestion / CRAG / Adaptive）：P5 高级检索。
- **分层切分 + 上下文富化（Anthropic contextual retrieval）**：P5 精化（切分本身 P1 已过门槛）。
- **ANN 向量索引（HNSW/IVF）支撑 ≥50 万**：P9（`VectorStore` 接口已预留）。
- **跨文档交叉验证 / 低接地声明幻觉标记**：P8 证据验证硬化。
- **图召回的实体链接精度**（query 抽种子实体的 NER/消解歧义）：P2 用轻量种子抽取过门槛，P5/P8 精化。

**依赖与风险（P2 全量）：**
- **重排真模型** `bge-reranker-v2-m3` 列 extra `search-rerank`（与 `embedding-local` 同 FlagEmbedding 族）；CI 默认 `IdentityReranker` 降级 + 桩测接口；真机验证用 `uv sync --extra search-rerank`。
- **稀疏索引**默认 `InMemoryBM25Index`（零依赖倒排）；`rank_bm25` 列 optional `search-bm25`，缺依赖用自建倒排。
- **评估 LLM-as-judge** 真实运行需 key；离线测试全用 `sys.modules` 桩 litellm（沿用 P0/P1 模式），`ragas` 列 optional `eval-ragas`。
- **检索全程 `visible_to`**：dense（store）/ sparse（index）/ local（graph store）/ global（community store）四路均按 `AccessContext` 过滤；融合/重排/合成基于已过滤结果，不再二次过滤（避免漏召回）。
- **版本钉制**：引入 rerank/BM25/ragas 时与 litellm `>=1.85,<1.91`、FlagEmbedding 协调，避免传递依赖冲突（Windows 无 wheel 风险）。
- **精度边界（如实声明）**：query 种子实体抽取（Local 模式）在 P2 用轻量模板/LLM 过门槛，复杂指代/歧义留 P5/P8；Global 模式社区召回依赖 P1 社区摘要质量，社区越粗召回越泛。
- **内存 stores 非持久**：P2 默认内存实现保证离线可测与 CI 可跑；pgvector/Neo4j 真后端持久化列为 extra（与 P1 同策略），prod 检索由真后端承担。ingest 与 query 需共享同一 store 实例（内存模式下同进程）；跨进程持久化随真后端接入解决。
