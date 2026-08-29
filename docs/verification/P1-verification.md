---
title: P1 验证报告（ECL 管线 MVP）
type: verification-report
phase: P1
date: 2026-07-26
tags:
  - verification
related:
  - "[[docs/plans/phases/P1-ecl-pipeline]]"
  - "[[docs/verification/P0-verification]]"
---
# P1 验证报告（ECL 管线 MVP：Extract → Cognify → Load）

> 关联：[[docs/plans/phases/P1-ecl-pipeline|P1 实施计划]] · [[docs/verification/P0-verification|P0 验证]] · [[docs/plans/roadmap|路线图]]

## 结论

**P1 ECL 主链路打通**：`Load → Extract → Cognify → Load → 文档社区派生` 端到端离线跑通，`calliodesmo ingest <path>` 一键建图落个人库并记审计。全程**桩 LLM + Hash 嵌入 + 内存 stores**，零真实网络、零外部服务依赖，CI 可跑。

| 维度 | 结果 | 证据 |
| --- | --- | --- |
| 自动化测试 | **124 通过**（P0 33 + P1 91） | `uv run pytest -q` → `124 passed` |
| 静态/格式 | ruff **0 error** · 96 files 一致 | `ruff check .` / `format --check .` |
| 端到端 | ingest CLI 退出码 0 + 审计落库 | `tests/test_ingest_cli.py::test_ingest_success` |

## 一、测试内容

**P1 新增 91 用例，按 Task**：

| Task | 测试文件 | 用例 | 覆盖要点 |
| --- | --- | --- | --- |
| 1 文档加载 | `test_document_loaders.py` | 20 | 12 内置格式 + LoaderRegistry + 缺依赖友好报错（pdf/office） |
| 2 切分+抽取 | `test_chunker/extractor/extraction_template.py` | 24 | 结构感知分块、模板软引导打标、source_chunk_ids、非法 JSON 抛 ExtractionError |
| 3 Cognify | `test_cognify.py` | 11 | 建图、实体消解、LLMAliasResolver 回退、连通分量确定性、社区摘要 |
| 4 存储+落库 | `test_visibility/in_memory_stores/load.py` | 14 | visible_to 三 scope、余弦过滤、幂等 upsert、Load 三 store |
| 5 文档社区 | `test_community_deriver.py` | 3 | level=1 派生、增量安全 |
| 6 引擎+CLI | `test_indexing_engine/ingest_cli.py` | 7 | ECLIndexingEngine 端到端、ingest 成功+审计、友好报错 |

## 二、技术栈

- **被测**：`LoaderRegistry`+12 loader · `TextChunker`/`LLMExtractor`/`ExtractionTemplateRegistry` · `EntityRelationGraphBuilder`/`NameEntityResolver`/`ConnectedComponentsDetector`（确定性）/`NetworkxCommunityDetector`（extra）/`LLMCommunitySummarizer`/`CognifyPipeline` · 内存三 store + `visible_to` · `DocumentCommunityDeriver` · `ECLIndexingEngine` + CLI `ingest` · 共享类型（Chunk 含 `summary` 预留字段）。
- **工具链**：pytest 9.1.1 + pytest-asyncio（auto）· `sys.modules` 桩 litellm + `_StubLLM` canned JSON · `HashEmbeddingProvider` · 内存三 store · Ruff。

## 三、验证原理

- **TDD**：每 Task 先写失败测试 → 实现 → 跑绿（checkbox 跟踪）。
- **隔离优先**：LLM 全程走抽象 + `sys.modules` 桩，零真实请求；Hash 嵌入确定性；无需 PG/Neo4j。
- **契约优先**：六接口 + 共享类型先行，Task 1-6 只填实现。
- **幂等**：种子/引导/测试可重复执行；upsert 覆盖非重复。
- **access 贯通**：`Chunk`/`Entity`/`Community`/Record 携带 access 字段，`visible_to` 全程过滤。

## 四、验证过程

```bash
uv sync && uv run ruff format --check . && uv run ruff check . && uv run pytest -q   # 124 passed
```

实际执行（2026-07-26，Windows 11 + uv 0.11.24 + Python 3.12.13）：`124 passed, 6 warnings in 2.25s`（6 warnings 为 P0 JWT 短密钥 `InsecureKeyLengthWarning`）。`config/extraction_templates.example.yaml` 可被 registry 加载（1 模板 / team-alpha）。

**提交**：`7a5aabe`（Task 1-6 主链路）→ `aa12853`（Task 7 档案卡）→ `5f3c395`（本地 LLM 接入，api_base localhost 自动豁免 key）。

## 五、已知边界与后续

- **文档解析重依赖按 extra 分组**：PDF 仅文本型，扫描/图片型需 OCR（不在 P1）。
- **三层存储为内存默认**（非持久）；pgvector/Neo4j 真后端列 extra（P4.5 已落地）。
- **社区检测默认连通分量**；Louvain/Leiden 列 extra。
- **L0/L1 摘要**：`Chunk.summary` 为预留字段，P1 填 None；属 P2/P5。
- **精度边界**：跨 chunk 关系、指代歧义靠切分+消解+溯源缓解，P8 证据验证硬化。
- **评估 harness 自 P2 接入**；CLI 默认不跑社区摘要（`summarizer=None`，可注入）。
