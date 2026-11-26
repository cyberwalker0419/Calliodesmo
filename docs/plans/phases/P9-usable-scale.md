---
title: P9 质量硬化与可用化实施计划
type: phase-plan
phase: P9
tags:
  - plan/phase
created: 2026-11-15
---
# P9 质量硬化与可用化实施计划

> 承接 [[docs/plans/phases/P8-evidence-verification|P8 证据验证与幻觉检测]]（T1–T7 + T9 已合入 main，PR #14）。P8 让平台「会自证」，但 `--real` 质量轨暴露三个真问题：**引注精确率 / 接地度 0.4091**（答案模板前缀与转述句拉低核验覆盖率）、**注入违规 2 条**（提示层防御挡不住输出层全文倾倒与内部元数据泄漏）、**ECE 样本仅 22 条**（不足 100，校准结论只能当参考）。P9 把这三条硬化到可宣称质量的水平，同时补齐 P9 原定项（审计硬化 / 压测 / VectorStore 置换 / 谓词下推 / 迁移可重复）与**可用化最小集**（健康检查、配置校验、部署引导可复现、文档同步），把项目推进到「拿到就能用」。

> **For agentic workers:** 严格按 Task 编号顺序执行；步骤用 checkbox（`- [ ]`）跟踪；每 Task 内遵循 TDD 五连（写失败测试 → 跑确认失败 → 实现 → 跑绿 → 提交，可加装配 / 迁移步骤）；不得跨 Task 顺手扩张范围，发现额外问题就地留痕（未竟点 + 周次 `2026-Www`）；新 ORM 必须在 `models.py` 集中导入注册；新配置项必须 `config.py` 与 `.env.example` 双同步；DB 依赖测试自动打 `@pytest.mark.db`；有视觉表现的前端改动必须走 `preview_*` 交互闭环 + 桌面 / 移动双视口；验证读取的材料一律经 `visible_to` 三维过滤。全量回归基线 **1288 passed / 1 skipped**（P8 末），P9 只增不减。

## 目标与范围

**总目标**：让「质量」从可运行变成可宣称——真模型上引注与接地度达到门槛、注入零诱导、ECE 有 ≥100 样本支撑；让「运维」从手工摸索变成可复现——健康检查、配置校验、迁移与压测有脚本、有证据；让「规模」有实测基线——谓词下推与 VectorStore 置换经契约与压测验证。

**本阶段交付（承诺批次，按 Task 顺序）**

| # | 交付 | 判据 |
| --- | --- | --- |
| 1 | QA 答案接地硬化 | 模板前缀剥离 + 句级引注纪律 + 多块证据核验 + 关键事实匹配；离线契约测试全绿，矛盾误报不升 |
| 2 | 输出层注入防御 | 全文倾倒 / 内部元数据 / 系统提示泄漏在输出层被拦截或脱敏；注入探针违规 0 |
| 3 | 评估语料 v3 + 交叉验证 ECE | 语料 ≥70 例，可核验声明 ≥120，5 折交叉验证 ECE 样本 ≥100 |
| 4 | 审计硬化 | 审计查询 API（过滤 / 分页 / 权限）+ 敏感字段脱敏 + 留存策略；越权 403 |
| 5 | 健康检查与配置校验 | `/readyz` 组件级就绪；请求 ID 贯穿；`calliodesmo doctor` 配置体检 |
| 6 | 迁移可重复 | 版本化迁移台账 + `db migrate` 幂等；Alembic 引入与否有明确结论 |
| 7 | 谓词下推与 VectorStore 置换 | 可见性过滤下沉到取数层；memory / pgvector 契约对等测试；swap 有回归 |
| 8 | 压测基线 | 离线可复现压测脚本，落 p50/p95/吞吐与越权零泄漏证据 |
| 9 | 部署引导可用化 | bootstrap / compose / 文档与 `doctor`、`db migrate`、`/readyz` 对齐 |
| 10 | W49 重评决策 | SSE / ReWOO / PlanExecute / RAG 记忆 / Agent 会话生命周期逐项「做 / 移交」 |
| 11 | 收尾 | `--real` 质量轨证据 + P9 验证报告 + 全量回归 + 前端三件套 + e2e 14/14 |

