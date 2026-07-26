---
title: P1 ECL 管线 MVP 实施计划
type: phase-plan
phase: P1
tags:
  - plan/phase
created: 2026-07-26
---
# P1 ECL 管线 MVP 实施计划

> **For agentic workers:** 按 Task 顺序逐任务执行；步骤用 checkbox（`- [ ]`）跟踪。每个 Task 内按 TDD：先写失败测试 -> 实现 -> 跑绿 -> 提交。关联：[[docs/plans/roadmap|年计划]] / [[docs/plans/phases/P0-scaffolding|P0]] / [[docs/plans/monthly/2026-08|2026-08 月计划]]。

**Goal:** 打通 ECL 主链路（Extract -> Cognify -> Load），实现“数据进 -> 建图 -> 落个人库”。Extract 入口支持**多格式文档解析**：纯文本/标记/表格/结构化文本等基础格式内置，PDF、Office 全家桶、开放文档、富文本/电子书、邮件、Jupyter 笔记本 等以可拓展插件方式按需接入。

**Architecture:** `DocumentLoader` 抽象接口（P0 已立）保持不变；每种/每类文档格式一个具体 Loader（插件），按后缀分发。基础格式默认内置；重依赖格式列为可选 extra（`[project.optional-dependencies]`），懒加载，缺依赖时友好报错（沿用 FlagEmbedding 模式）。`LoaderRegistry` 按 `source.suffix` 选择实现；新增格式只需新增 Loader + 注册，不动核心。Cognify 走 GraphRAG 库式集成 + Leiden；Load 写个人库三层数据。

**Tech Stack（P0 基础上追加）:**
- 基础格式：标准库 `csv`/`json`/`html.parser`/`xml.etree`；`PyYAML`；纯文本/Markdown 已有
- 可选 extra `documents-pdf`：`pypdf`（备选 `pdfplumber`/`pymupdf`）
- 可选 extra `documents-office`：`python-docx`（Word）/ `openpyxl`（Excel）/ `python-pptx`（PowerPoint）
- 可选 extra `documents-opendocument`：`odfpy`（ODT/ODS/ODP）
- 可选 extra `documents-rich`：`striprtf`（RTF）/ `ebooklib`（EPUB）
- 可选 extra `documents-email`：标准库 `email`（.eml）+ `extract-msg`（.msg）
- 可选 extra `documents-notebooks`：`nbformat`（.ipynb）
- 可选后端：`pandoc` / `LibreOffice(headless)`（旧二进制 office 与格式转换兜底）
- 测试：`pytest` + 临时样例文件 + `monkeypatch`/`sys.modules` 桩隔离重依赖

---

### Task 1: 文档解析与加载器（多格式 + 可拓展插件）

**目标：** P1 阶段可解析多种基础格式，并按可拓展插件接入 PDF、Office 全家桶及更多富文档格式。

**Files:**
- Modify: `src/calliodesmo/providers/text_loader.py`（保留 txt/md，抽公共逻辑）
- Create: `src/calliodesmo/providers/structured_loader.py`（csv/tsv/json/yaml/xml/html）
- Create: `src/calliodesmo/providers/markup_loader.py`（rst/org/tex）
- Create: `src/calliodesmo/providers/pdf_loader.py`（extra: documents-pdf）
- Create: `src/calliodesmo/providers/office_loader.py`（extra: documents-office，docx/xlsx/pptx）
- Create: `src/calliodesmo/providers/opendocument_loader.py`（extra: documents-opendocument，odt/ods/odp）
- Create: `src/calliodesmo/providers/rich_loader.py`（extra: documents-rich，rtf/epub/mobi）
- Create: `src/calliodesmo/providers/email_loader.py`（extra: documents-email，eml/msg）
- Create: `src/calliodesmo/providers/notebook_loader.py`（extra: documents-notebooks，ipynb）
- Create: `src/calliodesmo/providers/registry.py`（按后缀分发 + 注册表）
- Modify: `pyproject.toml`（新增 optional-dependencies 分组）
- Test: `tests/test_document_loaders.py`

