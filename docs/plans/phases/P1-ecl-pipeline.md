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

**Goal:** 打通 ECL 主链路（Extract → Cognify → Load），实现“数据进 -> 建图 -> 落个人库”。Extract 入口支持多格式文档解析：txt/md/csv 基础格式内置，pdf 与 Office 全家桶（docx/xlsx/pptx）以可拓展插件方式接入。

**Architecture:** `DocumentLoader` 抽象接口（P0 已立）保持不变；每种文档格式一个具体 Loader（插件），按后缀分发。基础格式（txt/md/csv）默认内置；pdf/office 重依赖列为可选 extra（`[project.optional-dependencies]`），懒加载，缺依赖时友好报错（沿用 FlagEmbedding 模式）。`LoaderRegistry` 按 `source.suffix` 选择实现；新增格式只需新增 Loader + 注册，不动核心。Cognify 走 GraphRAG 库式集成 + Leiden；Load 写个人库三层数据。

**Tech Stack（P0 基础上追加）:**
- 基础格式：`csv`（标准库）/ Markdown、纯文本（已有）
- 可选 extra `documents-pdf`：`pypdf`（备选 `pdfplumber`/`pymupdf`）
- 可选 extra `documents-office`：`python-docx`（Word）/ `openpyxl`（Excel）/ `python-pptx`（PowerPoint）
- 测试：`pytest` + 临时样例文件 + `monkeypatch`/`sys.modules` 桩隔离重依赖

---

### Task 1: 文档解析与加载器（多格式 + 可拓展插件）

**目标：** P1 阶段可解析 txt/md/csv 等基础格式，且可拓展接入 pdf 与 Office 全家桶（ppt/word/excel）。

**Files:**
- Modify: `src/calliodesmo/providers/text_loader.py`（保留 txt/md，抽公共逻辑）
- Create: `src/calliodesmo/providers/csv_loader.py`
- Create: `src/calliodesmo/providers/pdf_loader.py`（extra: documents-pdf）
- Create: `src/calliodesmo/providers/office_loader.py`（extra: documents-office，含 docx/xlsx/pptx）
- Create: `src/calliodesmo/providers/registry.py`（按后缀分发 + 注册表）
- Modify: `pyproject.toml`（新增 optional-dependencies）
- Test: `tests/test_document_loaders.py`

**接口与分发设计：**
- `DocumentLoader.load(source) -> list[LoadedDocument]` 签名不变
- `LoaderRegistry`：`register(suffix, loader)` / `resolve(source) -> DocumentLoader`；按后缀查表，未注册抛清晰错误并提示安装哪个 extra
- 基础（txt/md/csv）默认注册；pdf/office 懒注册（用到且依赖在时注册）

**基础格式（P1 必做，内置）：**
- [ ] **Step 1:** txt / md 复用 `TextDocumentLoader`（P0 已有，回归测试）
- [ ] **Step 2:** 写 `LoaderRegistry` 分发与未注册报错的失败测试 -> 实现跑绿
- [ ] **Step 3:** 写 csv_loader 测试（表头/多行/空文件）-> 实现跑绿（标准库 `csv`）

**可拓展插件（P1 接入，按 extra）：**
- [ ] **Step 4:** pdf（`documents-pdf`）：`pypdf` 抽文本，按页切分 `LoadedDocument`（页码入 metadata）；缺依赖友好报错
- [ ] **Step 5:** Word `.docx`（`documents-office`）：`python-docx` 按段落抽取
- [ ] **Step 6:** Excel `.xlsx`（`documents-office`）：`openpyxl` 按 sheet 抽取（sheet 名入 metadata）
- [ ] **Step 7:** PowerPoint `.pptx`（`documents-office`）：`python-pptx` 按幻灯片抽取
- [ ] **Step 8:** 缺依赖友好报错统一测试（monkeypatch `sys.modules` 卸载依赖，断言提示安装 extra）

**集成：**
- [ ] **Step 9:** `ingest` 入口（CLI/API）走 `LoaderRegistry` 按后缀加载，端到端冒烟

**验收：**
- txt/md/csv 装基础依赖即可用；pdf/docx/xlsx/pptx 装对应 extra 后可用；未装 extra 时清晰报错并给出 `uv sync --extra documents-pdf`（或 office）提示；新增格式只需新增 Loader + 注册一行。

---

### Task 2+: ECL 其余环节（概要，待 writing-plans 细化）

> 以下为 P1 其余 ECL 任务大纲，完整 TDD 步骤待用 `writing-plans` skill 细化后补入本文档。

- **Task 2 Extract 抽取：** Schema-Free + Schema-Constraint 四类抽取（实体/关系/声明），走 LLMProvider。
- **Task 3 Cognify 建图：** GraphRAG 库式集成 + Leiden 社区检测 + 社区摘要。
- **Task 4 Load 落库：** 三层数据落个人库（情景层/语义层/摘要层）。
- **Task 5 文档社区自动派生。**
- **Task 6 CLI `ingest` 建图命令**（串联 Task 1-5）。

---

**依赖与风险：**
- pdf/office 解析库体积较大，列为 optional extra；CI 默认不装，用桩测接口；真机验证用 `uv sync --extra documents-pdf --extra documents-office`。
- 旧二进制格式（.doc/.ppt/.xls）需 Libreoffice/antiword，P1 不支持，列入后续精化。
- GraphRAG 依赖在 P1 引入，注意与 LiteLLM 版本钉制（`>=1.85,<1.91`）协调。