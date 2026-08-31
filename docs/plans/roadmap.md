---
title: Calliodesmo 实施路线图
type: roadmap
created: 2026-07-26
---
# Calliodesmo 实施路线图

> [!info] 三层知识图谱驱动的智能情报分析平台
> 本文件为**年计划**（日/周/月/年四层之顶），向下 wikilink 到月计划、周计划与阶段任务计划（全部存于 `docs/plans/`，Obsidian 原生 markdown）。

## 摘要

GraphRAG（索引基座）+ LlamaIndex/LangGraph（检索与 Agent 编排）；LLM 与嵌入走可切换抽象接口。多用户采用**混合库模型**（团队/项目/个人三层）与 **Git-like 推送协作**（个人库 -> 项目库 -> 团队库，经审核合并）。文档社区管理 v1 同时完成自动派生（选项 A）与独立聚类+版本管理（选项 B，并入 P4）。API+CLI 优先，Web UI 在 P2 基础问答跑通后启动。学生独立开发、适中节奏（10-15h/周）。

## 已锁定决策

- 语言 Python 3.11+；uv 管理依赖；LLM 经 LiteLLM 可切换；嵌入 BGE-M3（`EmbeddingProvider` 可切换）
- 索引基座：GraphRAG 库形式集成（仅必要时局部 fork）；检索/Agent 编排：LlamaIndex + LangGraph
- 存储：Neo4j（语义层）+ PostgreSQL 16 + pgvector（向量/元数据，`VectorStore` 可换 Qdrant/Milvus）
- 交付：API（FastAPI）+ CLI（Typer）优先，Web UI 于 P2 后启动
- 规模：v1 单机 ≤5k 文档，六抽象接口保证扩展到 ≥50 万
- 多用户：混合库（个人/项目/团队）+ Git-like 推送（审核/合并/图谱合并）
- 认证：v1 本地账号（JWT），预留 OIDC/SSO；文档社区管理 v1 完成选项 A + B

## 三维正交权限模型

- **角色 RBAC**（控"能做什么"）：`analyst`/`reviewer`/`admin`；细粒度权限 `ingest`/`query`/`export`/`push`/`approve`/`manage_users`/`manage_community`。表：`users`/`roles`/`role_permissions`/`user_roles`。
- **访问等级 clearance**（控"能看什么"）：`public`/`internal`/`confidential`/`secret`，检索需 `clearance >= access_level`。
- **库范围 scope**（控"谁的数据"）：`personal`/`project`/`team` 三层；用户可被授予不同 project/team 的不同角色。
- **统一上下文** `AccessContext` 贯穿请求全生命周期，检索器/合成器统一过滤。**审计日志**记录谁/何时/做了什么（P0 骨架，P9 硬化）。

## Git-like 协作模型

- 三层库：个人库（工作库）-> 项目库（分支协作）-> 团队库（汇总，写需审核）。
- 推送流程：Push（提案合并）-> 贡献请求 MR（`draft->submitted->approved/rejected->merged`）-> 审核 -> 合并（**图谱合并**：实体按 name+type 去重、关系并集、来源打标）-> 差异 Diff -> 拉取 Sync（v1 单进程隐式）。
- **v1 务实范围**：推送=批量文档+抽取结果审核合并；复杂冲突解决/版本/回滚留 v2。

## 三层图谱与 ECL 管线

- 存储：情景层 Postgres（块+向量）· 语义层 Neo4j（实体关系）· 摘要层 Postgres+pgvector（摘要+向量）。
- ECL：**Extract**（实体/关系/声明/协变量四类 + 团队模板软引导，不 reject）-> **Cognify**（实体消解 + 图谱 + Leiden 社区 + 摘要）-> **Load**（三层落库，写个人库）。

## 文档社区管理

- **选项 A（v1）**：实体社区 `MENTIONS` 反查自动派生文档社区 + 分析师手动策展 UI（P1 自动 / P3 手动）。
- **选项 B（v1，并入 P4）**：独立文档嵌入聚类 + 社区版本/分支/合并/回滚（git-branch 式管理）。

## 精度与评估原则

- **评估 harness 贯穿**：golden 集 + 检索召回/忠实度/答案相关性回归；**精度由数据判定，不靠猜**。
- **精度杠杆排序**：①评估 harness ②混合检索+交叉编码器重排 ③实体消解 ④结构感知切分+overlap ⑤size 调参。
- **嵌入三输出全用**：BGE-M3 的 dense+sparse+multi-vec（近 BM25 / 近 ColBERT）。
- **切分**：结构感知过门槛；分层父子 + contextual retrieval + 语义切分**推迟 P5**。
- **L0/L1 分层摘要**仅服务展示层（列表预览/档案卡），**不进入检索/rerank/生成链路**。

## 阶段计划（P0-P9）

优先级：打通"数据进 -> 建图 -> 能问问题"主链路（P0-P2）-> UI（P3）-> Git-like 协作（P4）-> 高级检索/分析/Agent，差异化验证后置，规模化收尾。