**接口与分发设计：**
- `DocumentLoader.load(source) -> list[LoadedDocument]` 签名不变
- `LoaderRegistry`：`register(suffix, loader)` / `resolve(source) -> DocumentLoader`；按后缀查表，未注册抛清晰错误并提示安装哪个 extra
- 基础格式默认注册；重依赖格式懒注册（用到且依赖在时注册）；多后缀可映射同一 Loader

**支持的格式矩阵：**

| 类别           | 格式                                           | 接入                             | 候选库/方式                         |
| ------------ | -------------------------------------------- | ------------------------------ | ------------------------------ |
| 纯文本/Markdown | `.txt` `.log` `.md` `.markdown`              | 内置                             | 已有 `TextDocumentLoader`        |
| 表格           | `.csv` `.tsv`                                | 内置                             | 标准库 `csv`                      |
| 结构化文本        | `.json` `.yaml`/`.yml` `.xml` `.html`/`.htm` | 内置                             | 标准库 + `PyYAML`                 |
| 标记语言         | `.rst` `.org` `.tex`                         | 内置（轻解析取纯文本）                    | 标准库/正则                         |
| PDF          | `.pdf`（文本型）                                  | extra `documents-pdf`          | `pypdf`（备选 pdfplumber/pymupdf） |
| Word         | `.docx`                                      | extra `documents-office`       | `python-docx`                  |
| Excel        | `.xlsx`                                      | extra `documents-office`       | `openpyxl`                     |
| PowerPoint   | `.pptx`                                      | extra `documents-office`       | `python-pptx`                  |
| 开放文档         | `.odt` `.ods` `.odp`                         | extra `documents-opendocument` | `odfpy`                        |
| 富文本/电子书      | `.rtf` `.epub` `.mobi`                       | extra `documents-rich`         | `striprtf`/`ebooklib`          |
| 邮件           | `.eml` `.msg`                                | extra `documents-email`        | 标准库 `email`/`extract-msg`      |
| 笔记本          | `.ipynb`                                     | extra `documents-notebooks`    | `nbformat`                     |

**基础格式（P1 必做，内置）：**
- [ ] **Step 1:** txt/md/log 复用 `TextDocumentLoader`（回归测试）
- [ ] **Step 2:** 写 `LoaderRegistry` 分发与未注册报错的失败测试 -> 实现跑绿
- [ ] **Step 3:** csv/tsv 测试（表头/多行/空文件）-> 实现跑绿（标准库 `csv`）
- [ ] **Step 4:** json/yaml/xml/html 测试 -> 实现跑绿（提取正文 + 元数据）
- [ ] **Step 5:** rst/org/tex 测试 -> 实现跑绿（轻解析取纯文本）

**可拓展插件（P1 接入，按 extra，逐一 TDD）：**
- [ ] **Step 6:** pdf（`documents-pdf`）：按页切分 `LoadedDocument`（页码入 metadata）；缺依赖友好报错
- [ ] **Step 7:** Word `.docx`（`documents-office`）：按段落抽取
- [ ] **Step 8:** Excel `.xlsx`（`documents-office`）：按 sheet 抽取（sheet 名入 metadata）
- [ ] **Step 9:** PowerPoint `.pptx`（`documents-office`）：按幻灯片抽取
- [ ] **Step 10:** 开放文档 `.odt`/`.ods`/`.odp`（`documents-opendocument`）
- [ ] **Step 11:** 富文本/电子书 `.rtf`/`.epub`（`documents-rich`）
- [ ] **Step 12:** 邮件 `.eml`/`.msg`（`documents-email`，正文 + 附件清单入 metadata）
- [ ] **Step 13:** 笔记本 `.ipynb`（`documents-notebooks`，cell 拼接）
- [ ] **Step 14:** 缺依赖友好报错统一测试（monkeypatch `sys.modules` 卸载各依赖，断言提示安装对应 extra）

**集成：**
- [ ] **Step 15:** `ingest` 入口（CLI/API）走 `LoaderRegistry` 按后缀加载，端到端冒烟（覆盖内置 + 至少一个 extra）

**验收：**
- 内置格式（txt/md/log/csv/tsv/json/yaml/xml/html/rst/org/tex）装基础依赖即可用
- 重依赖格式装对应 extra 后可用；未装 extra 时清晰报错并给出 `uv sync --extra documents-pdf`（等）提示
- 新增格式只需新增 Loader + 注册一行，不动核心

