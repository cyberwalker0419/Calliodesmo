# P1 验证报告（ECL 管线 MVP：Extract → Cognify → Load）

> 关联：[[docs/plans/phases/P1-ecl-pipeline|P1 实施计划]] · [[docs/verification/P0-verification|P0 验证]] · [[docs/plans/roadmap|路线图]]

## 结论

**P1 ECL 主链路打通**：`Load → Extract → Cognify → Load → 文档社区派生` 端到端离线跑通，
`calliodesmo ingest <path>` 一键建图落个人库并记审计。全程**桩 LLM + Hash 嵌入 + 内存 stores**，
零真实网络请求、零外部服务依赖，CI 可跑。

| 维度 | 结果 | 证据 |
| --- | --- | --- |
| 自动化测试 | **112 通过**（P0 33 + P1 79） | `uv run pytest -q` → `112 passed` |
| 静态检查 | ruff **0 error** | `uv run ruff check .` → `All checks passed!` |
| 格式检查 | **91 files 一致** | `uv run ruff format --check .` → `91 files already formatted` |
| 端到端 | ingest CLI 退出码 0 + 审计落库 | `tests/test_ingest_cli.py::test_ingest_success` |

---

## 一、测试内容

### 1.1 自动化测试矩阵（P1 新增 79 用例，按 Task）

| Task | 测试文件 | 用例 | 覆盖要点 |
| --- | --- | --- | --- |
| 1 文档加载 | `test_document_loaders.py` | 20 | 内置 12 格式（txt/md/log/csv/tsv/json/yaml/xml/html/rst/org/tex）、LoaderRegistry 分发与未注册报错、缺依赖友好报错（pdf/office）、端到端冒烟 |
| 2 切分+抽取 | `test_chunker.py` `test_extractor.py` `test_extraction_template.py` | 9+9+6 | 结构感知切分（确定性/无丢失/overlap 接缝/代码块完整/空文档/access 字段）、模板软引导打标（conforming/discovered_types/schema_mode）、source_chunk_ids 全覆盖、非法 JSON 抛 ExtractionError、prompt 透明、模型参数透传、模板按 team 唯一+重复报错 |
| 3 Cognify | `test_cognify.py` | 11 | 建图（自环/重复边过滤）、实体消解（名归一化/别名/描述汇总/conforming 并集）、LLMAliasResolver 回退、连通分量确定性、networkx 缺依赖报错、社区摘要、CognifyPipeline 串联 |
| 4 存储+落库 | `test_visibility.py` `test_in_memory_stores.py` `test_load.py` | 5+6+3 | visible_to 三 scope + clearance 有序、余弦检索过滤/top_k/平局、图邻居过滤、社区列表排序、幂等 upsert、LoadService 三 store 落库 + access 从 chunk 继承 |
| 5 文档社区 | `test_community_deriver.py` | 3 | 按 doc 聚合实体、level=1 派生、写入 CommunityStore、增量安全（不动已有） |
| 6 引擎+CLI | `test_indexing_engine.py` `test_ingest_cli.py` | 3+4 | ECLIndexingEngine 端到端统计、personal scope 隔离、空目录、ingest CLI 成功+审计、路径不存在/未注册后缀/LLM 缺 key 友好报错 |

### 1.2 自动化之外的端到端验证

- `calliodesmo ingest <path>`（桩引擎）输出 `文档 1 / 块 N / 实体 2 / 关系 1 / 社区 M`，`audit_logs` 表写入 `("ingest","document","cli")`。
- `config/extraction_templates.example.yaml` 可被 `ExtractionTemplateRegistry.from_yaml` 加载（1 模板 / team-alpha）。

---

## 二、技术栈

### 2.1 被测系统（P1 实现）

| 层 | 组件 |
| --- | --- |
| Load | `LoaderRegistry` + 12 内置 loader + 6 类 extra loader（pdf/office/opendocument/rich/email/notebooks），按后缀分发，缺依赖友好报错 |
| Extract | `TextChunker`（结构感知 + overlap）、`LLMExtractor`（模板软引导 + 打标 + JSON 解析 + 健壮报错）、`ExtractionTemplateRegistry`（YAML 按 team 唯一） |
| Cognify | `EntityRelationGraphBuilder`、`NameEntityResolver`（名归一化+别名+描述汇总）、`LLMAliasResolver`、`ConnectedComponentsDetector`（确定性）、`NetworkxCommunityDetector`（extra）、`LLMCommunitySummarizer`、`CognifyPipeline` |
| Load(存储) | `InMemoryVectorStore`（余弦）、`InMemoryGraphStore`、`InMemoryCommunityStore`、`visible_to` 谓词、`LoadService` |
| 派生 | `DocumentCommunityDeriver`（level=1 文档社区） |
| 编排 | `ECLIndexingEngine` + `build_default_indexing_engine` + CLI `ingest` |
| 共享类型 | `Chunk`（含 `summary` 预留字段，P1 填 None）/`Entity`/`Relation`/`Claim`/`Covariate`/`ExtractionResult`/`ExtractionTemplate`/`Community`/三 store Record |

