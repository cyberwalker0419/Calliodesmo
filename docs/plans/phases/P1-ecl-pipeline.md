---
title: P1 ECL 管线 MVP 实施计划
type: phase-plan
phase: P1
tags:
  - plan/phase
created: 2026-07-26
---
# P1 ECL 管线 MVP 实施计划
> **For agentic workers:** 按 Task 顺序逐任务执行；步骤用 checkbox（`- [x]`）跟踪。每个 Task 内按 TDD：先写失败测试 -> 实现 -> 跑绿 -> 提交。关联：[[docs/plans/phases/P0-scaffolding|P0]] / [[docs/plans/phases/P2-retrieval-rag|P2]]。
**Goal:** 打通 ECL 主链路（Extract -> Cognify -> Load），实现“数据进 -> 建图 -> 落个人库”。Extract 入口支持多格式文档解析：基础格式（纯文本/标记/表格/结构化）内置，PDF、Office 全家桶、开放文档、富文本/电子书、邮件、Jupyter 笔记本以可拓展插件方式按需接入。
**Architecture:** `DocumentLoader` 抽象（P0 已立）不变；每类格式一个 Loader 插件，按 `source.suffix` 经 `LoaderRegistry` 分发，新增格式只需新增 Loader + 注册，不动核心。基础格式默认内置；重依赖格式列 optional extra、懒加载、缺依赖友好报错。Cognify 默认自建（实体-关系图 + 实体消解 + 连通分量社区检测 + LLM 社区摘要；networkx/GraphRAG Leiden 可选 extra）；抽取走团队级软引导模板；Load 写个人库三层数据（情景/语义/摘要）。
**Tech Stack（P0 基础上追加）:**
- 基础格式：标准库 `csv`/`json`/`html.parser`/`xml.etree` + `PyYAML`；纯文本/Markdown 已有；测试用 `pytest` + 临时样例 + `sys.modules` 桩隔离重依赖
- 可选 extra：`documents-pdf`（pypdf）｜ `documents-office`（python-docx/openpyxl/python-pptx）｜ `documents-opendocument`（odfpy）｜ `documents-rich`（striprtf/ebooklib）｜ `documents-email`（extract-msg）｜ `documents-notebooks`（nbformat）；后端兜底 `pandoc` / `LibreOffice(headless)`

---

### Task 1: 文档解析与加载器（多格式 + 可拓展插件）

**目标：** P1 阶段可解析多种基础格式，并按可拓展插件接入 PDF、Office 全家桶及更多富文档格式。
**Files:**
- Modify: `src/calliodesmo/providers/text_loader.py`（保留 txt/md，抽公共逻辑）；Create: `providers/{structured_loader,markup_loader}.py`（csv/tsv/json/yaml/xml/html、rst/org/tex）
- Create: `src/calliodesmo/providers/registry.py`（按后缀分发 + 注册表）
- Create（extra）: `pdf_loader.py`（documents-pdf）｜ `office_loader.py`（documents-office，docx/xlsx/pptx）｜ `opendocument_loader.py`（documents-opendocument）｜ `rich_loader.py`（documents-rich，rtf/epub/mobi）｜ `email_loader.py`（documents-email，eml/msg）｜ `notebook_loader.py`（documents-notebooks，ipynb）
- Modify: `pyproject.toml`（新增 optional-dependencies 分组）；Test: `tests/test_document_loaders.py`

**接口与分发设计 / 格式矩阵：** `DocumentLoader.load` 签名不变；`LoaderRegistry` `register/resolve` 按后缀查表，未注册抛清晰错误并提示安装哪个 extra；基础格式默认注册，重依赖格式懒注册，多后缀可映射同一 Loader。格式矩阵：txt/log/md、csv/tsv、json/yaml/xml/html、rst/org/tex——内置；pdf、docx/xlsx/pptx、odt/ods/odp、rtf/epub/mobi、eml/msg、ipynb——按对应 extra 接入。

