---
title: 实体图谱：Cytoscape/fcose 重写（治本）
type: plan
tags: [p3, frontend, entity-graph, cytoscape]
created: 2026-07-29
---

# 实体图谱：Cytoscape/fcose 重写（治本）

> 上一版用 react-force-graph-2d（d3-force 连续模拟）多轮调参仍不佳：无内置防重叠/边捆绑、连续模拟致拖动连锁。改用 **Cytoscape.js + fcose** 治本。

## 背景痛点

1. 线条凌乱（边交叉/重叠）。
2. 拖动一节点 -> 整图混乱（d3-force 连续模拟连锁）。
3. force/cluster 布局几乎无区分；hierarchy/radial 退化为 blob。
4. 节点同大、标签重叠，可读性差。

## 根因与方案

- **拖动连锁**：d3-force 连续模拟 -> 拖一节点全图重算。Cytoscape 布局**算一次即静止**，拖动只动目标（架构级治本）。
- **防重叠/边捆绑**：fcose 约束力导向 + bezier 边自动疏散平行边。
- **布局退化**：dagMode 对有环图退化为 blob。改用 4 种不同算法：

| 模式 | 算法 | 形态 |
|:--|:--|:--|
| 力导向 | fcose | 有机成簇，算法级防重叠 |
| 聚类 | concentric（按类型环） | 同类型同环 |
| 分层 | breadthfirst（BFS 树） | 以种子为根的层级树 |
| 径向 | concentric（按跳数环） | 种子居中、逐跳向外 |

## 关键参数（实测调出）

- fcose：`nodeRepulsion:30000 / idealEdgeLength:120 / nodeSeparation:60`（弱值下软斥力压不过边拉力 -> 重叠）。
- 首次布局与切模式强制 `randomize:true`（否则全堆原点）；增量 `randomize:false` 保位置。
- 可读性：节点按度数 20..40px、标签白描边、悬停高亮邻域（dim 非邻域）、低缩放隐藏标签；边 `bezier + line-opacity:0.4`。
- 结构变化才重布局；选中/焦点仅改数据，不重排。

## 交互模型（迭代收敛）

- **单击**看详情 · **Shift+单击**展开/收起 · **Alt+单击**设焦点。（截图不可视，改用 cytoscape API 经 `window.__cy` 程序化核验。）
- **Ctrl+拖** = 单节点移动；**普通拖** = 刚性联动（该连通分量整体平移，边长/版型全保，13/13 节点跟随、30/30 边长零偏差）。
- **展开/折叠**：增量时新节点在质心周围环形散布（30..80px，防共线塌成直线）；切模式后各模式位置缓存恢复（`modePositionsRef`，切回 force 复原）。
- **缩放**：`wheelSensitivity:2`、`maxZoom:4`（单次滚轮步进 ~9.7%，旧值 8x 慢）。
- **命中**：节点 `bounds-expansion:12` 扩大可点击区（叶节点 20px 底）。

## 验证（程序化核验）

- 4 布局均 `overlapPairs:0`；两两平均位移 182-397px（布局确有区分）；径向 rings 半径按 hop 递增。
- 悬停高亮 23/26 非邻域 dimmed；缩放下标签显隐阈值正确。
- lint / vitest / build 三件套全绿。

## 风险/取舍

- 包体较大（生产 chunk ~1.09MB / gzip 345KB），可后续 code-split。
- fcose 用确定性 RNG（同输入同结果）。demo 规模（<100 节点）bezier 已足够清晰，更强边捆绑留后续。
