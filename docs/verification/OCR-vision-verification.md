---
title: OCR/识图多模态验证报告
type: verification-report
tags:
  - verification
created: 2026-08-14
---

# OCR / 识图多模态验证报告（Task 7，2026-08-14）

> 关联：[[docs/plans/phases/P4.5-persistence-production|P4.5 计划 Task 7]] · [[docs/plans/roadmap|年计划]]

## 测试内容

| 模块 | 用例 | 数量 | 验证点 |
| --- | --- | --- | --- |
| `test_vision_interfaces.py` | StubOCR/StubVision/ABC 契约 | 3 | 桩可调用、返回结构、抽象方法 |
| `test_litellm_vision.py` | vision describe / data URI | 2 | 多模态 content part、usage 透传 |
| `test_paddleocr_provider.py` | local / 缺依赖 / 解析 | 3 | `rec_texts` 拼行、缺依赖报错 |
| `test_image_loader.py` | ImageLoader + registry | 5 | OCR 优先/识图降级/无 provider 报错/后缀注册 |
| `test_ingest_api.py` | PNG 摄入 | 1 | 图片→StubOCR→StubLLM 落库（owner 校验） |
| `test_query_api.py` | with-image 端点 | 2 | 带图提问 200 + 识图注入 + 审计；413 超限 |
| **合计** | | **16** | 全部离线可跑 |

**后端全量**：`uv run pytest -q`（真 PG+pgvector+Neo4j）→ **423 passed / 1 skipped / 0 failed**（较承诺批次 407 净增 16）；纯逻辑（CI 等价）261 passed / 162 deselected。**前端三件套**：lint 0 错 / vitest 5 passed / build 成功。

## 技术栈

- **摄入侧**：`interfaces/ocr.py`（`OcrProvider` ABC）· `PaddleOcrProvider`（local=paddleocr[doc-parser] `>=3.6` / remote=HTTP 编排零重型依赖，`documents-ocr` extra）· `ImageLoader`（OCR 优先/识图降级）。
- **提问侧**：`interfaces/vision.py`（`VisionProvider` ABC）· `LiteLLMVisionProvider`（data URI image_url，Ollama/LM Studio/云端可切）· `/query/with-image`（multipart）。
- **前端**：`AskPanel` 附图按钮 + 缩略图；有图走 multipart `/query/with-image`。
- **验证工具链**：pytest + `sys.modules` 桩（litellm/paddleocr）+ `test/*` 桩路由 + vitest + `preview_*` 闭环。

## 验证原理

- **契约优先**：`OcrProvider`/`VisionProvider` 抽象可插拔，桩与真实现同接口。
- **离线可测**：16 用例全经桩，零网络零重依赖。
- **边界守卫**：413 超限 / 415 mime / 403 权限；无 provider 友好报错。
- **增量索引兼容**：`ImageLoader.content_hash` 按转录文本 sha256，与 Task 3 指纹一致。

## 验证过程

1. 后端：6 测试文件（16 用例）→ 11 模块/provider → 全量 **423 passed / 1 skipped**。
2. 前端：`AskPanel`/`useQuery` 附图 → 三件套绿。
3. 交互闭环（`preview_*`，dev 5173 / 后端 8200）：附图按钮→缩略图→带图提问 `POST /api/query/with-image` **200**（审计 `{"has_image":true,"vision_model":"test/stub-vision"}` 落库）→移除图片；移动端 375×812 无溢出。注：真实 qwen3-vl 未部署时带图 500 属环境缺 VLM，换 stub-vision 全链路 200。

## 已知边界与后续

- **真机验证边界**（留痕）：PaddleOCR-VL 本机/远端部署、qwen3-vl 真实识图质量、扫描 PDF OCR 均未本机跑真实模型，验证用 `test/stub-*` 桩证明链路；真实接入按 `.env.example` OCR/识图段。预计完成：随用户本机模型环境 W33+ 真机走查。
- 默认 `OCR_PROVIDER=none` / 未配 vision 不注册图片后缀——默认零配置行为不变。

## 证据

全量 423 passed / 1 skipped（2026-08-14）；前端三件套 + `preview_*` 交互记录见本报告。
