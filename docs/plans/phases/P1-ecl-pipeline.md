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

| 类别 | 格式 | 接入 | 候选库/方式 |
| --- | --- | --- | --- |
| 纯文本/Markdown | `.txt` `.log` `.md` `.markdown` | 内置 | 已有 `TextDocumentLoader` |
| 表格 | `.csv` `.tsv` | 内置 | 标准库 `csv` |
| 结构化文本 | `.json` `.yaml`/`.yml` `.xml` `.html`/`.htm` | 内置 | 标准库 + `PyYAML` |
| 标记语言 | `.rst` `.org` `.tex` | 内置（轻解析取纯文本） | 标准库/正则 |
| PDF | `.pdf`（文本型） | extra `documents-pdf` | `pypdf`（备选 pdfplumber/pymupdf） |
| Word | `.docx` | extra `documents-office` | `python-docx` |
| Excel | `.xlsx` | extra `documents-office` | `openpyxl` |
| PowerPoint | `.pptx` | extra `documents-office` | `python-pptx` |
| 开放文档 | `.odt` `.ods` `.odp` | extra `documents-opendocument` | `odfpy` |
| 富文本/电子书 | `.rtf` `.epub` `.mobi` | extra `documents-rich` | `striprtf`/`ebooklib` |
| 邮件 | `.eml` `.msg` | extra `documents-email` | 标准库 `email`/`extract-msg` |
| 笔记本 | `.ipynb` | extra `documents-notebooks` | `nbformat` |

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

### Task 2+: ECL 其余环节（概要，待 writing-plans 细化）

> 以下为 P1 其余 ECL 任务大纲，完整 TDD 步骤待用 `writing-plans` skill 细化后补入本文档。

- **Task 2 Extract 抽取：** Schema-Free + Schema-Constraint 四类抽取（实体/关系/声明），走 LLMProvider。
- **Task 3 Cognify 建图：** GraphRAG 库式集成 + Leiden 社区检测 + 社区摘要。
- **Task 4 Load 落库：** 三层数据落个人库（情景层/语义层/摘要层）。
- **Task 5 文档社区自动派生。**
- **Task 6 CLI `ingest` 建图命令**（串联 Task 1-5）。

---

**依赖与风险：**
- 重依赖格式按 extra 分组（documents-pdf/office/opendocument/rich/email/notebooks），CI 默认只装基础 + 用桩测接口；真机验证用 `uv sync --extra documents-pdf --extra documents-office ...` 按需组合。
- PDF 仅支持文本型（可抽取文本的 PDF）；扫描型/图片型 PDF 需 OCR，不在 P1 支持范围。
- 旧二进制 Office（`.doc`/`.ppt`/`.xls`）、Keynote `.key`、Visio 等专有格式需 LibreOffice(headless)/antiword，P1 不直接支持，列入后续精化。
- `pandoc` 作为多格式转换兜底后端（可选），不作为 P1 必选。
- GraphRAG 依赖在 P1 引入，注意与 LiteLLM 版本钉制（`>=1.85,<1.91`）协调。