**基础格式（P1 必做，内置）：**
- [x] **Step 1:** txt/md/log 复用 `TextDocumentLoader`（回归测试）
- [x] **Step 2:** `LoaderRegistry` 分发与未注册报错的失败测试 -> 实现跑绿
- [x] **Step 3:** csv/tsv 测试（表头/多行/空文件）-> 实现跑绿（标准库 `csv`）
- [x] **Step 4:** json/yaml/xml/html 测试 -> 实现跑绿（提取正文 + 元数据）
- [x] **Step 5:** rst/org/tex 测试 -> 实现跑绿（轻解析取纯文本）

**可拓展插件（P1 接入，按 extra，逐一 TDD）：**
- [x] **Step 6:** pdf（`documents-pdf`）：按页切分 `LoadedDocument`（页码入 metadata）；缺依赖友好报错
- [x] **Step 7:** Word `.docx`（`documents-office`）：按段落抽取
- [x] **Step 8:** Excel `.xlsx`（`documents-office`）：按 sheet 抽取（sheet 名入 metadata）
- [x] **Step 9:** PowerPoint `.pptx`（`documents-office`）：按幻灯片抽取
- [x] **Step 10:** 开放文档 `.odt`/`.ods`/`.odp`（`documents-opendocument`）
- [x] **Step 11:** 富文本/电子书 `.rtf`/`.epub`（`documents-rich`）
- [x] **Step 12:** 邮件 `.eml`/`.msg`（`documents-email`，正文 + 附件清单入 metadata）
- [x] **Step 13:** 笔记本 `.ipynb`（`documents-notebooks`，cell 拼接）
- [x] **Step 14:** 缺依赖友好报错统一测试（monkeypatch `sys.modules` 卸载各依赖，断言提示安装对应 extra）

**集成：**
- [x] **Step 15:** `ingest` 入口（CLI/API）走 `LoaderRegistry` 按后缀加载，端到端冒烟（覆盖内置 + 至少一个 extra）

**验收：**
- 内置格式（txt/md/log/csv/tsv/json/yaml/xml/html/rst/org/tex）装基础依赖即可用；重依赖格式装对应 extra 后可用，未装时清晰报错并给出 `uv sync --extra documents-pdf`（等）提示；新增格式只需新增 Loader + 注册一行，不动核心

---

### Task 2: 分块与抽取（Chunk + Extract）

**目标：** 把 `LoadedDocument` 切成 `Chunk`，再用 LLM 抽取实体/关系/声明/协变量四类 `ExtractionResult`。实体类型走团队级抽取模板（软引导）：每团队唯一一套 `ExtractionTemplate`（user 可编辑、配置文件可改），注入 prompt 引导但不限定死——模板外实体仍捕获并打标（`template_conforming`/`discovered_types`），不丢弃；新类型沉淀进模板为 review-gated（P4）。LLM 走 `LLMProvider`，测试用 `sys.modules` 桩隔离 litellm。
> [!note] 本任务引入的 `Chunk`/`Entity`/`Relation`/`Claim`/`Covariate`/`ExtractionResult`/`ExtractionTemplate` 为 P1 全局共享类型，Task 3-6 直接引用；代码已同步于 `src/calliodesmo/interfaces/{chunker,extractor}.py`。
**Files:**
- Create: `src/calliodesmo/interfaces/{chunker,extractor}.py`（`Chunker`/`Extractor` ABC + 共享类型）
- Create: `src/calliodesmo/ecl/{__init__,chunker,extractor,extraction_template}.py`（`TextChunker` 结构感知确定性切分 / `LLMExtractor` prompt 构造 + JSON 解析 + 模板引导 / `ExtractionTemplateRegistry` 从 YAML 按 team 唯一加载）
- Create: `config/extraction_templates.example.yaml`（团队模板样例）；Modify: `src/calliodesmo/config.py`（新增 `extraction_template_file`）；Test: `tests/test_{chunker,extractor,extraction_template}.py`

