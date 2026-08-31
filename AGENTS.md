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
- **P4** Git-like 协作推送 ✅ 完成（Task 1-9 全闭合；A1 ContributionDetail + A2 CommunityVersions 已落地）
- **P4.5** 持久化与生产化 ✅ Task 1-7 全闭合（2026-08-15：清 SQLite 连真实 PG+pgvector+Neo4j、三 store 真后端、增量索引 MVP、P4 合并落库贯通 + 双写一致性、摄入 UI + 异步 job、三段式实体对齐 + 复核 UI、多模态 OCR/识图；详见 `docs/plans/phases/P4.5-persistence-production.md`）
- **P5** 高级 RAG 与智能检索 ✅ 完成（2026-08-19 合入，PR #10，431 passed：MultiQuery / RAGFusion / CRAG / SelfCheck / contextual retrieval；golden 基线 ctx_recall 0.4444；语义切分按证据跳过；详见 `docs/plans/phases/P5-advanced-rag.md`）
- **P6** LLM 分析任务 ✅ 完成（2026-08-30 合入，PR #11，1015 passed：9 类分析结构化报告 + 评估两件套 + 前端两批/自定义 + 注入防御；`--real` 质量补跑提前于 2026-W35 执行完毕、证据入库；详见 `docs/plans/phases/P6-llm-analysis-tasks.md` 与 `docs/verification/P6-verification.md`）
- **P7** Agent 模式 ✅ 完成（2026-08-31，PR 待合；详见 `docs/plans/phases/P7-agent-mode.md` 与 `docs/verification/P7-verification.md`）

完整路线图见 `docs/plans/roadmap.md`（Obsidian vault 根）；阶段任务计划见 `docs/plans/phases/`。

## 架构要点

**三层存储**
- 情景层：Postgres + pgvector（原始文本块 + 块向量）
- 语义层：Neo4j（实体-关系图）
- 摘要层：Postgres（社区摘要 + 摘要向量）

**ECL 管线**（P1）
- Extract：实体/关系/声明/协变量四类抽取，团队抽取模板软引导（模板外实体保留 + 打标，不 reject）
- Cognify：实体消解（一等公民）+ 图谱构建 + 连通分量社区检测（默认零依赖；networkx Louvain 可选 graph-analytics extra，Leiden 留 v2）+ 社区摘要
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
| 数据 | SQLAlchemy 2.0 (async) · PostgreSQL 16+ + pgvector · Neo4j |
| 认证 | PyJWT · pwdlib + Argon2 |
| LLM / 嵌入 | LiteLLM（多后端可切换）· BGE-M3（本地，可选 extra） |
| 检索 / Agent | LlamaIndex + LangGraph（P2+）· GraphRAG（P1，库形式集成） |
| 质量 | pytest + pytest-asyncio · Ruff · GitHub Actions |
| 前端 | React 19 · Vite 6 · TanStack Query · React Router 7 · Tailwind · shadcn/ui（Radix 源码拷贝）· cytoscape + cytoscape-fcose · lucide-react |

