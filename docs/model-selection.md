---
title: 模型选型建议
type: reference
created: 2026-07-26
tags:
  - reference
  - models
related:
  - "[[docs/plans/roadmap]]"
  - "[[docs/plans/phases/P1-ecl-pipeline]]"
  - "[[docs/deploy/native]]"
---
# 模型选型建议

> [!info] 范围
> 全程模型选型建议（嵌入 / 重排 / 抽取 / 摘要 / 合成 / 分析 / Agent）。核心原则：**可切换**（全走抽象接口）+ **离线可测**（默认桩 / 确定性实现）+ **由数据判定**（评估 harness 回归）。关联 [[docs/plans/roadmap|年计划]] / [[docs/plans/phases/P1-ecl-pipeline|P1 计划]] / [[docs/deploy/native|原生部署]]。

## 一、选型原则

1. **可切换、不绑死**：LLM 经 `LLMProvider`（LiteLLM 统一），嵌入经 `EmbeddingProvider`，重排经 `Reranker`（P2 引入）；均配置驱动，后端随时换。
2. **离线可测**：dev/test 默认 `HashEmbeddingProvider` + `sys.modules` 桩 litellm + 内存 store，**CI 零网络、确定性**；真实模型属真机验证边界（同 BGE-M3 的 extra 策略）。
3. **分层配置**：按场景/阶段配不同模型（抽取质量优先、摘要可降档、合成面向用户）；接口允许同进程多实例。
4. **中英双语**：嵌入与抽取 LLM 需中英兼顾（BGE-M3 双语；LLM 选中文强的）。
5. **结构化输出**：抽取需稳定 JSON（指令遵循 + JSON mode 强于自由生成）。
6. **由数据判定**：任何模型/参数变更经评估 harness 回归（[[docs/plans/roadmap|精度与评估原则]]），不靠主观。

## 二、嵌入（情景层向量）

| 项 | 推荐 | 说明 |
| --- | --- | --- |
| 默认 | **BGE-M3**（`BAAI/bge-m3`，1024 维，中英双语） | 三输出**全用**：dense（语义）+ sparse（近 BM25，词级）+ multi-vec（近 ColBERT，细粒度）；不止 dense |
| 本地 | FlagEmbedding（extra `embedding-local`，重依赖 torch） | `uv sync --extra embedding-local` |
| 测试默认 | `HashEmbeddingProvider` | 确定性、无语义、离线；不替代真模型 |
| 维度 | `CALLIODESMO_EMBEDDING_DIMENSION=1024` | 与 pgvector 列对齐；换模型须同步 |
| 替代 | bge-large-zh-v1.5 / OpenAI text-embedding-3-large | 接口可换；换后须重嵌入全量 |

> [!warning] BGE-M3 真实嵌入需 `--extra embedding-local`（torch）；P1 验证报告以 Hash 默认 + 桩为主，真嵌入真机验证。

## 三、重排（P2/P5，交叉编码器）

| 项 | 推荐 |
| --- | --- |
| 默认 | **bge-reranker-v2-m3**（与 BGE-M3 同源，中英，cross-encoder） |
| 接口 | `Reranker` ABC（P2 引入），默认内存/桩实现离线可测 |
| 作用 | 召回后精排：cross-encoder 比 bi-encoder 嵌入准，**第一精度杠杆** |

## 四、抽取 / 摘要 LLM（Extract Task2 / 社区摘要 Task3 / 文档社区 Task5）

**需求**：稳定 JSON 输出、指令遵循、中英、长上下文（多 chunk 拼）。

| 档 | 云（LiteLLM 串） | 本地（Ollama） |
| --- | --- | --- |
| 质量优先 | `openai/gpt-4o`、`anthropic/claude-3-5-sonnet`、`qwen/qwen-max` | `ollama/qwen2.5:72b`、`ollama/deepseek-v3` |
| 均衡（默认） | `openai/gpt-4o-mini`、`deepseek/deepseek-chat`、`qwen/qwen-plus` | `ollama/qwen2.5:32b` |
| 成本 | `gpt-4o-mini` / DeepSeek | 本地（仅显存成本） |

**建议**：
- **抽取用质量优先**--实体/关系准度直接决定图与社区质量（GIGO 源头）。
- **摘要可降一档**（社区/文档摘要对单实体误差容忍度高，省成本）。
- P1 全程 `sys.modules` 桩，离线零请求。

**配置**：`CALLIODESMO_LLM_MODEL` / `CALLIODESMO_LLM_API_KEY` / `CALLIODESMO_LLM_API_BASE`。

## 五、合成 LLM（Synthesis，P2）

**需求**：接地生成、引用来源、无证据拒答、推理。

- P2 基础合成：`gpt-4o-mini` 起步够用。
- P5 自纠错（CRAG / SelfCheck / Adaptive）：升级 `gpt-4o` / Claude / Qwen-Max（需更强推理与自我批判）。
- 与抽取同档或更高（直接面向用户答案质量）。

## 六、分析 / Agent LLM（P6/P7）

- **P6 九类分析**（摘要/关键信息/时间线/实体识别/关系映射/任务列表/概念解释/问答/自定义）：结构化报告，质量优先。
- **P7 Agent**：需 function-calling + 长程规划（`gpt-4o` / Claude / Qwen-Max 强）；权限内行动。

## 七、配置一览

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `CALLIODESMO_LLM_MODEL` | `openai/gpt-4o-mini` | LiteLLM 模型串（provider/model） |
| `CALLIODESMO_LLM_API_KEY` | - | API key（本地 Ollama 可空） |
| `CALLIODESMO_LLM_API_BASE` | - | 自定义 endpoint（Ollama / 私有网关） |
| `CALLIODESMO_EMBEDDING_PROVIDER` | `bge-m3` | 嵌入后端 |
| `CALLIODESMO_EMBEDDING_MODEL` | `BAAI/bge-m3` | 嵌入模型 |
| `CALLIODESMO_EMBEDDING_DIMENSION` | `1024` | 向量维度 |
| `CALLIODESMO_RERANKER_MODEL`（P2） | `BAAI/bge-reranker-v2-m3` | 重排模型 |

## 八、推荐组合（决策矩阵）

| 场景 | 离线/test | dev | prod（质量） | prod（成本） |
| --- | --- | --- | --- | --- |
| 抽取 | 桩 | gpt-4o-mini | gpt-4o / Qwen-Max / Claude | gpt-4o-mini / DeepSeek-V3 |
| 社区/文档摘要 | 桩 | gpt-4o-mini | gpt-4o-mini / Qwen-Plus | gpt-4o-mini / DeepSeek |
| 嵌入 | Hash | BGE-M3 | BGE-M3 | BGE-M3 |
| 重排 | 桩 | bge-reranker-v2-m3 | 同 | 同 |
| 合成（P2） | 桩 | gpt-4o-mini | gpt-4o / Claude | gpt-4o-mini |
| Agent（P7） | 桩 | gpt-4o-mini | gpt-4o / Claude / Qwen-Max | - |

## 九、边界与后续

- 真实模型需 API key / 显存；P1 离线全桩，验证报告如实声明。
- 模型升级经 **评估 harness 回归**判定（精度由数据判定，不靠主观）。
- 本地部署（P9 规模化）：vLLM / Ollama 批量 + 缓存 + 量化（awq/gptq）降显存。
- 模型迭代快：**接口可换 + 评估护航**比押注单一模型更重要。