### 2.2 验证工具链

| 类别 | 工具 |
| --- | --- |
| 测试 | pytest 9.1.1 + pytest-asyncio 1.4.0（auto 模式） |
| 桩隔离 | `sys.modules` 桩隔离 litellm（沿用 P0）；`_FakeLLM`/`_StubLLM` 返回 canned JSON，零真实请求 |
| 嵌入 | `HashEmbeddingProvider`（确定性，离线） |
| 存储 | 三层内存默认实现（确定性可复现） |
| 静态/格式 | Ruff 0.16.0（lint + format，CI 同步） |

---

## 三、验证原理

- **TDD**：每 Task 先写失败测试 → 实现 → 跑绿；步骤用 checkbox 跟踪。
- **隔离优先**：LLM 全程经 `LLMProvider` 抽象，离线测试用 `sys.modules` 桩，零真实请求；嵌入用 Hash 确定性实现；三 store 用内存默认实现，无需 Postgres/Neo4j。
- **契约优先**：六接口（DocumentLoader/Chunker/Extractor/Cognify 组件/三 store/IndexingEngine）+ 共享类型先行，Task 1-6 仅填实现，可插拔。
- **幂等可重复**：种子与引导脚本、测试用例均可重复执行；upsert 同 id/name 覆盖非重复。
- **access 贯通**：`Chunk`/`Entity`/`Community`/三 store Record 均携带 access 字段，`visible_to` 按 clearance + scope + owner/team/project 过滤，越权记录不可见（personal scope 隔离测试验证）。

---

## 四、验证过程

### 4.1 复现步骤（学生机/CI 通用）

```bash
uv sync
uv run ruff format --check .     # 91 files already formatted
uv run ruff check .              # All checks passed!
uv run pytest -q                 # 112 passed
```

> Windows 沙箱下 uv 受管 Python 位于 AppData，需在沙箱外执行（`uv run` 前缀已登记）。

### 4.2 实际执行记录（2026-07-26，Windows 11 + uv 0.11.24 + Python 3.12.13）

```
uv run pytest -q
........................................ [ 64%]
........................................ [100%]
112 passed, 6 warnings in 2.28s
```

6 warnings 均为 P0 JWT 测试的 `InsecureKeyLengthWarning`（测试用短密钥，非 P1 引入）。

### 4.3 提交锚点

P1 实现集中于 `src/calliodesmo/ecl/`、`src/calliodesmo/providers/`（新增 loader/store）、`src/calliodesmo/interfaces/`（新增接口）、`src/calliodesmo/stores/`，测试集中于 `tests/test_*.py`（11 个新文件）。

---

## 五、已知边界与后续

- **文档解析重依赖按 extra 分组**（documents-pdf/office/opendocument/rich/email/notebooks）；CI 默认只装基础 + `sys.modules` 桩测接口；真机验证用 `uv sync --extra documents-pdf ...` 组合。**PDF 仅支持文本型**，扫描/图片型需 OCR（不在 P1）。
- **三层存储为内存默认实现**（非持久，dev/test 重建即恢复）；pgvector/Neo4j 真后端列为 optional extra（容器验证，与 BGE-M3 同策略）。
- **社区检测默认 `ConnectedComponentsDetector`**（零重依赖、确定性）；networkx Louvain/Leiden 列 extra（`graph-analytics`），缺依赖友好报错。
- **L0/L1 分层摘要**：`Chunk.summary` 为预留字段，**P1 全程填 None，不写生成逻辑**；L0/L1 摘要属 P2/P5（参考 OpenViking 分层理念）。
- **精度边界**：跨 chunk 关系抽取、别名/指代歧义在 MVP 不完美，靠结构感知切分 + 实体消解 + `source_chunk_ids` 溯源缓解，**P8 证据验证硬化**。
- **评估 harness（贯穿项）**：P1 验证以功能测试 + 离线桩为主；golden 集 + 质量评测自 P2 接入。
- **CLI 默认不跑 LLM 社区摘要**（`CognifyPipeline(summarizer=None)`，省调用）；摘要路径经 `LLMCommunitySummarizer` 可注入，已单测覆盖。