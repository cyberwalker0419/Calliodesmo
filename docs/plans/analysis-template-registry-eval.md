---
title: 团队级自定义分析模板注册表评估备忘录
type: eval-memo
tags:
  - plan/eval
  - p7
created: 2026-08-31
---
# 团队级自定义分析模板注册表评估备忘录（P7 T17）

> P6 移交项「评估」口径落地（原锚点 2026-W47 → 重锚 W44）。先结论后实现：
> 本备忘录按 [[docs/plans/phases/P7-agent-mode|P7 计划]] 决策 5 五项口径逐条评估，
> 产出决策记录；探针证据见 `scripts/probe_template_schema.py`（一次性，不进主代码）。

## 五项口径评估

### ① Agent 消费是否依赖注册表

**不依赖。** P7 T8 分析桥已兑现 P6 移交承诺：``run_analysis`` 直接消费
``BUILTIN_ANALYSIS_SPECS`` 九类 + ``custom``（用户 schema 经 ``sanitize_user_schema``
闸门）。``config/golden_analysis.yaml`` 15 例覆盖九类离线回归；覆盖缺口仅为
「团队命名模板复用」（同一团队反复提交同型自定义分析时的模板别名便利），
属**便利项非能力项**——无注册表时用户每次内联 schema 即可达成同等产出。

### ② jsonschema 完整校验与 sanitize 衔接

探针（2026-08-31 跑）：``sanitize_user_schema`` 对 $ref / 递归 / 超深（>4）/
超大（键数 >30 或字节 >4096）全拒、正常团队模板收——结构 / 深度 / 键数 /
字节四闸已覆盖注入与 DoS 面。增量面仅「实例级类型校验」（jsonschema 对产出实例
做 type 断言）——对**输出 schema**（约束模型产出形状，非校验用户输入）边际收益低；
引入 ``jsonschema`` 需新增 extra + 懒加载，依赖成本高于收益。

### ③ 持久化形态

纯 YAML 轻量形态（仿 ``ecl/extraction_template.py`` ``ExtractionTemplateRegistry``：
每调用点重建、无 ORM）只能做**全局只读**模板——无 team-scope 可见性、无按团队
隔离；与「团队级」命名诉求错位。升 ORM 形态（五 access 字段 + team scope，
``ChunkRecordORM`` 先例）可满足，但即 P6 警示的范围膨胀面（建表 / 管理端点 /
缓存失效 / 迁移）。

### ④ 与内置九类冲突语义

轻量形态下可定义「custom 模板名与内置九类同名时禁止覆盖（保留内置、报错提示）」，
语义可管理；但需文档与测试双钉，属实现期成本。

### ⑤ 多用户写审计

文件形态**无审计通道**（谁 / 何时 / 改了什么不可追溯），与平台审计文化（每次
工具调用 / 提交 / 导出均 ``record_audit``）冲突；ORM 形态可满足但叠加 ③ 的膨胀面。

## 决策记录

**结论：整体顺延 P9 留痕（T18 取消，锚点 2026-W49 随 P9 清单一并重评）。**

理由链：轻量版 = ③⑤ 不达标（无 team 隔离、无写审计）的半成品；ORM 版 = 范围
膨胀（P6 移交原文即「评估」而非实现，且 P7 承诺批次优先）。①② 表明现状能力
（九类 + custom + sanitize 四闸）已覆盖真实需求，注册表为纯增量便利——让位序末位
（T21 → T20 → T18）正确生效。重评前置：P9 审计硬化批给出写审计基线后，ORM 形态
成本下降，届时一并决策。

## 回写

- [[docs/plans/phases/P6-llm-analysis-tasks|P6 计划]] 范围外表 / Task 22 留痕：
  锚点 2026-W47→W44 评估完成，结论顺延 P9。
- [[docs/verification/P6-verification|P6 验证]] 未竟清单：同结论更新。