- [x] **Step 1:** `TextChunker` 结构感知切分（默认 `chunk_size=1200`/`overlap=100` 字符；Markdown 标题/代码块/表为原子单元，段/句兜底，贪心装填 + overlap；空文档空返；确定性；无丢失覆盖）-> 实现跑绿
- [x] **Step 2:** `Chunk` 携带 access 字段（`access_level`/`library_scope`/`owner_id`/`project_id`/`team_id` 从 `LoadedDocument.metadata` 继承，缺省 INTERNAL/personal）-> 实现跑绿
- [x] **Step 3:** `ExtractionTemplateRegistry` 失败测试：按 team 唯一（同 team 重复键 -> 加载报错）；缺文件/空文件 -> 空 registry（全 free）；`CALLIODESMO_EXTRACTION_TEMPLATE_FILE` 可覆盖路径 -> 实现跑绿
- [x] **Step 4:** `LLMExtractor` 模板软引导混合抽取：模板内实体 `template_conforming=True`；模板外实体保留打标 `False` 且类型入 `discovered_types`；`schema_mode` 为输出属性（`template-guided`/`free`）-> 实现跑绿
- [x] **Step 5:** 健壮性：LLM 返回非法 JSON / 空抽取 -> 抛 `ExtractionError`（含原始响应片段），不静默吞异常 -> 实现跑绿
- [x] **Step 6:** 来源打标：跨 chunk 抽取 `Entity.source_chunk_ids` 含出现该实体的全部 chunk -> 实现跑绿
- [x] **Step 7:** 四类齐全端到端（entities/relations/claims/covariates 均非空，桩 LLM 一次返回）-> 实现跑绿
- [x] **Step 8:** 模型经 `LLMProvider` 可切换（`CALLIODESMO_LLM_MODEL`）；`ExtractionTemplate.instructions` 作为 user 可编辑 prompt 指令注入；选型见 `docs/model-selection.md` -> 实现跑绿

**验收：**
- `TextChunker` 结构感知、确定性、无丢失覆盖；`Chunk` 携带完整 access 字段；模板为软引导：模板外实体保留 + 打 `template_conforming=False`（不 reject），类型入 `discovered_types`，`schema_mode` 为输出属性
- 新类型沉淀进模板为 review-gated（P4），P1 只捕获+打标+收集；LLM 全程经 `LLMProvider`，离线测试用 `sys.modules` 桩，零真实请求，非法输出有清晰错误

---

### Task 3: 建图、实体消解与社区检测（Cognify）

**目标：** 把 `ExtractionResult` 建成实体-关系图，做实体消解（名归一化、别名合并、多 chunk 描述汇总，把切碎实体拼回单节点），再做社区检测，对每个社区生成 LLM 摘要，输出 `list[Community]`。
> [!note] 实体消解是 P1 精度的主回收层（GraphRAG entity summarization 同思路）：切分把同一实体切碎到不同 chunk，靠此合并回单节点；社区检测在消解后的图上进行，避免重复节点错分社区。
**Files:**
- Create: `src/calliodesmo/interfaces/cognify.py`（`GraphBuilder`/`EntityResolver`/`CommunityDetector`/`CommunitySummarizer` ABC + `Community` dataclass，含 access 字段）
- Create: `src/calliodesmo/ecl/cognify.py`（`EntityRelationGraphBuilder` / `NameEntityResolver` / `LLMAliasResolver`（可选）/ `ConnectedComponentsDetector` / `NetworkxCommunityDetector`（extra）/ `LLMCommunitySummarizer`）；Test: `tests/test_cognify.py`

