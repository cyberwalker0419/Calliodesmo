# AGENTS.md - Calliodesmo 项目提示词

> 三层知识图谱驱动的智能情报分析平台。GraphRAG 索引基座 + LlamaIndex/LangGraph 检索与 Agent 编排，LLM 与嵌入可切换。

## 项目定位

Calliodesmo 把原始文档加工成**三层知识图谱**（情景层 / 语义层 / 社区摘要层），支撑从精准检索到全局研判的多层问答，以**三维正交权限模型**（角色 RBAC + 访问等级 clearance + 库范围 scope）和 **Git-like 协作推送**保证多用户情报生产的安全与可追溯。

语言：Python 3.11+；uv 管理依赖，hatchling 打包。语料中英双语。

## 当前阶段

- **P0** 地基脚手架 ✅ 完成
- **P1** ECL 管线 MVP（抽取/建图/社区/落库/ingest CLI）✅ 完成
- **P2** 基础检索与 RAG ✅ 完成
- **P3** Web UI ✅ 完成--管理/浏览后端补全 + React SPA（登录/问答/浏览/管理/文档社区手动管理）+ 权限矩阵回归
- **P4** Git-like 协作推送 ⏳ 下一步

完整路线图见 `docs/plans/roadmap.md`（Obsidian vault 根）；阶段任务计划见 `docs/plans/phases/`。

## 架构要点

**三层存储**
- 情景层：Postgres + pgvector（原始文本块 + 块向量）
- 语义层：Neo4j（实体-关系图）
- 摘要层：Postgres（社区摘要 + 摘要向量）

**ECL 管线**（P1）
- Extract：实体/关系/声明/协变量四类抽取，团队抽取模板软引导（模板外实体保留 + 打标，不 reject）
- Cognify：实体消解（一等公民）+ 图谱构建 + Leiden 社区检测 + 社区摘要
- Load：三层数据落库（写个人库）

**六处可插拔抽象接口**（`src/calliodesmo/interfaces/`）
LLMProvider / EmbeddingProvider / VectorStore / GraphStore / DocumentLoader / IndexingEngine（P2 追加 SparseIndex / Reranker / Retriever / SearchEngine）。单机起步，按需扩展到 ≥50 万文档。

**三维正交权限模型**（`src/calliodesmo/auth/`）
- 角色 RBAC（analyst / reviewer / admin）-> 控"能做什么"
- clearance（public / internal / confidential / secret）-> 控"能看什么"
- 库范围 scope（personal / project / team 三层）-> 控"谁的数据"
- `AccessContext` 贯穿请求全生命周期，检索器/合成器统一接收做过滤

## 技术栈

| 类别 | 技术 |
| --- | --- |
| Web / CLI | FastAPI · uvicorn · Typer |
| 数据 | SQLAlchemy 2.0 (async) · PostgreSQL 16 + pgvector · Neo4j · aiosqlite |
| 认证 | PyJWT · pwdlib + Argon2 |
| LLM / 嵌入 | LiteLLM（多后端可切换）· BGE-M3（本地，可选 extra） |
| 检索 / Agent | LlamaIndex + LangGraph（P2+）· GraphRAG（P1，库形式集成） |
| 质量 | pytest + pytest-asyncio · Ruff · GitHub Actions |

## 项目结构
```
src/calliodesmo/
├── api/          FastAPI 应用（/healthz、/auth/token、/auth/me、/query）
├── auth/         三维权限：models / security(Argon2+JWT) / context / service
├── audit/        审计日志（谁/何时/做了什么/从哪来）
├── db/           异步 SQLAlchemy 引擎与声明式基类
├── ecl/          Extract-Cognify-Load 管线（chunker / extractor / cognify / community / load / engine / chunk_summarizer）
├── interfaces/   抽象接口（ABC）：LLM / Embedding / DocumentLoader / VectorStore / GraphStore / CommunityStore / Retriever / SearchEngine ...
├── providers/    默认实现：LiteLLM / BGE-M3 / Hash / 各格式加载器 / 内存 stores / StubLLM
├── retrieval/    P2 检索域：fusion(RRF) / hybrid_retriever / bge_reranker / local_search / global_search / answer_synthesizer / search_engine
├── eval/         P2 评估 harness：golden(Q&A) / metrics(context_recall/faithfulness/answer_relevance) / harness
├── stores/       profile_card_store / visibility
├── config.py     pydantic-settings（CALLIODESMO_ 前缀）
├── models.py     ORM 模型集中导入（保证 Base.metadata 注册完整）
└── cli.py        Typer：db init / db seed / serve / ingest / ask
docs/
├── deploy/               部署文档（native.md：非 Docker 原生部署）
├── plans/                Obsidian vault：roadmap / monthly/<YYYY-MM> / weekly/<YYYY-Www> / phases/P<n>-<slug>
│   ├── phases/           阶段任务计划（P0-P3 已有，checkbox 跟踪）
│   ├── monthly/          月计划
│   └── weekly/           周计划（含日计划表）
├── verification/         各阶段验证报告（README 索引 + P0/P1/P2 验证报告 + pytest 输出/证据）
└── model-selection.md    模型选型说明
tests/                     pytest 测试（内存 SQLite + sys.modules 桩，离线可跑）
config/                    extraction_templates.example.yaml（团队抽取模板）+ golden_qa.example.yaml（评估 golden 集）
scripts/                   bootstrap.ps1 / bootstrap.sh（一键引导：建表+种子+冒烟）
.github/workflows/ci.yml   CI：ruff + pytest
```

