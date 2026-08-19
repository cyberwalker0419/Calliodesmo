---
title: OCR/识图多模态验证报告
type: verification-report
tags:
  - verification
created: 2026-08-14
---

# OCR / 识图多模态验证报告（Task 7，2026-08-14）

> 关联：[[docs/plans/phases/P4.5-persistence-production|P4.5 阶段计划 Task 7]] · [[docs/plans/roadmap|年计划]]

## 测试内容

| 模块 | 用例 | 数量 | 验证点 |
| --- | --- | --- | --- |
| `tests/test_vision_interfaces.py` | StubOCR / StubVision / ABC 契约 | 3 | 桩可调用、返回结构、抽象方法存在 |
| `tests/test_litellm_vision.py` | vision describe / data URI | 2 | 多模态 content part（text+image_url base64）、usage 透传、`_short_model` |
| `tests/test_paddleocr_provider.py` | local 提取 / 缺依赖 / 结果解析 | 3 | `rec_texts` 优先拼行、缺 paddleocr 友好报错、text 回退 |
| `tests/test_image_loader.py` | ImageLoader + registry | 5 | OCR 优先 / 识图降级 / 无 provider 报错 / 后缀注册 / 无 provider 不注册 |
| `tests/test_ingest_api.py` | PNG 摄入 | 1 | `/ingest` 图片 → StubOCR 转文本 → StubLLM 抽取落库（owner 校验） |
| `tests/test_query_api.py` | with-image 端点 | 2 | multipart 带图提问 200 + 识图描述注入 + 审计 `has_image`；413 超限 |
| **合计** | | **16** | 全部离线可跑（`sys.modules` 桩 / `test/*` 桩），无网络依赖 |

**后端全量基线**：`uv run pytest -q`（`.env` 连真实 PG+pgvector+Neo4j）→ **423 passed / 1 skipped / 0 failed**（较承诺批次 407 净增 16 为新用例；无回归）。纯逻辑（CI 等价）：`uv run pytest -q -m "not db"` → 261 passed / 1 skipped / 162 deselected。

**前端三件套**：`npm run lint`（tsc 0 错）/ `npm run test`（vitest 5 passed）/ `npm run build`（成功，仅 chunk>500k 既有警告）。

## 技术栈

- **摄入侧**：`interfaces/ocr.py`（`OcrProvider` ABC）· `PaddleOcrProvider`（local=paddleocr[doc-parser] `>=3.6` 懒加载 / remote=HTTP 编排零重型依赖，`documents-ocr` extra）· `ImageLoader`（OCR 优先 / 识图降级）。
- **提问侧**：`interfaces/vision.py`（`VisionProvider` ABC）· `LiteLLMVisionProvider`（data URI image_url + litellm acompletion，Ollama/LM Studio/云端可切）· `/query/with-image`（multipart）。
- **前端**：`AskPanel` 附图按钮 + 缩略图 + 移除；`useAsk` 有图 → multipart `/query/with-image`，无图 → JSON `/query`。
- **验证工具链**：pytest + pytest-asyncio（auto）· `sys.modules` 桩（litellm/paddleocr）· StubOCR/StubVision（`test/*` 路由）· vitest + @testing-library/react · `preview_*` 交互闭环（dev server 5173 + 后端 8200）。

## 验证原理

- **契约优先**：`OcrProvider`/`VisionProvider` 抽象接口保证可插拔；桩与真实现同接口，测试断言输入映射与输出结构。
- **离线可测**：所有 16 用例经 `sys.modules` 桩（fake litellm / fake paddleocr）或 `test/*` 桩路由，零网络、零重型依赖；真实模型留 `.env` 配置面。
- **幂等/边界**：图片大小 413、mime 415、权限 403 守卫；`ImageLoader` 无 provider 友好报错。
- **增量索引兼容**：`ImageLoader.content_hash` 按转录文本 sha256 计算，与 Task 3 指纹一致。

## 验证过程

1. **后端**：写 6 个测试文件（16 用例）→ 实现 11 个模块/provider → `uv run pytest` 目标文件全绿 → ruff check 全绿（修 2 处测试 lint）→ `uv run pytest -q` 全量 **423 passed / 1 skipped**。
2. **前端**：`AskPanel`/`useQuery` 附图 → 三件套（lint/test/build）绿。
3. **交互闭环**（`preview_*`，dev server 5173 / 后端 8200 `--seed-demo`）：
   - 登录 → 问答面板出现「附带图片」按钮
   - 选图 → 缩略图「待提问图片」+「移除图片」按钮渲染
   - 带图提问 → `POST /api/query/with-image` **200**，后端日志审计 `{"mode":"native_rag","has_image":true,"vision_model":"test/stub-vision","sources":0}` 落库
   - 「移除图片」→ 缩略图清除
   - 移动端（375×812）布局正常，无溢出
   - 注：真实 qwen3-vl（本机 Ollama 未跑）时带图请求 500 属环境缺 VLM，非代码缺陷；换 `test/stub-vision` 后全链路 200。

## 已知边界与后续

- **真机验证边界**（留痕）：PaddleOCR-VL 本机/远端部署、qwen3-vl 真实识图质量、扫描 PDF 渲染+OCR（`pdf_loader._ocr_page`）均未在本机跑真实模型，验证用 `test/stub-*` 桩证明链路；真实接入按 `.env.example` OCR/识图段接线。预计完成时间：随用户本机模型环境 W33+ 真机走查（计划级留痕，无代码 TODO）。
- `config` 默认 `OCR_PROVIDER=none` / 未配置 vision 时不注册图片后缀——默认零配置行为不变。

## 证据

- 全量 `uv run pytest -q`：423 passed / 1 skipped（2026-08-14，上述过程 1 记录）
- 前端三件套 + `preview_*` 交互证据：上述过程 3（本报告会话记录）