- [x] **Step 1:** `EntityRelationGraphBuilder` 失败测试（entities->节点、relations->边、自环/重复边过滤；最终去重留待 Step 2 消解）-> 实现跑绿
- [x] **Step 2:** `NameEntityResolver` 一等公民：名归一化（大小写/空白/标点）+ 显式别名表合并 + 跨 chunk 描述汇总为单节点；`template_conforming` 取并集（任一 conforming 则合并后 conforming）-> 实现跑绿
- [x] **Step 3:** 可选 `LLMAliasResolver`（LLM 判别名/指代合并，桩 litellm）；未启用时回退纯名归一化 -> 实现跑绿
- [x] **Step 4:** 默认 `ConnectedComponentsDetector`（零重依赖、确定性、按 name 排序可复现；在消解后的图上检测）-> 实现跑绿
- [x] **Step 5:** 可选 `NetworkxCommunityDetector`：monkeypatch 模拟 networkx 缺失 -> 友好报错 `RuntimeError("社区检测需 networkx：uv sync --extra graph-analytics")` -> 实现跑绿
- [x] **Step 6:** `LLMCommunitySummarizer`：成员实体名+描述喂 LLM 生成 `title`+`summary`（桩 litellm）-> 实现跑绿
- [x] **Step 7:** Cognify 串联（build -> resolve -> detect -> summarize -> `list[Community]`，access 字段从 chunk 继承）端到端 -> 实现跑绿

**验收：**
- 实体消解为一等公民：名归一化 + 别名合并 + 多 chunk 描述汇总；碎片实体合并为单节点（断言合并前后节点数）
- 默认社区检测零重依赖、确定性可复现；networkx 路径缺依赖友好报错；社区摘要经 `LLMProvider`，离线测试用桩；`Community` 携带 access 字段供 Task 4 落库与 P2 检索过滤

---

### Task 4: 三层存储与落库（Load）

**目标：** 引入 `VectorStore`/`GraphStore`/`CommunityStore` 三抽象接口 + 确定性内存默认实现；把 `Chunk`（嵌入向量）+ `ExtractionResult`（图）+ `Community`（摘要）落个人库，全程带 access 字段供 `AccessContext` 过滤。
> [!note] pgvector/Neo4j 真后端列为 optional extra（容器验证，与 BGE-M3 同策略）；P1 默认内存实现保证离线可测、CI 可跑。
**Files:**
- Create: `src/calliodesmo/interfaces/{vector_store,graph_store,community_store}.py`（ABC + `ChunkRecord`/`VectorHit`/`EntityRecord`/`RelationRecord`/`CommunityRecord`）
- Create: `src/calliodesmo/stores/visibility.py`（`visible_to(record, ctx)` 谓词）；`src/calliodesmo/providers/{in_memory_vector_store,in_memory_graph_store,in_memory_community_store}.py`；`src/calliodesmo/ecl/load.py`（`LoadService`）
- Test: `tests/test_visibility.py`、`tests/test_in_memory_stores.py`、`tests/test_load.py`

**可见性谓词（`stores/visibility.py`）：** `visible_to(record, ctx)`：`ctx.clearance` 低于 access 拒见；按 `library_scope` 匹配 personal/project/team 归属（owner/project/team）。
**接口签名：** `VectorStore`（`upsert_chunks`/`search(query_vector, top_k, access)`）；`GraphStore`（`upsert_graph`/`get_entity`/`neighbors`）；`CommunityStore`（`upsert_communities`/`list_communities`），均带 `access` 过滤；完整签名见 `src/calliodesmo/interfaces/`。

- [x] **Step 1:** `visible_to` 正反例（clearance 有序比较 + personal/project/team 三 scope 可见性 + 越权拒见）-> 实现跑绿
- [x] **Step 2:** `InMemoryVectorStore` upsert + 余弦相似 `search`（按 `visible_to` 过滤、`top_k` 截断、score 降序、确定性平局按 chunk_id 排序）-> 实现跑绿
- [x] **Step 3:** `InMemoryGraphStore` upsert（同 name 覆盖）+ `get_entity`/`neighbors`（按 `visible_to` 过滤；`EntityRecord` 含 `template_conforming` 供 P2 过滤）-> 实现跑绿
- [x] **Step 4:** `InMemoryCommunityStore` upsert + `list_communities`（按 `visible_to` 过滤、按 level/title 排序）-> 实现跑绿
- [x] **Step 5:** `LoadService`：Chunk 经 EmbeddingProvider 嵌入 -> `ChunkRecord`；`ExtractionResult` -> GraphStore；`Community` -> CommunityStore；access 字段继承，端到端断言三 store 有数据 -> 实现跑绿
- [x] **Step 6:** 幂等 upsert（同 `chunk_id`/实体 name 二次写入覆盖而非重复）-> 实现跑绿