## 代码约定

- **语言**：模块 docstring、注释、docstring 用中文；标识符用英文。
- **接口**：抽象用 `ABC` + `@abstractmethod`；数据结构用 `@dataclass`；异步全链路 `async/await`。
- **配置**：经 `pydantic-settings` 从环境变量 / `.env` 加载（前缀 `CALLIODESMO_`），`get_settings()` 用 `@lru_cache` 单例。新增配置项加到 `config.py` 的 `Settings` 类并同步 `.env.example`。
- **ORM 模型注册**：新增 ORM 模型须在 `models.py` 集中导入（保证 `Base.metadata` 注册完整），测试与 CLI 中 `import calliodesmo.models  # noqa: F401`。
- **依赖分层**：默认实现保持确定性、零重依赖、离线可测。重型依赖（BGE-M3 / reranker / PDF / Office 等）列 `optional-dependencies`（extra），运行时懒加载 + 缺依赖友好报错。
- **本地 LLM 豁免**：`LLM_API_BASE` 指向 localhost 或模型以 `ollama/` / `lm-studio/` 开头时自动豁免 API key 校验。
- **精度原则**：精度由数据判定，不靠猜--评估 harness 贯穿；精度主要在检索重排与实体消解挣回，切分属中游杠杆。

## 开发命令

```bash
uv sync                          # 安装依赖（含 dev 组）
uv sync --extra embedding-local  # 安装 BGE-M3 重依赖（按需）
uv run ruff format .             # 格式化
uv run ruff check .              # 静态检查
uv run pytest -v                 # 测试（内存 SQLite，离线可跑）
uv run calliodesmo serve         # 启动 API（uvicorn）
uv run calliodesmo db init       # 建表（幂等）
uv run calliodesmo db seed      # 种子角色/管理员（幂等）
uv run calliodesmo ingest <path> # 端到端建图
```

SQLite 零依赖开发模式：设 `CALLIODESMO_DATABASE_URL=sqlite+aiosqlite:///./data/calliodesmo-dev.db`（无向量检索与图库，P0 全功能可跑）。

## 测试策略

- **隔离**：每用例独立内存 SQLite（`sqlite+aiosqlite:///:memory:`，见 `tests/conftest.py`）；`sys.modules` 桩隔离 litellm/uvicorn 等外部依赖--离线可跑。
- **契约优先**：接口测试断言输入映射与输出结构，保证可插拔。
- **幂等**：种子与引导脚本均显式验证可重复执行。
- **异步**：`pytest-asyncio` auto 模式（`asyncio_mode = "auto"`）。
- 新增功能先写失败测试 -> 实现 -> 跑绿 -> 提交（TDD），阶段计划文件用 checkbox 跟踪。

## Ruff 配置

- `target-version = "py311"`，`line-length = "100"`
- 选用：`E, F, I, UP, B, ASYNC, RUF`
- 忽略：`RUF001/2/3`（中文全角标点误报）、`B008`（FastAPI `Depends` 惯用法）

## Git 约定

- **Conventional Commits**，描述用中文：`feat(ecl): ...` / `docs(plans): ...` / `fix(auth): ...` / `refactor(api): ...` / `chore: ...`
- Codex 创建分支前缀 `codex/`（如 `codex/p2-retrieval-rag`）。
- 合并走 PR；CI（`.github/workflows/ci.yml`）自动执行 ruff + pytest。

## 关键约束

- **litellm 钉版 `>=1.85,<1.91`**：≥1.93 无 Windows 预编译 wheel（需 Rust/MSVC 工具链）。升级前确认 wheel 可用性。
- **`.obsidian/` 整目录不追踪**（已入 `.gitignore`），但 `docs/plans/` 下的计划文档用 Obsidian 原生 markdown + wikilinks。
- **`data/` 不追踪**（含本地 DB 与导入语料），文档放 `data/docs/`。
- **`.env` 不追踪**，仅提交 `.env.example`。
- 生产部署必须改 `CALLIODESMO_JWT_SECRET_KEY` 为 ≥32 字节随机串。

## 计划文档体系（docs/plans/）

四层 Obsidian markdown + wikilinks：

- `roadmap.md` - 年计划（P0-P9 路线图 + 里程碑 + 节奏）
- `monthly/<YYYY-MM>.md` - 月计划
- `weekly/<YYYY-Www>.md` - 周计划（含日计划表）
- `phases/P<n>-<slug>.md` - 阶段任务计划（bite-sized TDD 步骤）

修改计划文档时保持 wikilink（`[[...]]`）与 frontmatter（`title` / `type` / `tags` / `created`）格式一致。