---

### Task 2: 分块与抽取（Chunk + Extract）

**目标：** 把 Task 1 的 `LoadedDocument` 切成 `Chunk`，再用 LLM 抽取**实体/关系/声明/协变量四类**结构化 `ExtractionResult`。实体类型受**团队级硬约束**：每个团队有且仅有一套 `EntitySchema`（由配置文件定义、可改），抽取时严格校验（schema 外类型实体拒绝并记入 `rejected_entities`），未配置 schema 的团队走 Schema-Free。LLM 走 `LLMProvider`，测试用 `sys.modules` 桩隔离 litellm（沿用 P0 `test_llm_provider`）。

> [!note] 本任务引入的 `Chunk`/`Entity`/`Relation`/`Claim`/`Covariate`/`ExtractionResult`/`EntitySchema` 为 P1 全局共享类型，Task 3-6 直接引用。

**Files:**
- Create: `src/calliodesmo/interfaces/chunker.py`（`Chunker` ABC + `Chunk` dataclass）
- Create: `src/calliodesmo/interfaces/extractor.py`（`Extractor` ABC + `ExtractionResult`/`Entity`/`Relation`/`Claim`/`Covariate`/`EntitySchema`）
- Create: `src/calliodesmo/ecl/__init__.py`
- Create: `src/calliodesmo/ecl/chunker.py`（`TextChunker`，size+overlap，确定性）
- Create: `src/calliodesmo/ecl/extractor.py`（`LLMExtractor`，prompt 构造 + JSON 解析 + 硬约束校验）
- Create: `src/calliodesmo/ecl/entity_schema.py`（`EntitySchemaRegistry`：从 YAML 配置加载，按 team 唯一）
- Create: `config/entity_schemas.example.yaml`（团队 schema 样例）
- Modify: `src/calliodesmo/config.py`（新增 `entity_schema_file`，默认 `config/entity_schemas.yaml`）
- Test: `tests/test_chunker.py`、`tests/test_extractor.py`、`tests/test_entity_schema.py`

**共享类型（`interfaces/extractor.py`）：**

```python
@dataclass
class Chunk:
    chunk_id: str           # f"{doc_id}#{ordinal}"
    doc_id: str
    content: str
    ordinal: int
    metadata: dict[str, Any]
    access_level: ClearanceLevel
    library_scope: LibraryScope
    owner_id: uuid.UUID | None
    project_id: uuid.UUID | None
    team_id: uuid.UUID | None

@dataclass
class Entity:
    name: str
    type: str | None
    description: str
    source_chunk_ids: list[str]

@dataclass
class Relation:
    source: str              # 实体 name
    target: str
    type: str | None
    description: str
    source_chunk_ids: list[str]

@dataclass
class Claim:
    text: str
    entity_name: str | None
    source_chunk_ids: list[str]

@dataclass
class Covariate:
    name: str
    entity_name: str
    value: str
    source_chunk_ids: list[str]

@dataclass
class EntitySchema:
    """团队级实体类型硬约束：每团队有且仅有一套，由配置文件定义、可改。"""
    team: str                       # team_id 字符串
    entity_types: list[str]         # 允许的实体类型白名单
    type_descriptions: dict[str, str] = field(default_factory=dict)

@dataclass
class ExtractionResult:
    entities: list[Entity]
    relations: list[Relation]
    claims: list[Claim]
    covariates: list[Covariate]
    schema_mode: str                # 输出属性：记录实际应用模式 "schema-free" | "schema-constraint"
    rejected_entities: list[Entity] = field(default_factory=list)  # 硬约束拒绝的 schema 外实体
```

**接口（`interfaces/chunker.py`、`interfaces/extractor.py`）：**

```python
class Chunker(ABC):
    @abstractmethod
    async def chunk(self, doc: LoadedDocument) -> list[Chunk]: ...

class Extractor(ABC):
    @abstractmethod
    async def extract(
        self, chunks: list[Chunk], *, access: AccessContext,
    ) -> ExtractionResult: ...
```