**验收：**
- 三 store 接口 + 内存默认实现齐全，余弦相似/图邻居/社区列表均按 `AccessContext` 过滤；`LoadService` 把 ECL 产物落个人库（personal scope + owner_id），access 字段贯通
- 内存实现确定性可复现；pgvector/Neo4j 真后端列为 extra（不阻塞 P1 验收）

---

### Task 5: 文档社区自动派生（选项 A）

**目标：** 选项 A 自动派生：在 Task 3 实体社区之上，按文档来源聚合一层“文档级”社区（level=1），便于按文档检索与导航。
**Files:**
- Create: `src/calliodesmo/ecl/community_deriver.py`（`DocumentCommunityDeriver`）；Test: `tests/test_community_deriver.py`

- [x] **Step 1:** 按 `doc_id` 聚合其 chunk 关联实体 -> LLM 生成文档级 `title`+`summary`（桩 litellm）-> 实现跑绿
- [x] **Step 2:** 派生社区写入 `CommunityStore`（`level=1`、`member_entity_names` 为该文档实体集合、access 字段继承）-> 实现跑绿
- [x] **Step 3:** 增量：新文档 ingest 只新增本档社区，不动已有文档社区 -> 实现跑绿

**验收：**
- 文档社区自动派生，level 区分实体/文档两层；增量安全，可重复 ingest 不重复派生

---

### Task 6: IndexingEngine 与 `ingest` CLI（串联 Task 1-5）

**目标：** 实现 `IndexingEngine` 抽象（六接口之一）+ 默认 `ECLIndexingEngine` 串联 Load->Extract->Cognify->Load->社区派生；CLI `calliodesmo ingest <path>` 端到端建图落个人库并记审计。
**Files:**
- Create: `src/calliodesmo/interfaces/indexing_engine.py`（`IndexingEngine` ABC + `IngestStats`）；Create: `src/calliodesmo/ecl/engine.py`（`ECLIndexingEngine`，依赖注入 loader/embedding/llm/chunker/extractor（含模板 registry）/cognify/三 store/deriver）
- Modify: `src/calliodesmo/cli.py`（新增 `ingest` 命令）；`src/calliodesmo/models.py`（如需 ORM 持久化补表）；Test: `tests/test_{indexing_engine,ingest_cli}.py`

- [x] **Step 1:** `IndexingEngine` 接口 + `ECLIndexingEngine` 依赖注入构造（loader/embedding/llm/chunker/extractor/模板 registry/cognify/三 store/deriver）-> 实现跑绿
- [x] **Step 2:** 端到端 ECL（桩 LLM + HashEmbedding + 内存三 store + TextDocumentLoader）：doc->chunks->extraction（模板软引导，模板外打标不拒）->graph->communities->三 store 落库 + `IngestStats` 计数正确 -> 实现跑绿
- [x] **Step 3:** `AccessContext` 限定 personal scope + `owner_id=ctx.user_id` 落库（越权不可见断言）-> 实现跑绿
- [x] **Step 4:** `ingest` CLI（Typer）：路径参数 + 默认引擎（内存 stores + HashEmbedding + LiteLLMProvider）+ 打印 `IngestStats`；`CliRunner` 断言退出码 0 与统计文本 -> 实现跑绿
- [x] **Step 5:** 失败友好报错（路径不存在 -> 退出码非 0；loader 未注册 -> 提示安装 extra；LLM 缺 key -> 指引 `CALLIODESMO_LLM_API_KEY`）-> 实现跑绿
- [x] **Step 6:** 审计：ingest 动作经 `record_audit(action="ingest", resource_type="document", detail={stats}, source="cli")` 落 `AuditLog` -> 实现跑绿

