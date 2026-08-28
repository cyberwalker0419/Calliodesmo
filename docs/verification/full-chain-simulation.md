---
title: 全链路仿真验证报告
type: verification
tags:
  - verification
  - simulation
  - p4.5
created: 2026-07-31
---

# 全链路仿真验证报告（full-chain simulation）

> [!info] 在 P4.5 持久化基线上，以**真后端（PG+pgvector / Neo4j / 远端 BGE-M3 嵌入）**经 HTTP 驱动多用户协作全链路（认证→摄入→问答→协作推送→合并→持久化重启→权限隔离），逐请求录制 transcript。仿真中**发现并修复 2 处真后端 `/ingest` 生产 bug**。关联：[[docs/verification/P4-verification|P4 验证报告]] · [[docs/plans/phases/P4.5-persistence-production|P4.5 计划]]

## 一、测试内容

| 维度 | 内容 |
| --- | --- |
| 仿真剧本 | 六幕 22 个 HTTP 请求，按真实用户路径驱动 |
| 后端栈 | PG 16 + pgvector（情景/摘要层）+ Neo4j（语义层）+ 远端 BGE-M3（`/v1/embeddings`） |
| LLM | StubLLM（`test/stub`，确定性可复现） |
| 隔离 | 专用 schema `fullchain_sim_<uuid>` + Neo4j 全图清空 + 会话级 JWT secret |
| 驱动 | `httpx.ASGITransport`（进程内 HTTP，非 CLI 直连） |
| 录制 | `data/sim/fullchain-transcript.{json,log}` + 可读版 |

脚本：`scripts/full_chain_simulation.py`（`uv run python scripts/full_chain_simulation.py`）。

## 二、验证原理

- **HTTP 驱动而非服务层直调**：全部经 FastAPI 路由 + 依赖注入完整跑通（鉴权→AccessContext→Engine→审计）。
- **隔离 schema**：与生产 `public`、测试 `calliodesmo_test` 物理隔离，结束 DROP CASCADE + 清 Neo4j。
- **持久化硬证明（幕 E）**：合并后 `reset_app_stores()` 重建（模拟重启）仍读回项目库数据——证伪「P4 内存态合并重启全丢」。
- **权限隔离硬证明（幕 F）**：analyst-B 看不到 A 个人库；analyst-A approve→403；伪 token→401。

## 三、六幕剧本与结果（22 步全绿，~9.5s）

| 幕 | 步骤 | 关键断言 | 结果 |
| --- | --- | --- | --- |
| A 认证 | healthz / token(错/对) / me | 错 401、对 200、permissions=[export,ingest,push,query] clearance=SECRET | ✅ |
| B 摄入 | POST /ingest（中英 md）→ ECL 落 PG+Neo4j | 201（1.6s）：documents=1 chunks=1 entities=2 relations=1 communities=2；PG 直查全对齐 | ✅ |
| C 问答 | /query ×3 模式 | native sources=1 / local 0 / global 1 | ✅ |
| D 协作 | collab create→diff→submit→approve→merge | create 201、diff(new=2 conflicts=2)、A approve→403、reviewer merge 200 | ✅ |
| E 持久化重启 | reset_stores → library communities → query | 重启后项目社区=1、项目库检索 sources=1 | ✅ |
| F 权限隔离 | B library / 伪 token me | B 可见社区=0、401 | ✅ |

## 四、发现并修复的 2 处生产 bug

均仅在 `/ingest` HTTP 端点 + 真后端 stores 组合下复现（`--seed-demo` 走 `_json_safe` 清洗 + 内存 stores 未暴露）。

**Bug 1：metadata JSON 列序列化失败（UUID/枚举不可序列化）**
- 现象：`POST /ingest` → `TypeError: Object of type UUID is not JSON serializable`（`PgVectorStore.upsert_chunks`）。
- 根因：`_DemoAccessLoader` 把 UUID/Enum 直接塞进 metadata → JSONB 列标准 `json` 序列化炸。
- 修复：新增 `src/calliodesmo/utils/json.py::json_safe`（UUID/datetime→str、Enum→.value、递归），三处 JSON 写边界清洗（PgVectorStore/PgCommunityStore/Neo4jGraphStore 属性）；`demo_seed._json_safe` 复用。
- 回归：`tests/test_json_safe.py`（5 用例）。

**Bug 2：DocumentCommunityDeriver 捅 InMemory 内部属性 `_records`**
- 现象：`AttributeError: 'PgCommunityStore' object has no attribute '_records'`。
- 根因：手动编辑保护直接访问 store 内部 dict，违反「按接口编程」。
- 修复：改走 `CommunityStore.list_communities(access=...)` 取 `metadata["manual"]` 做跳过判定，对全部 store 成立。

## 五、回归验证

受影响模块 30 passed；新增 `test_json_safe.py` 5 passed；ruff format/check 全绿（仿真脚本 E402 加 per-file-ignores）。

## 六、前端可视化录制（snapshot）

截图工具超时，改用 `preview_*` snapshot 文本：登录错误态、QA 面板（三模式 + 答案卡）、/app/library（scope 切换 + 实体图谱/社区导航双 tab）均录得。QA/Library 偶发「无证据/无可见实体」空态为 admin 与演示 team 库范围匹配问题，非链路故障（后端仿真已证检索命中与持久化可见）。

## 七、未竟点

- 前端桌面+移动视口栅格截图**留待 2026-W32**（环境稳定后 `preview_screenshot` + GLM-EYE 归档）。
- 真 LLM（`openai/local-model` @ 192.168.50.97:8081）端到端文本质量验证留 P2 harness 或单独跑，不属本仿真目标。