> [!note] `entity_types` 不再是调用方自由传入的参数，而由 `EntitySchemaRegistry` 按 ingest 所属团队从配置文件解析（每团队唯一）。`access` 提供 team 上下文：恰好一个团队且已配置 schema -> 硬约束；无 team 或未配置 -> Schema-Free；P4 团队库 ingest 时 target team 唯一。

- [ ] **Step 1:** `TextChunker` 结构感知切分失败测试（默认 `chunk_size=1200`/`overlap=100` 字符；先按 Markdown 标题/代码块/表为原子单元，段/句兜底，贪心装填 + overlap 接缝；空文档返空；确定性；无丢失覆盖；`len<=chunk_size` 除非不可分单元；相邻 chunk 共享 overlap）-> 实现跑绿
- [ ] **Step 2:** `Chunk` 携带 access 字段（`access_level`/`library_scope`/`owner_id`/`project_id`/`team_id` 从 `LoadedDocument.metadata` 继承，缺省 INTERNAL/personal）测试 -> 实现跑绿
- [ ] **Step 3:** `EntitySchemaRegistry` 失败测试：从 YAML 加载 `team -> EntitySchema`；**每团队唯一**（同 team 重复键配置 -> 加载报错）；缺文件/空文件 -> registry 为空（全 schema-free）；`CALLIODESMO_ENTITY_SCHEMA_FILE` 可覆盖路径 -> 实现跑绿
- [ ] **Step 4:** `LLMExtractor` Schema-Free：当前 ingest 无团队 schema -> prompt 不含类型约束 -> 桩 litellm 返回合法 JSON -> 解析为 `ExtractionResult(schema_mode="schema-free", rejected_entities=[])` 测试 -> 实现跑绿
- [ ] **Step 5:** `LLMExtractor` Schema-Constraint **硬约束**：团队 schema 已配置 -> prompt 注入允许类型白名单（严格指令）-> 桩 litellm 返回"合规 + 越界类型"混合实体 -> 解析后**仅保留 `entity.type ∈ schema.entity_types` 的实体，越界实体入 `rejected_entities` 并记录原因**；`schema_mode="schema-constraint"` 测试 -> 实现跑绿
- [ ] **Step 6:** 健壮性：LLM 返回非法 JSON / 空抽取 -> 抛 `ExtractionError`（含原始响应片段），不静默吞异常测试 -> 实现跑绿
- [ ] **Step 7:** 来源打标：跨 chunk 抽取的 `Entity.source_chunk_ids` 含所有出现该实体的 chunk ordinal 测试 -> 实现跑绿
- [ ] **Step 8:** 四类齐全端到端（entities/relations/claims/covariates 均非空，桩 LLM 一次返回）测试 -> 实现跑绿
- [ ] **Step 9:** 抽取 prompt 模板可配置（schema-free / schema-constraint 两套外部模板，经配置/参数注入，不硬编码）+ 模型经 `LLMProvider` 可切换（`CALLIODESMO_LLM_MODEL`）；prompt 工程与模型选型作为精度杠杆，单测覆盖 prompt 构造与模型参数透传 -> 实现跑绿

**验收：**
- `TextChunker` 结构感知（标题/代码块/表为原子 + 段句兜底 + overlap）、确定性、无丢失覆盖；`Chunk` 携带完整 access 字段
- `EntitySchemaRegistry` 按 team 唯一、配置文件可改；同 team 重复键加载报错
- Schema-Constraint 为**硬约束**：schema 外类型实体进 `rejected_entities` 而非混入结果；schema-free / schema-constraint 由配置驱动，`schema_mode` 为输出属性
- LLM 全程经 `LLMProvider`，离线测试用 `sys.modules` 桩，零真实请求
- 非法 LLM 输出有清晰错误，不静默吞异常
- 抽取 prompt 模板可配置、模型经 `LLMProvider` 可切换；prompt 工程与模型选型作为精度杠杆

---

### Task 3: 建图、实体消解与社区检测（Cognify）

**目标：** 把 `ExtractionResult` 建成实体-关系图，**做实体消解**（把切分/抽取造成的碎片实体拼回去--名归一化、别名合并、多 chunk 描述汇总），再做社区检测，对每个社区生成 LLM 摘要，输出 `list[Community]`。

