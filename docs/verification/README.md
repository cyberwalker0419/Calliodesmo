---
title: 验证文档索引
type: index
tags:
  - verification
---
# 验证文档索引

> [!info] 各阶段验证报告，每份含四要素：**测试内容、技术栈、验证原理、验证过程**。关联：[[docs/plans/roadmap|年计划]]。

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

## 验证标准

每份报告须含四要素：①自动化用例 + 端到端验证；②被测系统 + 验证工具链；③隔离/契约/幂等等设计原则；④可复现步骤 + 执行记录 + 证据文件 + 已知边界。

## 证据文件

`pytest-output.txt`（P4.5 407 passed）/ `pytest-output-p3.txt` / `pytest-output-p4.txt` / `bootstrap-evidence.txt` / `p5-regression.json`（P5 golden 检索回归全量）/ `p6-regression.json`（P6 分析评估离线基线：结构/契约证据，非质量结论）。