**范围外（显式归属，不在 P9 做）**

| 事项 | 去向 |
| --- | --- |
| Agent 写行动工具（ingest / push / merge / 社区管理） | P10+（需写行动审计模型 + 复核流扩展） |
| NLI / 语义蕴含 / 交叉编码器级核验 | P10+（P9 v2 用关键事实匹配 + 可选 LLM judge） |
| 跨 chunk 关系补抽 / 别名歧义精解 | P10 抽取批（P1 移交，P8 只验证不改进） |
| 分布式任务队列 / 多副本调度 | P10+（单机压测基线先行） |
| L2 摘要 / ProfileCard 改 PG | P10（与谓词下推同批评估） |

## 验收口径

**双轨继续严格分离**：离线证据只承诺结构与契约；质量结论仅来自 `--real`。P9 新增**运维轨**（`doctor`/`readyz`/压测）作为第三类证据，三者并列登记。

**质量门槛（沿用 P8，不因口径修订而放宽）**

- `citation_precision ≥ 0.80`、`claim_grounding ≥ 0.80`；
- `unsupported_rate ≤ 0.10`、`contradiction_rate ≤ 0.05`；
- `ece ≤ 0.10`（5 折交叉验证，样本 ≥ 100）；
- 注入探针违规 = 0（一票否决，离线 + `--real` 双轨）。

**指标口径 v3（透明登记，不静默改口径）**

| 变更 | 理由 | 影响 |
| --- | --- | --- |
| 答案模板前缀 / 连接词剥离后再切句核验 | 「根据提供的上下文，」不是可核查声明 | 减少无意义 uncited 计数，不改变「声明是否被支撑」 |
| 引注句按**全部被引块**联合核验 | 一句引多块是合法答法，单块核验会误判 unsupported | 提升 citation_precision 的口径正确性 |
| 关键事实匹配（数字 / 日期 / 英文实体 + 内容二元组） | 中文转述与原文不必逐字相同 | 提升 paraphrase 场景的 supported 判定 |
| 句级引注纪律（仅当该块可支撑时补引注） | 降低未引注率，同时不伪造证据 | uncited_claim_rate 下降，citation 可核验 |
| ECE 改 5 折交叉验证 | 单次奇偶留出只用到一半样本 | 100 条可核验声明即可满足 ≥100 门槛 |

口径变更须在 `docs/verification/P9-verification.md` 与证据 JSON 的 `metric_revision` 字段如实标注，并与 P8 数字并列展示。

## 关键决策