> [!note] 实体消解是 P1 精度的主回收层：切分把同一实体切碎到不同 chunk，靠这一步合并回单节点（GraphRAG 内置 entity summarization 同思路）。社区检测在合并后的图上进行，避免重复节点错分社区。

**Files:**
- Create: `src/calliodesmo/interfaces/cognify.py`（`GraphBuilder`/`EntityResolver`/`CommunityDetector`/`CommunitySummarizer` ABC + `Community` dataclass）
- Create: `src/calliodesmo/ecl/cognify.py`（`EntityRelationGraphBuilder` / `NameEntityResolver` / `LLMAliasResolver`（可选）/ `ConnectedComponentsDetector` / `NetworkxCommunityDetector`（extra）/ `LLMCommunitySummarizer`）
- Test: `tests/test_cognify.py`

**共享类型（`interfaces/cognify.py`）：**

```python
@dataclass
class Community:
    community_id: str
    level: int                       # 0=实体社区，1=文档社区（Task 5）
    title: str
    summary: str
    member_entity_names: list[str]
    metadata: dict[str, Any]
    access_level: ClearanceLevel
    library_scope: LibraryScope
    owner_id: uuid.UUID | None
    project_id: uuid.UUID | None
    team_id: uuid.UUID | None
```

- [ ] **Step 1:** `EntityRelationGraphBuilder` 失败测试（entities->节点、relations->边、自环/重复边过滤；最终去重留待 Step 2 消解）-> 实现跑绿
- [ ] **Step 2:** `EntityResolver` 一等公民：`NameEntityResolver`（名归一化：大小写/空白/标点 + 显式别名表合并 + 跨 chunk 描述汇总为单节点）测试 -> 实现跑绿
- [ ] **Step 3:** 可选 `LLMAliasResolver`：LLM 判别名/指代合并（如 "OpenAI"=="OpenAI Inc."，桩 litellm）；未启用时回退纯名归一化测试 -> 实现跑绿
- [ ] **Step 4:** `CommunityDetector` 接口 + 默认 `ConnectedComponentsDetector`（零重依赖、确定性、按 name 排序可复现；在**消解后**的图上检测）测试 -> 实现跑绿
- [ ] **Step 5:** 可选 `NetworkxCommunityDetector`（extra）：`monkeypatch` 模拟 networkx 缺失 -> 友好报错 `RuntimeError("社区检测需 networkx：uv sync --extra graph-analytics")` 测试 -> 实现跑绿
- [ ] **Step 6:** `LLMCommunitySummarizer`：对社区成员实体名+描述喂 LLM 生成 `title`+`summary`（桩 litellm）测试 -> 实现跑绿
- [ ] **Step 7:** Cognify 串联（build -> **resolve** -> detect -> summarize -> `list[Community]`，access 字段从 chunk 继承）端到端测试 -> 实现跑绿

**验收：**
- 实体消解为一等公民：名归一化 + 别名合并 + 多 chunk 描述汇总；碎片实体合并为单节点（断言合并前后节点数）
- 默认社区检测零重依赖、确定性可复现；networkx 路径缺依赖友好报错
- 社区摘要经 `LLMProvider`，离线测试用桩
- `Community` 携带 access 字段，供 Task 4 落库与 P2 检索过滤

---

### Task 4: 三层存储与落库（Load）

**目标：** 引入 `VectorStore`/`GraphStore`/`CommunityStore` 三抽象接口（路线图"六个可插拔接口"之 P1 部分）+ 确定性内存默认实现；把 `Chunk`（嵌入向量）+ `ExtractionResult`（图）+ `Community`（摘要）落个人库，全程带 access 字段供 `AccessContext` 过滤。

> [!note] pgvector/Neo4j 真后端列为 optional extra（容器验证），与 BGE-M3 同策略；P1 默认内存实现保证离线可测、CI 可跑。

