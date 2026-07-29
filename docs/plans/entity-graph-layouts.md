---
title: 实体图谱：Cytoscape/fcose 重写（治本）
type: plan
tags: [p3, frontend, entity-graph, cytoscape]
created: 2026-07-29
---

# 实体图谱：Cytoscape/fcose 重写（治本）

> 上一版用 react-force-graph-2d（d3-force 连续模拟）多轮调参仍不佳。经 [[roadmap]] 研究确认
> d3-force 无内置防重叠/边捆绑、连续模拟致拖动连锁，是天花板。改用 [[Cytoscape.js]] + fcose 治本。

## 背景痛点（用户反馈）
1. 线条相当凌乱（边交叉/重叠噪声）。
2. 跳数多时拖动一个节点 -> 整图混乱（d3-force 连续模拟连锁）。
3. 几个布局看不出区别（force/cluster 力配置几乎相同；hierarchy/radial 用 dagMode 退化为 blob）。
4. 视觉效果差、几乎无可读性（节点同大、标签重叠）。

## 根因
- **#2 拖动连锁**：d3-force 是连续模拟，力恒作用于全部节点 -> 拖一节点 reheat 后全局力重施、整图漂移。
  Cytoscape 布局**算一次即静止**，拖动只动该节点（架构级治本）。
- **#1/#4 无防重叠/边捆绑**：react-force-graph-2d 无内置约束；fcose 约束力导向 + bezier 边自动疏散平行边。
- **#3 布局退化**：dagMode 对有环实体图退化为力导向 blob。改用 4 种不同算法。

## 方案（Cytoscape + fcose，仅 1 个扩展）
- 依赖：`cytoscape` + `cytoscape-fcose`（约束力导向）；分层/径向/聚类用 cytoscape 内置 `breadthfirst`/`concentric`。
  移除 `react-force-graph-2d`。补 `src/vite-env.d.ts`（项目原缺，启用 `import.meta.env`）。
- 4 布局（视觉区分）：
  | 模式 | 算法 | 形态 |
  |:--|:--|:--|
  | 力导向 | fcose | 有机成簇，算法级防重叠 |
  | 聚类 | concentric(按类型环) | 同类型同环（环单色） |
  | 分层 | breadthfirst(BFS 树) | 以种子为根的层级树 |
  | 径向 | concentric(按跳数环) | 种子居中、逐跳向外 |
- 边降噪：`curve-style:bezier`（自动疏散平行边）+ `line-opacity:0.4` + 低缩放隐藏边标签（zoom<1.3）。
- 可读性：节点按度数变大小（16..38px，hub 视觉层级）+ 标签白描边 + 悬停高亮邻域（dim 非邻域）+ 低缩放隐藏节点标签（zoom<0.4）。
- 不漂移：仅结构变化（展开/折叠/切模式）才重布局；选中/焦点仅改数据。fcose `randomize:false` 增量保位置。

## 关键参数（实测调出）
- fcose：`nodeRepulsion:30000 / idealEdgeLength:120 / nodeSeparation:60`（弱值 6000/90/45 下软斥力压不过边拉力 -> 重叠；强值实测 overlapPairs=0）。
- 首次布局强制 `randomize:true`（`firstLayoutRef`，否则全堆原点重叠）；切模式也 `randomize:true`；增量 `randomize:false`。

## 验证（preview 程序化核验，非截图）
> 截图在本侧不可视，改用 cytoscape API 经 `window.__cy`（dev 钩子）程序化核验，比截图更精确。
- **#2 拖动**（初版：拖动只动 1 节点）→ 见下方「迭代 2026-07-29」改为**刚性联动**（拖一节点带整分量平移）。
- **#1/#4 零重叠**：4 布局均 `overlapPairs:0`（force/cluster/hierarchy/radial）。
- **#3 布局区分**：4 布局两两平均位移 182-397px；径向 rings 按 hop 0/1/2 半径递增（279/291/311，种子居中）。
- **悬停高亮**：26 节点中 23 非邻域 dimmed + 悬停节点与边 hl。
- **标签隐藏**：zoom 0.48 时边标签 opacity 0（<1.3）、节点标签 opacity 1（>0.4）。
- **三件套**：lint/test/build 全绿。

## 风险/取舍
- Cytoscape + fcose 包体较大（生产 chunk ~1.09MB / gzip 345KB）；可后续 code-split 优化。
- fcose 随机起用确定性 RNG（同输入同结果），可复现。
- 仅 1 个扩展（fcose）；若需更强边捆绑，可后续加 G6 的 edge-bundling 或 sigma edge-curve，但当前 demo 规模（<100 节点）bezier 已足够清晰。

## 迭代（2026-07-29）：展开直线 / 刚性联动 / 缩放倍率

用户反馈三问题：(a) 勾选新节点/首个节点时力导向图塌成一条直线；(b) 拖动无联动，要"刚性"（移动中图大小、边长不变）；(c) 缩放需多次滚轮、倍率太小。

