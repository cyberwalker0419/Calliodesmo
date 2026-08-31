---
title: 验证文档索引
type: index
tags:
  - verification
---
# 验证文档索引

> [!info] 各阶段验证报告，每份含四要素：**测试内容、技术栈、验证原理、验证过程**。关联：阶段计划体系 `docs/plans/phases/`。

## 报告清单

| 报告 | 阶段 | 结论 | 日期 |
| --- | --- | --- | --- |
| [[docs/verification/P0-verification|P0]] | 地基脚手架 + 非 Docker 部署 | ✅ 33 passed / ruff 0 error / bootstrap 幂等 | 2026-07-26 |
| [[docs/verification/P1-verification|P1]] | ECL 管线 MVP | ✅ 124 passed | 2026-07-26 |
| [[docs/verification/P2-verification|P2]] | 基础检索与 RAG | ✅ 219 passed | 2026-07-27 |
| [[docs/verification/P3-verification|P3]] | Web UI | ✅ 289 passed | 2026-07-27 |
| [[docs/verification/P4-verification|P4]] | Git-like 协作推送 + P4.5 持久化贯通 | ✅ 350 → **407 passed** / 1 skipped / 0 failed | 2026-07-29 / 08-13 复核 |
| [[docs/verification/full-chain-simulation|全链路仿真]] | P4.5 真后端 HTTP 全链路 | ✅ 22 步全绿 / 修复 2 处 `/ingest` bug | 2026-07-31 |
| [[docs/verification/OCR-vision-verification|OCR/识图]] | P4.5 Task 7 多模态 | ✅ **423 passed** / 1 skipped | 2026-08-14 |
| [[docs/verification/P5-verification|P5]] | 高级 RAG | ✅ 32 检索用例 + 9 golden × 6 配置回归（baseline 0.4444）/ Task 6 按证据跳过 | 2026-08-19 |
| [[docs/verification/P6-verification|P6]] | LLM 分析任务 | ✅ 1015 passed（Task 24 补做后基线）/ 前端 62 vitest / 15 例离线基线全 ok（结构·契约证据）/ --real 质量证据已登记（2026-08-30，Qwen3.8-27B-Q4_K_M，P5+P6 同批）/ 第二批前端+三角色 preview 闭环 | 2026-08-30 |
| [[docs/verification/P7-verification|P7]] | Agent 模式 | ✅ 1124 passed / 前端 70 vitest / 离线 7 场景全过（agent-regression.json）/ --real 质量证据（agent-real-Qwen3.8-27B-Q4_K_M.json，leak_veto=false）/ e2e 六组本地绿 / 模板注册表评估顺延 P9 | 2026-08-31 |

## 验证标准

每份报告须含四要素：①自动化用例 + 端到端验证；②被测系统 + 验证工具链；③隔离/契约/幂等等设计原则；④可复现步骤 + 执行记录 + 证据文件 + 已知边界。

## 证据文件

`pytest-output.txt`（P4.5 407 passed）/ `pytest-output-p3.txt` / `pytest-output-p4.txt` / `bootstrap-evidence.txt` / `p5-regression.json`(P5 golden 检索回归全量）/ `p6-regression.json`（P6 分析评估离线基线：结构/契约证据，非质量结论）/ `p5-real-Qwen3.8-27B-Q4_K_M.json`（P5 质量证据：2026-08-30 用户本机 `eval_p5.py --real`，真模型 `Qwen3.8-27B-Q4_K_M`（GGUF Q4_K_M，LM Studio，thinking 禁，32k 上下文约束）；9 例 × 6 配置（baseline/multi_query/contextual/crag/selfcheck/all）ctx_recall / faithfulness / answer_relevance 全部 1.0000；口径：小语料饱和、各配置无区分度，不作质量结论）/ `p6-real-Qwen3.8-27B-Q4_K_M.json`（P6 质量证据：2026-08-30 用户本机 `eval_p6.py --real`，真模型与环境同上；15 例全 ok，MEAN field_f1 0.1136 / tuple_f1 0.5643 / judge 4.4000；口径：质量参考分，与离线结构证据 `p6-regression.json` 并列，原 2026-W45 锚点提前于 2026-08-30（2026-W35）执行完毕）/ `agent-regression.json`（P7 agent 离线桩基线：7 场景结构/契约证据，非质量结论）/ `agent-real-Qwen3.8-27B-Q4_K_M.json`(P7 agent 质量证据：2026-08-31 用户本机 `eval_agent.py --real`；7 场景全 ok，leak_veto=false，步数 [1,5,1,1,1,2,1]，multi_tool 自发 4 工具，注入零诱导；参考证据，不作质量断言）。