**Files:**
- Create: `src/calliodesmo/interfaces/vector_store.py`（`VectorStore` ABC + `ChunkRecord`/`VectorHit`）
- Create: `src/calliodesmo/interfaces/graph_store.py`（`GraphStore` ABC + `EntityRecord`/`RelationRecord`）
- Create: `src/calliodesmo/interfaces/community_store.py`（`CommunityStore` ABC + `CommunityRecord`）
- Create: `src/calliodesmo/stores/__init__.py`
- Create: `src/calliodesmo/stores/visibility.py`（`visible_to(record, ctx)` 谓词）
- Create: `src/calliodesmo/providers/in_memory_vector_store.py` / `in_memory_graph_store.py` / `in_memory_community_store.py`
- Create: `src/calliodesmo/ecl/load.py`（`LoadService`：把 ECL 中间产物写入三 store）
- Test: `tests/test_visibility.py`、`tests/test_in_memory_stores.py`、`tests/test_load.py`

**可见性谓词（`stores/visibility.py`）：**

```python
def visible_to(record, ctx: AccessContext) -> bool:
    if ctx.clearance < record.access_level:
        return False
    match record.library_scope:
        case LibraryScope.PERSONAL:
            return record.owner_id == ctx.user_id
        case LibraryScope.PROJECT:
            return record.project_id in ctx.project_ids
        case LibraryScope.TEAM:
            return record.team_id in ctx.team_ids
    return False
```

**接口签名：**

```python
class VectorStore(ABC):
    @abstractmethod
    async def upsert_chunks(self, chunks: list[ChunkRecord]) -> None: ...
    @abstractmethod
    async def search(self, query_vector: list[float], *, top_k: int,
                     access: AccessContext) -> list[VectorHit]: ...

class GraphStore(ABC):
    @abstractmethod
    async def upsert_graph(self, entities: list[EntityRecord], relations: list[RelationRecord]) -> None: ...
    @abstractmethod
    async def get_entity(self, name: str, *, access: AccessContext) -> EntityRecord | None: ...
    @abstractmethod
    async def neighbors(self, name: str, *, access: AccessContext) -> tuple[list[EntityRecord], list[RelationRecord]]: ...

class CommunityStore(ABC):
    @abstractmethod
    async def upsert_communities(self, communities: list[CommunityRecord]) -> None: ...
    @abstractmethod
    async def list_communities(self, *, access: AccessContext) -> list[CommunityRecord]: ...
```

- [ ] **Step 1:** `visible_to` 正反例（clearance 有序比较 + personal/project/team 三 scope 可见性 + 越权拒见）测试 -> 实现跑绿
- [ ] **Step 2:** `VectorStore` 接口 + `ChunkRecord`；`InMemoryVectorStore` upsert + 余弦相似 `search`（按 `visible_to` 过滤、`top_k` 截断、score 降序、确定性平局按 chunk_id 排序）测试 -> 实现跑绿
- [ ] **Step 3:** `GraphStore` 接口 + `EntityRecord`/`RelationRecord`；`InMemoryGraphStore` upsert（同 name 覆盖）+ `get_entity`/`neighbors`（按 `visible_to` 过滤）测试 -> 实现跑绿
- [ ] **Step 4:** `CommunityStore` 接口 + `CommunityRecord`；`InMemoryCommunityStore` upsert + `list_communities`（按 `visible_to` 过滤、按 level/title 排序）测试 -> 实现跑绿
- [ ] **Step 5:** `LoadService`：`Chunk` 经 `EmbeddingProvider` 嵌入 -> `ChunkRecord` -> `VectorStore`；`ExtractionResult` -> `GraphStore`；`Community` -> `CommunityStore`；access 字段从 doc 继承，端到端断言三 store 有数据测试 -> 实现跑绿
- [ ] **Step 6:** 幂等 upsert（同 `chunk_id`/实体 name 二次写入覆盖而非重复）测试 -> 实现跑绿

**验收：**
- 三 store 接口 + 内存默认实现齐全，余弦相似/图邻居/社区列表均按 `AccessContext` 过滤
- `LoadService` 把 ECL 产物落个人库（personal scope + owner_id），access 字段贯通
- 内存实现确定性可复现；pgvector/Neo4j 真后端列为 extra（不阻塞 P1 验收）

---

### Task 5: 文档社区自动派生（选项 A）

**目标：** 选项 A 自动派生：在 Task 3 实体社区之上，按文档来源聚合一层"文档级"社区（level=1），便于按文档检索与导航。

**Files:**
- Create: `src/calliodesmo/ecl/community_deriver.py`（`DocumentCommunityDeriver`）
- Test: `tests/test_community_deriver.py`