1. **先修产品、再谈指标**：P8 的低分主因是「答案转述 + 模板前缀 + 单块核验」造成的核验覆盖不足，不是模型疯狂幻觉（unsupported 仅 0.1364）。P9 先改答案合成与核验口径，让指标反映真实接地程度；任何口径变更透明登记，不通过删样本 / 放水阈值达标。
2. **引注补全只在可核验时发生**：答案后处理只对「句子能被某块证据支撑（覆盖率达标）」的句子补 `[chunk_id]`，不为无据句子编造引注；无法支撑的句子保持无引注并计入 `uncited_claim_rate`。
3. **输出层防御是最后一道闸**：提示层（system prompt）继续防注入，输出层新增 `security/output_guard`——对全文倾倒（与任一源文连续重合 ≥200 字符）、内部元数据（`access_level` / `library_scope` / `owner_id` 等）、系统提示回声做拦截与脱敏；拦截事件入审计与侧车，不静默丢弃。
4. **ECE 用交叉验证而非扩样单留出**：5 折交叉验证让每条声明恰好进入一次留出集，样本利用率从 50% 升到 100%，统计上更稳；语料仍扩到 ≥70 例，保证总样本 ≥120。
5. **Alembic 决策按收益 / 风险判定**：现有 `create_all + migrate.py` 覆盖增量加列；P9 先补**版本化迁移台账**（`schema_migrations` 表 + 有序迁移函数 + `db migrate`），保证既有库升级可重复、可审计。Alembic 需为全库历史 DDL 编写基线，风险高、收益低，**P10 再评估**（判据：出现列改名 / 回滚 / 数据回填类迁移 ≥2 次）。
6. **谓词下推下沉到取数层**：可见性过滤必须在「取候选」时生效（SQL WHERE / 内存预过滤），不得先取全量再后置过滤；`get_chunks_by_ids` 增加 access 过滤参数，堵住按 ID 直取的越权面。
7. **压测离线可复现**：压测走内存 stores + 桩模型，固定语料与并发梯度，产出可重复的 p50/p95 与越权泄漏计数；不把真模型时延混入规模基线。
8. **W49 重评按判据不按情绪**：SSE / ReWOO / PlanExecute / RAG 记忆逐项列判据（用户可感知收益、实现成本、回归风险），做则进 P9 尾巴，不做则明确移交 P10 并写锚点。

## 为什么是这个顺序

1. **质量硬化先行**（T1–T3）：引注与核验口径决定 `--real` 数字，先改产品再扩语料，避免用旧口径扩出来的样本白跑。
2. **安全闸紧随其后**（T2）：输出层防御会改变注入探针判定，必须先于质量轨重跑。
3. **运维与规模在中段**（T4–T8）：互不阻塞，且都要在全量回归稳定时做，避免质量改动与结构改动混在一次提交。
4. **文档与决策最后**（T9–T11）：先有证据，再写结论；W49 重评需要 T8 的压测数据作输入。

---

## Task 1: QA 答案接地硬化 ✅ 必做

**目标：** 提升真模型答案的可核验性：剥离模板前缀与连接词、句级引注纪律、多块联合核验、关键事实匹配、矛盾误报收敛。

**Files:** 新 `src/calliodesmo/retrieval/answer_postprocess.py` · 改 `src/calliodesmo/retrieval/answer_synthesizer.py`（prompt v2 + 后处理）· 改 `src/calliodesmo/verification/engine.py` · 改 `src/calliodesmo/verification/pipeline.py` · 测试 `tests/test_answer_postprocess.py` / `tests/test_verification_engine.py` / `tests/test_answer_synthesizer.py`。

- [x] **Step 1:** 写失败测试：模板前缀剥离（根据提供的上下文 / 基于上述材料 / 综上所述）、连接词剥离、句级引注补全只在覆盖率达标时发生、多块联合核验、关键事实（数字 / 日期 / 英文实体）匹配、否定词误报（不仅 / 未来 / 不同）不判矛盾。
- [x] **Step 2:** 跑确认失败 → 实现 `answer_postprocess.py`（纯函数：`strip_answer_boilerplate` / `attach_sentence_citations`）与引擎扩展（`verify_claim_against` 多块联合、`_key_facts` 匹配、矛盾阈值收紧）。
- [x] **Step 3:** `answer_synthesizer` prompt v2：逐句引注、直接作答不写 preamble、禁止输出内部元数据；合成后经后处理再接输出层守卫。
- [x] **Step 4:** 跑绿 + 离线评估不倒退（43/43 判定、矛盾 10/10）；提交：`feat(retrieval): QA 答案接地硬化与引注纪律`。

**验收：** 后处理纯函数确定性可测；多块联合核验有专项用例；离线判定与矛盾黄金集不倒退。

---

## Task 2: 输出层注入防御与敏感输出护栏 ✅ 必做

**目标：** 提示层之外加输出层闸门：全文倾倒、内部元数据、系统提示回声、注入服从话术被拦截或脱敏；事件入审计与侧车。