## 项目结构
```
src/calliodesmo/
├── api/          FastAPI 应用（/healthz、/auth/token、/auth/me、/query）
├── auth/         三维权限：models / security(Argon2+JWT) / context / service
├── audit/        审计日志（谁/何时/做了什么/从哪来）
├── db/           异步 SQLAlchemy 引擎与声明式基类（models_analysis.py 报告 ORM / models_agent.py 会话三表 / migrate.py 幂等补列）
├── ecl/          Extract-Cognify-Load 管线（chunker / extractor / cognify / community / load / engine / chunk_summarizer）
├── analysis/     P6 分析域（schemas / specs / prompts / parser / evidence / access / materials / engine / sanitize / factory / job_worker / report_store）
├── agent/        P7 Agent 域（errors / registry / tools / budget / graph / access / history / checkpoint / factory / job_worker）
├── interfaces/   抽象接口（ABC）：LLM / Embedding / DocumentLoader / VectorStore / GraphStore / CommunityStore / Retriever / SearchEngine / analysis ...
├── providers/    默认实现：LiteLLM / BGE-M3 / Hash / 各格式加载器 / 内存 stores / StubLLM
├── retrieval/    P2 检索域：fusion(RRF) / hybrid_retriever / bge_reranker / local_search / global_search / answer_synthesizer / search_engine
├── eval/         P2 评估 harness：golden(Q&A) / metrics(context_recall/faithfulness/answer_relevance) / harness
├── stores/       profile_card_store / visibility
├── config.py     pydantic-settings（CALLIODESMO_ 前缀）
├── models.py     ORM 模型集中导入（保证 Base.metadata 注册完整）
└── cli.py        Typer：db init / db seed / serve / ingest / ask
frontend/                独立 SPA（React 19 + Vite 6），与 src/ 平级；详见下「前端开发与验证闭环」
docs/
├── deploy/               部署文档（native.md：非 Docker 原生部署）
├── plans/                Obsidian vault：roadmap / monthly/<YYYY-MM> / weekly/<YYYY-Www> / phases/P<n>-<slug>
│   ├── phases/           阶段任务计划（P0-P7 已有，checkbox 跟踪）
│   ├── monthly/          月计划
│   └── weekly/           周计划（含日计划表）
├── verification/         各阶段验证报告（README 索引 + P0-P5 / OCR 识图 / 全链路仿真报告 + pytest 输出/证据）
└── model-selection.md    模型选型说明
tests/                     pytest 测试（真实 PG+pgvector+Neo4j，走 `.env`；CI 以 `-m "not db"` 跳过 DB 测试）
config/                    extraction_templates.example.yaml（团队抽取模板）+ golden_qa.example.yaml + analysis_prompts/（P6 九类模板）+ golden_analysis.yaml（P6 评估 golden）
scripts/                   bootstrap.ps1 / bootstrap.sh（一键引导：建表+种子+冒烟）+ eval_p5.py / eval_p6.py / eval_agent.py（评估回归，--real 切真模型）
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
- **未竟事项留痕**：凡留有后续或未完善的内容（代码 `TODO`/`FIXME`、阶段计划未勾选 checkbox、验证报告缺口、UI 持续迭代项等），须在对应文档或就地注释显式注明**未竟点 + 预计完成时间**（落到具体周次 `YYYY-Www` 或日期），不留隐式尾巴；代码内 `TODO` 一律附预计完成时间。完成即勾除 / 删除标记，闭环。

## 开发命令

```bash
uv sync                          # 安装依赖（含 dev 组）
uv sync --extra embedding-local  # 安装 BGE-M3 重依赖（按需）
uv run ruff format .             # 格式化
uv run ruff check .              # 静态检查
uv run pytest -v                 # 测试（连 `.env` 的 PG+Neo4j；`-m "not db"` 仅纯逻辑，CI 等价）
uv run calliodesmo serve         # 启动 API（uvicorn）
uv run calliodesmo db init       # 建表（幂等）
uv run calliodesmo db seed      # 种子角色/管理员/系统账户（幂等）
uv run calliodesmo ingest <path> # 端到端建图
```

> P4.5 起：测试与运行一律连真实 PG+pgvector+Neo4j（`.env` 驱动，`uv sync --extra persistence`）。**SQLite 零依赖模式已移除**——测试经专用 schema `calliodesmo_test` 隔离 + 每测 TRUNCATE；CLI 测试经 `cli_db` 夹具唯一 schema 隔离。

## 测试策略

- **隔离**：每用例在专用 PG schema `calliodesmo_test`（与生产 `public` 物理隔离）内每测 TRUNCATE 清空；CLI 测试经 `cli_db` 夹具用唯一 schema 隔离；`sys.modules` 桩隔离 litellm/uvicorn 等外部依赖；Neo4j 经 `neo4j_session` 夹具清图。DB 依赖测试自动打 `@pytest.mark.db`，CI 以 `-m "not db"` 跳过（全量回归靠本地 `.env`）。
- **契约优先**：接口测试断言输入映射与输出结构，保证可插拔。
- **幂等**：种子与引导脚本均显式验证可重复执行。
- **异步**：`pytest-asyncio` auto 模式（`asyncio_mode = "auto"`）。
- 新增功能先写失败测试 -> 实现 -> 跑绿 -> 提交（TDD），阶段计划文件用 checkbox 跟踪。

## 联网检索能力（tavily-mcp）

本项目接入 **tavily-mcp**，提供联网检索与网页内容获取的五项核心能力（`tavily_search` / `tavily_extract` / `tavily_crawl` / `tavily_map` / `tavily_research`）：

| 工具 | 能力 | 用途 |
|:--|:--|:--|
| `tavily_search` | Search | 关键词检索最新信息 / 事实 / 数据（支持时间区间、域名过滤、深度调节） |
| `tavily_extract` | Extract | 从指定 URL 提取干净内容（markdown / 纯文本，advanced 可取表格与嵌入内容） |
| `tavily_crawl` | Crawl | 从根 URL 按深度 / 广度爬取整站内容 |
| `tavily_map` | Map | 映射站点 URL 结构（不抓正文），用于摸清可抓页面范围 |
| `tavily_research` | Research | 综合多源做深度专题研究，返回结构化结论 |

**主动使用时机**--遇到以下情况积极联网获取先进优秀方案，不要仅凭记忆硬写：

- **复杂问题**：涉及不熟悉的库版本、API、协议、平台行为差异时，先 `tavily_search` / `tavily_research` 查证最新最佳实践再动手。
- **重构时**：替换依赖、调整架构、升级版本前，搜社区主流方案与已知坑（如 litellm `>=1.85,<1.91` 的 Windows wheel 问题）。
- **创建新功能**：新增模块 / 端点 / 组件前，检索业界成熟实现与设计模式，吸收先进做法。

**边界**：查到的外部方案须与本项目约定对齐（Python 3.11+ / async / 接口抽象 / TDD / 三维权限模型 / 离线可测），不盲抄；**经综合考量（收益 / 维护成本 / 安全性 / 离线可测性）后允许引入重依赖**，但重依赖仍走 `optional-dependencies`（extra）+ 运行时懒加载 + 缺依赖友好报错，并在引入前说明理由；版本相关结论落实前再用 `tavily_extract` 取官方文档原文核对。

## 前端开发与验证闭环

前端为独立 SPA（`frontend/`，与 `src/` 平级），React 19 + Vite 6 + TanStack Query + React Router 7 + Tailwind + shadcn/ui（Radix 源码拷贝）+ `cytoscape` + `cytoscape-fcose`（图谱，Canvas）+ `lucide-react`（图标）。开发期 Vite dev server（5173）经 dev proxy 把 `/api` 转发后端 8200（见 `frontend/vite.config.ts`），后端联调启 `uv run calliodesmo serve --port 8200`，同源 cookie 全程可用；生产构建产物由 FastAPI `StaticFiles` 托管（`frontend/dist`），同源免 CORS。路由：`/login` + `/app/{qa, library, admin/users, admin/teams, admin/communities, settings}`（见 `frontend/src/routes.tsx`）。

### 前端命令（在 `frontend/` 执行）

```bash
cd frontend
npm run dev      # Vite dev server（5173，/api 代理到 8200）
npm run build    # tsc -b && vite build -> dist/
npm run lint     # tsc -b --noEmit（noUnusedLocals/noUnusedParameters 严）
npm run test     # vitest run（@testing-library/react）
npm run e2e      # Playwright e2e（@playwright/test，桌面 + 移动视口）
```

### 验证闭环（有视觉表现的改动必走）

**底线三件套**：任何前端改动都过 `lint` / `test` / `build`。**之上**，有可见视觉表现的改动（`components/` / `features/` / `App.tsx` / `index.css` / 图谱）走浏览器交互验证闭环；纯逻辑 / 类型改动（无视觉表现）三件套即可。判不准默认走三件套。

1. **开发与启动**：改代码 -> 启 Vite dev（5173）；联调另起 `uv run calliodesmo serve --port 8200`（灌演示数据加 `--seed-demo`；dev proxy 已把 `/api` -> 8200）。
2. **取页面结构**：accessibility snapshot 拿无障碍树，识别按钮 / 输入框 / 路由项及 Selector（**首选 snapshot，非 screenshot**--snapshot 给可操作的 ref/selector，screenshot 不能驱动操作）。
3. **模拟人类操作**：按业务路径 click / type / hover 像真实用户（登录页输错密码点登录、悬停下拉、切换问答模式、双击图谱节点展开 / 折叠、滑块调跳数与节点上限）。
4. **视觉与状态感知**：screenshot 截图 -> 视觉识图模型分析布局 / 重叠 / 溢出 / 状态是否符合预期；同步查 console（error）/ network（4xx/5xx）/ snapshot（结构）。
5. **反思与修复**：交互失败 / UI 状态不对 / 不符合要求 -> 读源码诊断 -> 改代码 -> 重复 2–4，**直到所有人类交互路径完美通过**。

### 工具

浏览器自动化 MCP：`browser_snapshot`（无障碍树）/ `browser_click` / `browser_type` / `browser_hover` / `browser_take_screenshot` / `browser_resize` / `browser_console_messages`。视觉识图：GLM-EYE（`analyze_image` / `ui_diff_check`）。

> **Claude Code** 用内置 `preview_*` 工具等价完成（**不用 Playwright MCP**），映射见 [CLAUDE.md](CLAUDE.md)：`preview_start`（启 dev server）/ `preview_snapshot` / `preview_click` / `preview_fill` / `preview_eval`(hover) / `preview_screenshot` / `preview_inspect` / `preview_console_logs` / `preview_resize`。

### 验收要点（关键流程截图，桌面 + 移动视口）

- **登录**：`/login` 错误凭证提示 + 正确登录跳 `/app/qa`
- **问答**：`/app/qa` 三模式（Native/Local/Global）切换 + `top_k` 调节 + 来源标注展开
- **库浏览**：`/app/library` ProfileCard / 社区导航 / **图谱**（4 布局切换、展开折叠、拖动、调范围）
- **管理**：`/app/admin/{users,teams,communities}` CRUD + 越权探测（无 `manage_users` 直击前端路由 + 后端端点均 403）
- **设置**：`/app/settings` 改密
- **权限矩阵**：analyst / reviewer / admin 三角色各跑可见与可操作集合（对齐后端 `DEFAULT_ROLE_PERMISSIONS`）

### 图谱（EntityGraph）专项验收

4 布局模式（force / cluster / hierarchy / radial）切换 + `forceCollide` 防标签重叠 + 降 #5（拖动时不相邻节点连带位移，目标漂移 <20）+ 多分量拉近。计划见 [docs/plans/entity-graph-layouts.md](docs/plans/entity-graph-layouts.md)。验收：三件套 + 4 模式截图对比 + 拖动 #5 漂移量 + 标签重叠像素检查。

### 依赖与边界

- 前端依赖隔离（`frontend/package.json`，与后端 Python 依赖隔离）；CI 前端 job `npm ci && npm run build && vitest`；Node 版本锁 `.nvmrc`。
- 前端不进检索精度回归（P2 harness），但权限一致性有回归测试（三角色矩阵）。
- 内存 stores 单进程：UI 走 API，演示数据统一走 `serve --seed-demo`（serve 进程内自灌，seed 产物落盘缓存 `data/demo/seed-cache.json`）。

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