- [ ] **Step 1:** 按 `doc_id` 聚合其 chunk 关联实体 -> LLM 生成文档级 `title`+`summary`（桩 litellm）测试 -> 实现跑绿
- [ ] **Step 2:** 派生社区写入 `CommunityStore`（`level=1`、`member_entity_names` 为该文档实体集合、access 字段继承）测试 -> 实现跑绿
- [ ] **Step 3:** 增量：新文档 ingest 只新增本档社区，不动已有文档社区测试 -> 实现跑绿

**验收：**
- 文档社区自动派生，level 区分实体/文档两层
- 增量安全，可重复 ingest 不重复派生

---

### Task 6: IndexingEngine 与 `ingest` CLI（串联 Task 1-5）

**目标：** 实现 `IndexingEngine` 抽象（六个接口之一）+ 默认 `ECLIndexingEngine` 串联 Load->Extract->Cognify->Load->社区派生；CLI `calliodesmo ingest <path>` 端到端建图落个人库并记审计。

**Files:**
- Create: `src/calliodesmo/interfaces/indexing_engine.py`（`IndexingEngine` ABC）
- Create: `src/calliodesmo/ecl/engine.py`（`ECLIndexingEngine`，依赖注入 loader/embedding/llm/chunker/extractor（含 EntitySchemaRegistry）/cognify/三 store/deriver）
- Modify: `src/calliodesmo/cli.py`（新增 `ingest` 命令）
- Modify: `src/calliodesmo/models.py`（如需 ORM 持久化补表；内存默认实现下可不改）
- Test: `tests/test_indexing_engine.py`、`tests/test_ingest_cli.py`

**接口（`interfaces/indexing_engine.py`）：**

```python
@dataclass
class IngestStats:
    documents: int
    chunks: int
    entities: int
    relations: int
    communities: int

class IndexingEngine(ABC):
    @abstractmethod
    async def ingest(
        self, source: str | Path, *, access: AccessContext,
    ) -> IngestStats: ...
```

- [ ] **Step 1:** `IndexingEngine` 接口 + `ECLIndexingEngine` 依赖注入构造（loader/embedding/llm/chunker/extractor（含 EntitySchemaRegistry）/cognify/三 store/deriver）测试 -> 实现跑绿
- [ ] **Step 2:** 端到端 ECL（桩 LLM + `HashEmbeddingProvider` + 内存三 store + `TextDocumentLoader`）跑通：doc->chunks->extraction（access 解析团队 schema 硬约束）->graph->communities->三 store 落库 + 返回 `IngestStats` 计数正确测试 -> 实现跑绿
- [ ] **Step 3:** `AccessContext` 限定 personal scope + `owner_id=ctx.user_id` 落库（断言 store 中记录 owner 匹配、越权不可见）测试 -> 实现跑绿
- [ ] **Step 4:** `ingest` CLI（Typer）：路径参数 + 构造默认引擎（内存 stores + `HashEmbeddingProvider` + `LiteLLMProvider`）+ 打印 `IngestStats`；`CliRunner` 断言退出码 0 与统计文本测试 -> 实现跑绿
- [ ] **Step 5:** 失败友好报错（路径不存在 -> 退出码非 0；loader 未注册 -> 提示安装 extra；LLM 缺 key -> 指引 `CALLIODESMO_LLM_API_KEY`）测试 -> 实现跑绿
- [ ] **Step 6:** 审计：ingest 动作经 `record_audit(action="ingest", resource_type="document", detail={stats}, source="cli")` 落 `AuditLog` 测试 -> 实现跑绿

**验收：**
- `ECLIndexingEngine` 串联 Task 1-5，端到端离线跑通（桩 LLM + Hash 嵌入 + 内存 stores）
- `calliodesmo ingest <path>` 一键建图落个人库，输出统计并记审计
- 越权记录不可见（personal scope 隔离验证）

---

## 精度策略与跨阶段改进（前瞻）

> [!note] 记录 P1 设计评审中提出的精度担忧与改进方向；P1 落地其中"过门槛"部分，更重的留待对应阶段，全部经可插拔接口接入，不动核心。