- **P0 地基脚手架 ✅**：compose 起库、配置密钥、三接口+默认实现、用户/角色/权限表+JWT+AccessContext+审计、CI+冒烟。
- **P1 ECL 管线 MVP ✅**：多格式文档解析、四类抽取（模板软引导）、Cognify（消解+图谱+社区+摘要）、Load 三层落库、文档社区自动派生、CLI `ingest`、实体档案卡（ProfileCard）。
- **P2 基础检索与 RAG ✅（里程碑）**：NativeRAG/Local/Global 三模式、混合检索（稠密+稀疏+图 RRF）+ 交叉编码器重排、来源标注、按 AccessContext 过滤、FastAPI+CLI 暴露 Q&A、评估 harness。
- **P3 Web UI ✅**：登录注册、个人/组织库视图、问答面板、用户/团队/项目管理 UI、文档社区手动管理 UI、角色可见性。
- **P4 Git-like 协作推送 ✅**：个人/项目/团队库、MR 状态机、图谱合并（去重/并集/打标）、模板 review-gated 沉淀、文档社区选项 B（聚类+版本/回滚）。
- **P4.5 持久化与生产化 ✅**：store 真后端持久化（pgvector/Neo4j/PG）+ 增量索引 MVP + P4 合并落库贯通 + 双写一致性 + 前端 ingest UI + 异步 job + 三段式实体对齐 + 多模态 OCR/识图（详见 [[docs/plans/phases/P4.5-persistence-production|P4.5 计划]]）。
- **P5 高级 RAG 与智能检索 ✅**：MultiQuery / RAGFusion / CRAG / SelfCheck / contextual retrieval 完成，golden 回归基线 ctx_recall 0.4444（语义切分按证据跳过，见 [[docs/verification/P5-verification|P5 验证]]）。
- **P6 LLM 分析任务 ✅**：9 类分析（摘要/关键信息/时间线/实体识别/关系映射/任务/概念/问答/自定义）结构化报告完成（2026-08-30 合入 main，PR #11，1015 passed；`--real` 质量补跑提前于 2026-W35 执行完毕、证据入库；详见 [[docs/plans/phases/P6-llm-analysis-tasks|P6 计划]] 与 [[docs/verification/P6-verification|P6 验证]]）。
- **P7 Agent 模式 ✅**（2026-08-31 完成，PR 待合）：ReAct 主链（手写 StateGraph + 三重预算帽）+ 工具定义（只读七件 + 分析桥，三维门控，越权与不存在同消息）+ 多轮对话状态（ORM 三表 + PG checkpointer）+ agent golden 轨迹 harness（离线 + --real 双轨）+ 前端聊天面 + e2e 六组。承接项闭合：多轮对话状态并入本体；模板注册表评估结论顺延 P9；e2e 重锚 W44 补建。ReWOO 暂缓 / PlanExecute 门槛达标让位 / SSE 让位（均锚点 2026-W49；详见 [[docs/plans/phases/P7-agent-mode|P7 计划]] 与 [[docs/verification/P7-verification|P7 验证]]）。
- **P8 证据验证与幻觉检测**：答案-证据映射、接地度评分、低接地声明标记。承接：报告生命周期（删除 / 版本化 / 复核流）与置信度校准（ECE）。
- **P9 动态更新与规模化**：VectorStore 置换验证（Qdrant/Milvus）、Celery+Redis 异步批处理、审计硬化/合规/压测、社区规模化增量（增量索引 MVP 已剥离到 P4.5）。承接：L2 全库主题摘要（**P2 原指派 P6、此处改道**）、`api/deps.py` ProfileCard/BM25 改 PG TODO、三 store 谓词下推（均锚点 2026-W49）。

## Obsidian 计划文档结构

- `roadmap.md`（本文件，年计划）· `monthly/<YYYY-MM>.md`（月计划）· `weekly/<YYYY-Www>.md`（周计划，含日计划表）· `phases/P<n>-<slug>.md`（阶段任务计划，TDD）+ `entity-graph-layouts.md`（图谱布局专项）。
- 四层关系：年定里程碑 -> 月拆周 -> 周拆日 -> 阶段任务最细粒度。

## 时间表（学生 10-15h/周）

| 阶段 | 时间 |
| --- | --- |
| P0-P4 + P4.5 承诺批次 | 2026-07/08（提前完成，全员 407 passed） |
| P4.5 Task 5-7 / P5 高级检索 | 2026-08（完成）| 
| P6 LLM 分析任务 | 2026-08-30 完成（提前，1015 passed，PR #11） |
| P7 Agent 模式 | 2026-W36 开工，2026-08-31 完成（提前于 W48 窗口；PR #13 已合入 main） |
| P8-P9 | 2026-09 起滚动（随 P7 移交锚点） |

> [!note] 进度注记
> P0-P4 与 P4.5（含 Task 5-7）、P5 均已完成（2026-08-19，431 passed）；**P6 完成并合入**（2026-08-30，PR #11，1015 passed，9 类分析报告，`--real` 提前于 2026-W35 执行完毕、证据入库，[[docs/verification/P6-verification|P6 验证]]）；**P7 计划定稿**（2026-08-30）→ **P7 完成**（2026-08-31，提前于 W48 窗口；1124 passed + 前端 70 vitest + e2e 本地绿 + --real 质量证据 leak_veto=false；PR #13 已合入 main；移交锚点重锚：模板注册表评估 / e2e 补建 2026-W47→W44 已闭合，`--real` 定锚 W45 提前执行；[[docs/plans/phases/P7-agent-mode|P7 计划]] · [[docs/verification/P7-verification|P7 验证]]）；月/周计划按节奏滚动更新。

## 后续精化（v2）

- 图谱合并：同名不同义冲突解决、版本/回滚、按调查任务开分支。
- 认证：OIDC/SSO。
- 规模化：大规模分布式索引与检索。