**验收：**
- `ECLIndexingEngine` 串联 Task 1-5，端到端离线跑通（桩 LLM + Hash 嵌入 + 内存 stores）；`calliodesmo ingest <path>` 一键建图落个人库，输出统计并记审计；越权记录不可见（personal scope 隔离验证）

---

### Task 7: 实体档案卡自动生成（ProfileCard）

**目标：** 从已消解的 `Entity` + 图邻居 + Covariate 确定性聚合出结构化档案卡（`ProfileCard`），作为用户侧展示单元。结构化字段（别名/职务/组织/关联人/时间跨度/证据）是图与 Covariate 的确定性投影，可进模型上下文增强可读性与精度；叙述字段 `narrative` 为可选 LLM 生成概述，按“摘要不进模型”约束不进检索/rerank 链路，仅供人读。P1 只做自动生成（用户编辑/版本/审核/推送归 P4）；数据模型预留 `provenance`/`locked` 标记字段，不实现编辑逻辑。
> [!note] 与 Task 2 Step 4 的区别：Task 2/3 从 chunk 原文抽取实体并消解合并（产出 `Entity`）；Task 7 从已合并 Entity + 图邻居 + Covariate 聚合结构化画像（产出 `ProfileCard`），只做二手聚合，不重复抽取。
**Files:**
- Create: `src/calliodesmo/interfaces/profile_card.py`（`ProfileCard`/`ProfileField`/`FieldProvenance` + `ProfileCardDeriver` ABC）；`src/calliodesmo/ecl/profile_card_deriver.py`（`DeterministicProfileCardDeriver`：GraphStore.neighbors + Covariate + Entity 聚合；可选 `narrative` 经 LLM 生成但标记非检索用）
- Create: `src/calliodesmo/stores/profile_card_store.py`（`InMemoryProfileCardStore`，与三 store 同构，按 `visible_to` 过滤）；Modify: `src/calliodesmo/ecl/engine.py`（可选串联档案卡生成，不阻塞主流程；`IngestStats` 增 `profile_cards`）；Test: `tests/test_profile_card.py`

- [x] **Step 1:** `ProfileCard`/`ProfileField`/`FieldProvenance` 数据模型失败测试（字段齐全、默认值、access 继承）-> 实现跑绿
- [x] **Step 2:** `DeterministicProfileCardDeriver` 纯确定性聚合：aliases（消解别名）/associates（person 类型邻居）/organization（组织类 Relation target）/role 与 timespan（Covariate 或 chunk 时间元数据）；**不调 LLM**，全为图/Covariate 客观投影 -> 实现跑绿
- [x] **Step 3:** 结构化字段可进模型上下文（序列化后喂 LLM 可读性优于自由 description；narrative 为 None 时不进任何检索输入）-> 实现跑绿
- [x] **Step 4:** 可选 narrative：经 `LLMProvider` 生成（桩 litellm），`provenance=AUTO`；不进 VectorStore/GraphStore/rerank，仅存 ProfileCardStore 供展示 -> 实现跑绿
- [x] **Step 5:** `InMemoryProfileCardStore`：upsert（同 entity_name 覆盖）+ 按 `visible_to` 过滤的 list/get；幂等 -> 实现跑绿
- [x] **Step 6:** `ECLIndexingEngine` 可选串联：ingest 完成后触发档案卡生成写入 store；`IngestStats` 增 `profile_cards`；开关默认开，关闭不影响主链路 -> 实现跑绿
- [x] **Step 7:** 来源标记预留：`provenance`/`locked`/`version` 字段存在且 P1 恒 `AUTO`/`False`/`1`；断言不覆盖 `locked=True` 字段（P4 编辑接口预留）-> 实现跑绿