**Files:** 新 `src/calliodesmo/security/__init__.py` / `output_guard.py` · 改 `retrieval/answer_synthesizer.py` · 改 `agent/job_worker.py` · 改 `analysis/engine.py`（文本字段扫描）· 测试 `tests/test_output_guard.py` / 三输出面接入测试。

- [x] **Step 1:** 写失败测试：源文连续 200 字符倾倒被拦截、`access_level` 等元数据泄漏被脱敏、系统提示回声被拦截、正常拒绝话术（「不能泄露系统提示」）不误伤、注入服从话术标记。
- [x] **Step 2:** 跑确认失败 → 实现 `output_guard.guard_output`（纯函数，返回 `GuardResult(clean_text, violations, action)`）；单源覆盖度 / 连续重合用最长公共子串近似（滑窗长度固定，确定性）。
- [x] **Step 3:** 接入 QA 合成器、Agent 回合落库前、分析报告文本字段；拦截事件写审计 `output_guard`（只记类别与计数，不记原文）。
- [x] **Step 4:** 跑绿 + 提交：`feat(security): 输出层注入防御与敏感输出护栏`。

**验收：** 四类违规各有拦截用例；拒绝话术零误伤；三输出面接线完整。

---

## Task 3: 评估语料 v3 + 交叉验证 ECE ✅ 必做

**目标：** 把质量结论从「样本不足参考值」变成「≥100 样本的门槛判定」：QA 语料扩到 ≥70 例、核验语料扩到 ≥60 条、ECE 改 5 折交叉验证。

**Files:** 改 `config/golden_qa_v2.yaml`（新增至 v3，保留 v2 兼容注释）· 改 `config/golden_verification.yaml` · 新 `config/eval_corpus/`（可追踪的评估语料副本，`data/demo` 缺失时回退）· 改 `scripts/eval_p8.py`（语料版本 / 交叉验证）· 改 `src/calliodesmo/eval/metrics_grounding.py`（`cross_validated_ece`）· 测试 `tests/test_metrics_grounding.py` / `tests/test_golden_verification.py`。

- [x] **Step 1:** 写失败测试：5 折切分确定性（同输入同折）、空样本 / 单样本、交叉验证 ECE 聚合公式、语料规模下限断言（QA ≥70、claim ≥60）。
- [x] **Step 2:** 跑确认失败 → 实现 `cross_validated_ece(confidences, outcomes, folds=5)`；`eval_p8.py` 用交叉验证 ECE 并保留单留出对照。
- [x] **Step 3:** 扩语料：QA 新增 35 例（正例 / 多跳 / 无答案 / 干扰 / 注入五类平衡）；verification 新增 17 条（含 3 条注入探针）；新增 `config/eval_corpus/` 三件语料副本（与 `data/demo` 同名同内容）。
- [x] **Step 4:** 跑绿 + 落离线基线；提交：`feat(eval): P9 评估语料 v3 与交叉验证 ECE`。

**验收：** 语料规模满足下限；交叉验证 ECE 有单测；离线基线可复现。

---

## Task 4: 审计硬化 ✅ 必做

**目标：** 审计日志从「只写」变成「可查、可脱敏、可留存」：管理查询 API（过滤 / 分页）、敏感字段脱敏、留存策略配置。

**Files:** 改 `src/calliodesmo/audit/service.py`（`sanitize_audit_detail` / `list_audit_logs` / `purge_expired_audit`）· 改 `src/calliodesmo/api/admin.py`（`GET /admin/audit`）· 改 `src/calliodesmo/config.py` + `.env.example`（`audit_retention_days`）· 测试 `tests/test_audit_hardening.py` / `tests/test_admin_api.py`。

- [x] **Step 1:** 写失败测试：detail 内 `password` / `token` / `secret` 键值脱敏为 `***`；按 action / user / 时间过滤与分页；无 `manage_users` 403；留存清理只删过期行。
- [x] **Step 2:** 跑确认失败 → 实现脱敏与查询服务 + API + 配置；`db seed`/CLI 不动，清理走显式函数（不自动删）。
- [x] **Step 3:** 跑绿 + 提交：`feat(audit): 审计查询、脱敏与留存策略`。

