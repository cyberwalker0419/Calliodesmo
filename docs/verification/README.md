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

## 目录结构

```
docs/verification/
├── README.md                 # 本索引
├── P0-verification.md        # P0 验证报告（四要素）
├── pytest-output.txt         # 证据：pytest 原始输出
└── bootstrap-evidence.txt    # 证据：bootstrap 两次运行（幂等）+ DB 内容佐证
```

## 验证标准

每阶段验证报告须满足：

1. **测试内容**：列出全部自动化用例（按模块/数量/验证点）+ 自动化之外的端到端验证项。
2. **技术栈**：被测系统技术 + 验证工具链。
3. **验证原理**：测试隔离策略、契约优先、幂等性、数学化断言等设计原则。
4. **验证过程**：可复现步骤 + 实际执行记录（命令/结果/证据文件）+ 已知边界与后续。