**验收：**
- `ProfileCard` 结构化字段从图+Covariate 确定性聚合，零 LLM 调用（narrative 除外）；结构化字段可进模型上下文，narrative 不进检索/rerank/生成链路，仅供人读
- 与 Task 2/3 不重复：后者抽取消解产出 `Entity`，本任务聚合产出 `ProfileCard`；`provenance`/`locked`/`version` 预留用户编辑接口（归 P4 review-gated）；Store 按 `visible_to` 过滤

---

## 精度策略与跨阶段改进（前瞻）
> [!note] P1 设计评审的精度担忧与改进方向；P1 落地“过门槛”部分，更重的留待对应阶段，全部经可插拔接口接入，不动核心。
**精度投资优先级（ROI 排序，非按阶段）：**
1. **评估 harness（贯穿项，最大缺口）**——起建 golden Q&A 集 + 指标脚本（忠实度/上下文召回/答案相关性，RAGAS 式），每次改动跑回归。
2. **检索精度（P2/P5，第一杠杆）**——`SparseIndex`(BM25) + `Reranker` 接口；稠密∪稀疏∪图 -> RRF 融合 -> 交叉编码器重排。
3. **实体消解（P1 Task 3，第二杠杆）**——名归一化 + 别名合并 + 多 chunk 描述汇总（已落地为一等公民）。
4. **抽取质量（P1 Task 2）**——团队软引导模板（user 可编辑）+ prompt 工程 + 模型可切换（已纳入）。
5. **切分（中游杠杆）**——结构感知 + overlap 过门槛 + size 调参（已落地）；语义/分层切分推迟 P5。
**GIGO 缓解与留待后续（本阶段已做 / 不阻塞 P1 验收）：** 结构感知切分 + 实体消解 + 全程 `source_chunk_ids` 溯源。留待：混合检索 + 重排（P2/P5）；分层切分 + 上下文富化（P5）；跨 chunk 关系补抽/别名歧义精解（P8 硬化）；ANN 索引支撑 ≥50 万（P9，接口已预留）；L0/L1 分层摘要（P2/P5，P1 仅预留 `Chunk.summary` 字段，参考 OpenViking 分层理念非目录递归）。
**依赖与风险（P1 全量）：**
- 文档解析重依赖按 extra 分组；CI 默认只装基础 + `sys.modules` 桩测接口，真机验证用 `uv sync --extra ...` 组合。PDF 仅支持文本型（扫描需 OCR 不在 P1 范围）；旧二进制 Office/Keynote/Visio 需 LibreOffice(headless)/antiword，`pandoc` 兜底。
- 三层存储接口 + 确定性内存默认实现保证离线可测；pgvector/Neo4j 真后端列 extra（内存实现非持久，dev/test 重建即恢复，与 P0 SQLite/Postgres 同构）。社区检测默认 `ConnectedComponentsDetector`（零重依赖）；networkx Louvain/Leiden 列 extra（`graph-analytics`），缺依赖友好报错；GraphRAG 库式集成列 extra，P1 用自建 Cognify。
- 抽取/摘要 LLM 真实运行需 API key；离线测试全用 `sys.modules` 桩，零真实请求。模板经 `CALLIODESMO_EXTRACTION_TEMPLATE_FILE` 按 team 唯一加载、软引导不拒模板外实体；新类型沉淀 review-gated 于 P4。版本钉制 litellm `>=1.85,<1.91`（>=1.93 无 Windows wheel）。
- 精度边界（如实声明）：跨 chunk 关系抽取、别名/指代歧义在 P1 MVP 不完美；靠结构感知切分 + 实体消解 + `source_chunk_ids` 溯源缓解，P8 证据验证硬化。评估 harness 从 P1/P2 起建，P1 验证以功能测试 + 离线桩为主，质量评测自 P2 接入。

> 精简于 2026-08（文档重构）：删除嵌入代码块，保留任务/勾选结构。