**验收：** 脱敏对嵌套 detail 生效；查询过滤与分页正确；越权 403；清理函数幂等。

---

## Task 5: 健康检查与可观测性最小集 ✅ 必做

**目标：** 运维可见：`/readyz` 组件级就绪、请求 ID 贯穿、`calliodesmo doctor` 配置体检（含生产 JWT 密钥强制）。

**Files:** 新 `src/calliodesmo/api/observability.py`（请求 ID 中间件 + readyz 组装）· 新 `src/calliodesmo/config_validation.py` · 改 `src/calliodesmo/api/app.py` · 改 `src/calliodesmo/cli.py`（`doctor`）· 改 `src/calliodesmo/config.py` + `.env.example` · 测试 `tests/test_observability.py` / `tests/test_config_validation.py`。

- [x] **Step 1:** 写失败测试：`/readyz` 在 DB 不可达时 503 且组件明细可读、可用时 200；响应头回显 / 生成 `X-Request-ID`；doctor 检出默认 JWT 密钥（生产为 error）、非法 store 后端、缺 LLM key、非法数据库 URL。
- [x] **Step 2:** 跑确认失败 → 实现配置校验（纯函数 `validate_settings`）+ 中间件 + readyz（DB `SELECT 1`，Neo4j 后端时校验连接，LLM/嵌入只查配置不连外网）+ CLI。
- [x] **Step 3:** 跑绿 + 提交：`feat(api): 就绪探针、请求 ID 与配置体检`。

**验收：** readyz 不泄漏密钥；请求 ID 恒存在；doctor 退出码与级别正确；生产默认密钥被拦截。

---

## Task 6: 数据库迁移可重复 + Alembic 决策 ✅ 必做

**目标：** 既有库升级可重复、可审计：`schema_migrations` 版本台账 + 有序迁移步骤 + `db migrate`；Alembic 引入与否给出明确结论。

**Files:** 新 `src/calliodesmo/db/migrations.py` · 改 `src/calliodesmo/db/migrate.py`（接入台账）· 改 `src/calliodesmo/cli.py`（`db migrate`）· 测试 `tests/test_db_migrations.py`（db 标记）。

- [x] **Step 1:** 写失败测试：首次执行应用全部迁移并记录版本；重复执行零改动（幂等）；失败步骤不记账、可重试；`db init` 后 `db migrate` 为纯 no-op。
- [x] **Step 2:** 跑确认失败 → 实现台账（`CREATE TABLE IF NOT EXISTS schema_migrations`）+ 迁移清单（版本 / 描述 / 可重入函数）+ CLI。
- [x] **Step 3:** 文档记录 Alembic 决策（P10 再评估，判据见关键决策 5）；跑绿 + 提交：`feat(db): 版本化迁移台账与 db migrate`。

**验收：** 幂等与失败重试有专项测试；既有 `ensure_missing_columns` 行为不变。

---

## Task 7: 检索谓词下推与 VectorStore 置换校验 ✅ 必做

**目标：** 可见性过滤下沉到取数层，堵住按 ID 直取的越权面；memory / pgvector 后端契约对等，swap 有回归保障。

**Files:** 改 `src/calliodesmo/interfaces/vector_store.py`（`get_chunks_by_ids(..., access=)`）· 改 `providers/in_memory_vector_store.py` / `pg_vector_store.py` · 改 `retrieval/local_search.py` / `global_search.py` / `in_memory_sparse_index.py`（预过滤）· 测试 `tests/test_vector_store_contract.py` / `tests/test_local_search.py` / `tests/test_library_scope_filter.py`。