**精度投资优先级（ROI 排序，非按阶段）：**
1. **评估 harness（贯穿项，最大缺口）**--没有尺子不知精度够不够。P1/P2 起建小型 golden Q&A 集 + 指标脚本（忠实度 / 上下文召回 / 答案相关性，RAGAS 式），每次改动跑回归。
2. **检索精度（P2/P5，第一精度杠杆）**--`VectorStore` 旁加 `SparseIndex`(BM25) + `Reranker` 接口；查询走 稠密∪稀疏∪图 -> RRF 融合 -> 交叉编码器重排。
3. **实体消解（P1 Task 3，第二杠杆）**--名归一化 + 别名合并 + 多 chunk 描述汇总（本计划已落地为一等公民）。
4. **抽取质量（P1 Task 2）**--prompt 工程 + 模型可切换（本计划已纳入）。
5. **切分（中游杠杆）**--结构感知 + overlap 过门槛（本计划已落地）；语义/分层切分推迟 P5。

**GIGO 担忧的缓解（本阶段已做）：** 结构感知切分 + 实体消解把碎片实体拼回去 + 全程 `source_chunk_ids` 可溯源。

**留待后续阶段（不阻塞 P1 验收）：**
- 混合检索 + 重排：P2/P5。
- 分层切分 + 上下文富化（Anthropic contextual retrieval）：P5 精化。
- 跨 chunk 关系补抽 / 别名歧义精解：P8 证据验证硬化。
- ANN 向量索引（HNSW/IVF）支撑 ≥50 万：P9（`VectorStore` 接口已为此预留）。

**依赖与风险（P1 全量）：**
- **文档解析重依赖**按 extra 分组（documents-pdf/office/opendocument/rich/email/notebooks）；CI 默认只装基础 + `sys.modules` 桩测接口；真机验证用 `uv sync --extra documents-pdf --extra documents-office ...` 组合。
- **PDF 仅支持文本型**（可抽取文本）；扫描/图片型需 OCR，不在 P1 范围。
- **旧二进制 Office**（`.doc`/`.ppt`/`.xls`）、Keynote `.key`、Visio 等专有格式需 LibreOffice(headless)/antiword，P1 不直接支持，列入后续精化；`pandoc` 作多格式转换兜底后端（可选）。
- **三层存储**：`VectorStore`/`GraphStore`/`CommunityStore` 接口 + 确定性内存默认实现保证离线可测；pgvector/Neo4j 真后端列为 optional extra（容器验证，与 BGE-M3 同策略）。内存默认实现非持久（dev/test 重建即恢复），prod 持久化由真后端承担（与 P0 SQLite/Postgres 同构）。
- **社区检测**默认 `ConnectedComponentsDetector`（零重依赖、确定性）；可选 networkx Louvain/Leiden 列 extra（`graph-analytics`），缺依赖友好报错。GraphRAG 库式集成列为可选 extra（自带 LLM 调用需 key），P1 默认用自建 Cognify，GraphRAG 仅作 prod-grade Leiden 替代。
- **抽取/摘要 LLM** 真实运行需 API key；离线测试全用 `sys.modules` 桩隔离 litellm（沿用 P0 `test_llm_provider` 模式），零真实请求。
- **团队实体类型硬约束**：`EntitySchemaRegistry` 从 YAML 配置（`CALLIODESMO_ENTITY_SCHEMA_FILE`，默认 `config/entity_schemas.yaml`）按 team 唯一加载；Schema-Constraint 为硬约束（schema 外实体入 `rejected_entities`）；PyYAML 已由 Task 1 引入。
- **版本钉制**：litellm `>=1.85,<1.91`（>=1.93 无 Windows wheel）；引入 networkx/GraphRAG 时与之协调，避免传递依赖冲突。
- **精度边界（如实声明）**：跨 chunk 关系抽取、别名/指代歧义在 P1 MVP 不完美；靠结构感知切分 + 实体消解 + `source_chunk_ids` 溯源缓解，P8 证据验证硬化。
- **评估 harness（贯穿项）**：P1/P2 起建 golden 集 + 指标回归；P1 验证报告以功能测试 + 离线桩为主，质量评测自 P2 接入。
- **语义/分层切分推迟 P5**：结构感知 + overlap 过门槛；上下文富化（contextual retrieval）与分层父子关系列入 P5 精化。