### (a) 展开塌成直线 -> 新节点就近散布起始位置
- **根因**：增量展开时 `cy.add(toAdd)` 把新节点堆在原点（默认位置）-> fcose `randomize:false` 从退化共线起点收敛成直线。首次布局 `randomize:true` 不受影响（故"选择第一个节点"在多节点时正常，单节点图天然是线）。
- **修复**：边重建后，给新节点在已布局节点**质心周围环形散布**起始位置（`30..80px` + 随机角），fcose `randomize:false` 从正常 2D 起点收敛。
- **验证**：3 次增量展开（2/3 种子，16→29 节点，1→3 分量）`lineRatio` 0.82/0.57（0=直线、1=正方），`overlapPairs:0`。

### (b) 拖动刚性联动 -> 拖一节点带整连通分量平移
- **语义**：用户定义"刚性 = 移动中图大小、边长都不变"。唯一能保全**所有**边长与图大小的运动 = 连通分量整体平移（translation）。故拖一节点 -> 其连通分量（除自身）整体平移同 delta；其余分量不动。
- **实现**：`grab` 一次算定 `dragComp = component.not(node)`（drag 期间复用，免每 tick 重算）；`drag` 每 tick 算 delta -> `dragComp.shift({x:dx,y:dy})`；`free` 清状态。拖动节点本身由 cytoscape 移到光标，其余 shift 同 delta -> 整分量刚性平移。
- **验证**（经 `node.emit("grab"/"drag"/"free")` 驱动真实事件回调）：13/13 分量节点随拖动节点平移，30/30 边长全保（max deviation 0），其余 15 节点不动，`RIGID:true`。
- **注**：synthetic MouseEvent 无法触发 cytoscape 渲染器内部拖动（`mousedown` 处理器对非 trusted 事件 `e.which` 缺失走不到 `grab` 分支）；改用 `emit` 直驱事件回调验证监听器与逻辑，等价。真实用户拖动（trusted 输入）原生触发 grab/drag/free。

### (c) 缩放倍率 -> wheelSensitivity 0.25 → 2
- **根因**：`wheelSensitivity: 0.25`（4x 慢于默认 1）-> 单次滚轮缩放 ~1.2%，需多次滚动。
- **修复**：`wheelSensitivity: 2`（2x 默认），`maxZoom: 3 → 4`。
- **验证**：单次滚轮（deltaY=±100）缩放步进 9.65%（factor 1.0965），约 8x 于旧值；放大/缩小对称。

### 三件套
lint（tsc --noEmit）/ test（vitest 5 passed）/ build 全绿。

## 迭代（2026-07-29 #2）：切回图形变化 / 节点难选 / Ctrl 单拖 + Shift 展开

用户反馈三问题：(a) 切去切回图形变化（切 force->cluster->force 后 force 不复原）；(b) 几个节点无法手动选中；(c) 要 Ctrl+左键单独拖节点、Shift+左键展开/收起。

### (a) 切回图形变化 -> 各模式位置缓存恢复
- **根因**：切模式 `fresh=true` -> fcose `randomize:true` 重新随机散布 -> 切回 force 时是新随机布局，非原 force。
- **修复**：`modePositionsRef`（Map<mode, Map<id,{x,y}>>）。切走前缓存旧模式当前位置；切到新模式若有缓存且节点集一致（`every(id in cache)`）则恢复位置 + fit（不重布局）；否则跑布局。增量（展开/折叠）结构变化后 `clear()` 全缓存（节点集已变，旧缓存失效）。
- **验证**：force(F1)->cluster(C1)->force(F2)：`f2DiffersFromF1:0`（14 节点位置全复原），`clusterDiffersFromForce:14`（聚类确为不同布局）。切回应恢复原 force 布局。
- **附**：`runLayout` 增令牌（`layoutTokenRef`）+ 停旧布局（`layoutApiRef.stop()`）：切模式先 stop 上一个，避免新旧动画并发互覆；旧布局的 stop 回调按令牌判过期跳过，防错位 fit。

### (b) 几个节点无法选中 -> 增大节点 + 扩大命中区
- **根因**：叶节点（degree 1）原 16-18px，命中区小，实点易落空或被当拖动。选中逻辑本身无 bug（emit tap 全节点均能选中，已核）。
- **修复**：节点尺寸 `16+(d/maxDeg)*22`（16..38）-> `20+(d/maxDeg)*20`（20..40，叶节点底 20px）；节点样式加 `bounds-expansion:12`（扩大可点击包围盒，标签也易命中）。
- **验证**：`min size 22 / max 40 / floor20:true`；emit tap 全节点选中正常。

### (c) 交互模型 -> Ctrl+拖=单节点 / Shift+单击=展开 / 普通=选中 / 普通拖=刚性
- **grab**：`originalEvent.ctrlKey` -> `dragComp=null`，drag 时跳过 `shift` -> 仅该节点由 cytoscape 跟手（整图不动）；否则算连通分量作刚性平移。
- **tap**：`shiftKey` -> 展开/收起；`altKey` -> 焦点；其余（含 Ctrl+单击）-> 看详情选中。原 `Ctrl|Shift` 改为只 `Shift`（Ctrl 让给单节点拖）。
- **验证**：Ctrl+拖 `componentNodesMoved 0/13`（solo），普通拖 `13/13 跟随`（刚性回归），Shift+tap `expanded 0->1 / seeds 1->2`，Ctrl+tap `seeds 不变`（选中非展开）。
- 帮助文案更新：单击看详情；Shift+单击展开/收起；Alt+单击设焦点；Ctrl+拖动=单节点；普通拖动=整图联动。