- [x] **Step 1:** 写失败测试：`get_chunks_by_ids` 传 access 时过滤不可见块；local / global 检索越权块零泄漏；sparse 预过滤等价于原后置过滤（结果集合一致）；两种后端对同一数据返回一致可见集。
- [x] **Step 2:** 跑确认失败 → 实现接口扩展（默认 `access=None` 保持向后兼容）+ 两后端过滤 + 调用方传 access + sparse 预过滤。
- [x] **Step 3:** 跑绿 + 提交：`refactor(retrieval): 谓词下推与向量后端契约对等`。

**验收：** 越权零泄漏；两后端契约对等；既有检索结果不变。

---

## Task 8: 压测基线 ✅ 必做

**目标：** 规模与并发的实测基线：离线可复现压测脚本，落 p50 / p95 / 吞吐 / 越权泄漏计数证据。

**Files:** 新 `scripts/loadtest_p9.py` · 新 `src/calliodesmo/eval/loadtest.py`（分位数与并发 runner 纯函数）· 测试 `tests/test_loadtest_metrics.py` · 证据 `docs/verification/p9-loadtest.json`。

- [x] **Step 1:** 写失败测试：分位数计算（含边界 / 空样本）、并发 runner 计数（成功 / 失败 / 泄漏）、结果确定性结构。
- [x] **Step 2:** 跑确认失败 → 实现 runner（内存 stores + 桩 LLM + 固定语料，并发梯度 1/5/20，每级 N 次查询）与脚本。
- [x] **Step 3:** 跑离线压测落证据；提交：`feat(eval): P9 压测基线与分位数工具`。

**验收：** 脚本可重复执行且数字稳定；越权泄漏 0；证据 JSON 登记。

---

## Task 9: 部署引导可用化 ✅ 必做

**目标：** 拿到源码即可跑：bootstrap 接入 `db migrate` 与 `doctor`，compose 增加应用健康检查，文档与 README 同步新命令。

**Files:** 改 `scripts/bootstrap.sh` / `bootstrap.ps1` · 改 `Dockerfile`（健康检查注释与口径）·
改 `README.md` / `docs/deploy/native.md` / `docs/deploy/docker.md` / `docs/deploy/testing.md` ·
测试 `tests/test_cli.py`（doctor / db migrate 冒烟）。

- [x] **Step 1:** bootstrap 增加 `db migrate` 与 `doctor` 步骤；容器 HEALTHCHECK 保持指向
  `/healthz`（存活），`/readyz` 作为人工 / LB 就绪查法写进文档——就绪探针会把「模型 key
  未配」判 503，用作 liveness 会误杀容器，原计划的 compose healthcheck 指向 /readyz 就此修正；
  文档补命令与故障排查。
- [x] **Step 2:** 本地实跑 bootstrap 全链（建表 → 种子 → 迁移核对 → 体检）验证幂等；
  提交：`chore(deploy): 引导脚本接入迁移核对与体检，存活/就绪探针分家`。

**验收：** 新库从零到 serve 的命令链最短且可重复；文档命令与代码一致。

---

## Task 10: W49 重评决策 + Agent 会话生命周期 ✅ 必做

**目标：** 对 P7/P8 移交到 W49 的五项逐条给结论（做 / 移交 + 判据 + 锚点），并把「做」的
那一项（会话生命周期）实现到位。

**Files:** 新 `src/calliodesmo/agent/session_lifecycle.py` · 改 `agent/access.py`（已删除即不可用）·
改 `api/agent.py`（DELETE / restore / include_deleted）· 改 `db/models_agent.py` + `db/migrations.py`
（0006 步骤）· 前端 `features/agent/{AgentPage.tsx,api.ts,useAgent.ts}` + `api/types.ts` ·
改本计划「暂缓与移交记录」· 测试 `tests/test_agent_session_lifecycle.py`。

- [x] **Step 1:** 写失败测试：软删除后默认列表不可见、恢复后可见、重复删幂等、越权与不存在
  同文案、已删除会话跑回合 404、admin 可代删、API 三端点与权限矩阵。
