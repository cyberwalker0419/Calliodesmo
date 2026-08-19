---
title: 验证文档索引
type: index
tags:
  - verification
---
# 验证文档索引

> [!info] 本目录单独存放各阶段验证报告，每份报告须包含四要素：**测试内容、技术栈、验证原理、验证过程**。关联：[[docs/plans/roadmap|年计划]]。

## 报告清单

| 报告 | 阶段 | 结论 | 日期 |
| --- | --- | --- | --- |
| [[docs/verification/P0-verification\|P0 验证报告]] | P0 地基脚手架 + 非 Docker 部署 | ✅ 33 passed / ruff 0 error / bootstrap 幂等实测 | 2026-07-26 |
| [[docs/verification/P1-verification\|P1 验证报告]] | ECL 管线（Extract/Cognify/Load） | ✅ 124 passed | 2026-07-27 |
| [[docs/verification/P2-verification\|P2 验证报告]] | 基础检索与 RAG | ✅ 219 passed / ruff 0 error | 2026-07-27 |
| [[docs/verification/P3-verification\|P3 验证报告]] | Web UI | ✅ 289 passed / ruff 0 error | 2026-07-27 |
| [[docs/verification/P4-verification\|P4 验证报告]] | Git-like 协作推送 | ✅ 332 passed / 1 skipped / 1 failed(pre-existing) / ruff 0 error | 2026-07-29 |
| [[docs/verification/full-chain-simulation\|全链路仿真验证报告]] | P4.5 全链路仿真（HTTP 驱动真后端） | ✅ 22 步全绿 / 发现并修复 2 处 `/ingest` 真后端 bug / 30+5 回归通过 | 2026-07-31 |
| [[docs/verification/P4-verification\|P4 验证报告 ·持久化贯通段]]→ | P4.5 Task 1-4（真后端持久化 + 增量 + 合并落库贯通 + 双写一致性） | ✅ **407 passed / 1 skipped / 0 failed**（2026-08-13 全量实测；JWT 401 污染已修）/ ruff 0 error | 2026-07-31 起 / 08-13 复核 |
| [[docs/verification/OCR-vision-verification\|OCR/识图多模态验证报告]] | P4.5 Task 7（图片文档摄入 + 带图问答 /query/with-image） | ✅ **423 passed / 1 skipped / 0 failed**（全量净增 16 用例）/ 前端三件套绿 + preview 闭环 200 | 2026-08-14 |
| [[docs/verification/P5-verification|P5 高级 RAG 验证报告]] | P5 Task 1-5/7（改写/MultiQuery/contextual/CRAG/SelfCheck + golden 回归；Task 6 语义切分按证据跳过） | ✅ 32 检索层新用例 + 9 golden × 6 配置回归（baseline ctx_recall 0.4444，MultiQuery 空生成回退缺陷已修）/ ruff 0 error | 2026-08-19 |

## 目录结构

```
docs/verification/
├── README.md                 # 本索引
├── P0-verification.md        # P0 验证报告（四要素）
├── P1-verification.md        # P1 验证报告
├── P2-verification.md        # P2 验证报告
├── P3-verification.md        # P3 验证报告
├── P4-verification.md        # P4 验证报告（含 P4.5 持久化贯通验证段）
├── OCR-vision-verification.md # P4.5 Task 7 多模态 OCR/识图验证报告
├── pytest-output.txt         # 证据：pytest 原始输出（P4.5 407 passed）
├── pytest-output-p3.txt      # 证据：P3 pytest 输出
├── pytest-output-p4.txt      # 证据：P4 pytest 输出
├── bootstrap-evidence.txt    # 证据：bootstrap 两次运行（幂等）+ DB 内容佐证
└── full-chain-simulation.md  # 证据：P4.5 全链路仿真验证报告
```

## 验证标准

每阶段验证报告须满足：

1. **测试内容**：列出全部自动化用例（按模块/数量/验证点）+ 自动化之外的端到端验证项。
2. **技术栈**：被测系统技术 + 验证工具链。
3. **验证原理**：测试隔离策略、契约优先、幂等性、数学化断言等设计原则。
4. **验证过程**：可复现步骤 + 实际执行记录（命令/结果/证据文件）+ 已知边界与后续。