- [x] **Step 2:** 跑确认失败 → 实现服务层（谓词下推 + 密级不洗白复检）与 API / 迁移步骤 0006。
- [x] **Step 3:** 前端：侧栏行内二次确认删除 + 「显示已删除」恢复入口；移动端同等入口；
  修「新会话命名用 total+1 导致删除后撞名」。
- [x] **Step 4:** 跑绿（vitest + 三件套 + preview 桌面闭环）+ 提交：`feat(agent): Agent 会话软删除与恢复`。
- [x] **Step 5:** 五项重评结论写进「暂缓与移交记录」与本 Task 结论段；提交 `docs(plans)`。

**验收：** 会话可删可恢复且权限/审计齐备；五项均有明确结论，无隐式尾巴。

**W49 重评结论（判据：用户可感知收益 / 实现成本 / 回归风险 / 有无数据支撑）**

| 项 | 结论 | 依据 | 锚点 |
| --- | --- | --- | --- |
| Agent 会话生命周期（P8 T8） | ✅ 做（本 Task 闭合软删除 + 恢复） | 隐私与列表噪声是可用级缺口；复用报告生命周期范式，成本低 | 本阶段 |
| 会话归档 / 共享范围变更 | ⏸ 移交 P10 | 归档只是折叠（收益低）；共享要重推三维权限与会话密级快照语义（风险高） | 2026-W49 |
| SSE 回合流式（P7 T21） | ⏸ 移交 P10 体验批 | 收益真实（首字延迟），但要动 API/前端/代理缓冲与取消语义四端；本轮先把质量与安全做扎实 | 2026-W49 |
| ReWOO / PlanExecute（P7 T20/T22） | ⏸ 移交 P10 模型层 | 无区分度数据：agent golden 多步场景样本仍小，先按压测与质量轨补齐证据再决策 | 2026-W49 |
| RAG 记忆（跨会话长期记忆） | ⏸ 移交 P10 数据层 | 需要先有「记忆」的权限归属与留存策略（与审计留存同批设计），否则越权面扩大 | 2026-W49 |
| Alembic 迁移 | ⏸ 不引入（台账替代） | 需求全是加可空列 / 补索引 / 列型 widening；判据：出现改名 / 回滚 / 数据回填类需求 ≥2 次再切 | 2026-W49 |
| BM25 / ProfileCard 改 PG | ⏸ 移交 P10 | 单机内存后端可用；横向扩展（多进程 serve）前必须改，判据已写进 `api/deps.py` TODO | 2026-W52 |

---

## Task 11: 收尾（--real / 验证报告 / 文档 / 全量回归 / PR）✅ 必做

**Files:** 新 `docs/verification/P9-verification.md` · 改 `docs/verification/README.md` · 改 `CLAUDE.md` / `AGENTS.md` / `README.md` · 证据 `docs/verification/p9-real-<模型>.json` / `p9-regression.json` / `p9-loadtest.json`。

- [x] **Step 1:** 离线轨：全量 `pytest -q` 绿（≥1288 基线）+ `ruff check` / `format --check`；前端 `lint` / `test` / `build`；e2e 14/14。
- [ ] **Step 2:** ⏸ 受阻（两次：2026-11-16 LLM 端点 `115:8888` 连接被拒；2026-11-26 复测 LLM 已恢复、嵌入服务 `192.168.50.97:11234` TCP 超时致 ingest 中断。恢复清单见验证报告，锚点 2026-W47） 质量轨：`scripts/eval_p8.py --real` 于 head 端点执行，落证据并按门槛如实判定；未达则写明差距与锚点。
- [x] **Step 3:** 写 P9 验证报告（四要素 + Task 闭合矩阵 + 未竟清单 + 口径变更说明）。
- [x] **Step 4:** 文档同步：阶段与结构段、README badge、验证索引。
- [x] **Step 5:** 提交 + 推送分支 + 创建 PR；CI 绿后合入 main 并同步 Gitea 镜像。
  → PR #15 于 2026-11-17 squash 合入 main（`c1e4d16`）；CI 两项 pass（修了两处 CI 专属
  问题：runner 镜像迁移后缺 Python 3.12、自建夹具漏打 `db` 标记）。

**验收：** 三类证据齐备；文档与代码一致；PR 合入 main。

---

**闭合实录（2026-11-16）**：T1–T10 全部闭合并逐 Task 提交（提交链见
[[docs/verification/P9-verification|P9 验证报告]] 的 Task 闭合矩阵）。结构轨全绿：
后端 1438 passed / 1 skipped、离线判定 60/60 与矛盾 10/10 不倒退、审计/探针/台账/
下推/压测/会话生命周期均有专项测试；运维轨三份压测证据 + readyz/doctor 实测；
前端 82 vitest 与三件套绿、e2e 12/14（2 例 agent 需真模型 tool calls，桩模型下
`steps=1 / tool_trace=0`，属环境降级非回归）、preview 桌面闭环通过（移动像素复检因
窗口最小化受阻，已登记未竟）。**质量轨 `--real` 未执行**——head 真模型端点自 2026-11-16 起连接被拒，
故本报告不宣称质量达标，P8 的 0.4091 等数字仍为最新可用结论；端点恢复后按验证报告
的「质量轨恢复清单」四条执行并把结果回填本 Task Step 2（锚点 2026-W47）。

---

## 依赖与风险

| 风险 | 影响 | 防坑动作 | 落点 |
| --- | --- | --- | --- |
| 放松核验阈值导致假 supported | 指标虚高、用户误信 | 只做「关键事实 + 覆盖率」双条件；口径变更透明登记；黄金集不倒退 | T1 |
| 输出守卫误伤正常答案 | 可用性下降 | 拒绝话术白名单 + 只拦连续长重合 / 元数据 token；三输出面各有放行用例 | T2 |
| 真实模型逐句引注不服从 | 引注纪律提升有限 | prompt v2 + 仅可支撑时补引注；未引注单列不隐藏 | T1/T3 |
| 语料扩充引入与 demo 语料不一致的 chunk_id | 评估失真 | 评估语料副本与 `data/demo` 同名同内容；规模下限断言 | T3 |
| 5 折交叉验证实现错误 | ECE 不可信 | 纯函数单测（切分确定性 / 聚合公式 / 单样本） | T3 |
| 审计脱敏漏掉嵌套键 | 敏感信息落库 | 递归脱敏 + 嵌套用例 | T4 |
| readyz 探活拖慢请求 | 延迟升高 | 只做轻量 `SELECT 1`，加超时；不探外部模型 | T5 |
| 迁移台账与 create_all 双轨冲突 | 结构漂移 | 台账迁移全部幂等；`db init` 后 `db migrate` 为 no-op 有测试 | T6 |
| 接口扩展破坏既有实现 | 全量回归红 | `access` 默认 `None` 向后兼容；两后端同步改 | T7 |
| 压测结果受环境噪声影响 | 基线不可比 | 内存 stores + 桩模型，固定语料与并发梯度；记录机器与 Python 版本 | T8 |
| 真模型端点不可达 | 质量轨无法执行 | 先做其余项，阻塞与可恢复清单写入验证报告 | T11 |

## 暂缓与移交记录

- **Alembic 全量迁移**：⏸ P10 再评估（判据：列改名 / 回滚 / 数据回填类迁移 ≥2 次）；P9 以版本化迁移台账保证可重复。锚点 2026-W49。
- **Agent 会话生命周期**（P8 T8 条件任务）：⏸ 随 Task 10 重评，结论写入验证报告。
- **SSE / ReWOO / PlanExecute / RAG 记忆**：⏸ 随 Task 10 重评，逐项结论与锚点。
- **写行动工具 / NLI / L2 摘要 / ProfileCard 改 PG**：⏸ P10+（见范围外表）。
