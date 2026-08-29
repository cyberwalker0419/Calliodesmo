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

> 全程模型选型（嵌入 / 重排 / 抽取 / 摘要 / 合成 / 分析 / Agent）。核心原则：**可切换**（抽象接口）+ **离线可测**（默认桩）+ **由数据判定**（评估 harness 回归）。关联 [[docs/plans/roadmap|年计划]] / [[docs/plans/phases/P1-ecl-pipeline|P1 计划]] / [[docs/deploy/native|原生部署]]。

## 一、选型原则

1. **可切换不绑死**：LLM 走 `LLMProvider`（LiteLLM）、嵌入 `EmbeddingProvider`、重排 `Reranker`，配置驱动随时换。
2. **离线可测**：dev/test 默认 `HashEmbeddingProvider` + `sys.modules` 桩 litellm + 内存 store，CI 零网络；真实模型属真机验证。
3. **分层配置**：抽取质量优先、摘要可降档、合成面向用户；接口允许同进程多实例。
4. **中英双语**：BGE-M3 双语嵌入；抽取 LLM 选中文强的。
5. **结构化输出**：抽取需稳定 JSON（JSON mode 强于自由生成）。
6. **由数据判定**：模型变更经评估 harness 回归。

## 二、嵌入（情景层向量）

| 项 | 推荐 | 说明 |
| --- | --- | --- |
| 默认 | **BGE-M3**（1024 维，中英双语） | 三输出全用：dense + sparse + multi-vec |
| 本地 | FlagEmbedding（extra `embedding-local`） | `uv sync --extra embedding-local` |
| 测试默认 | `HashEmbeddingProvider` | 确定性、离线、无语义 |
| 维度 | `CALLIODESMO_EMBEDDING_DIMENSION=1024` | 与 pgvector 列对齐；换模型须同步 |

> BGE-M3 真实嵌入需 `--extra embedding-local`（torch）；真嵌入属真机验证。

## 三、重排（P2/P5，交叉编码器）

- 默认 **bge-reranker-v2-m3**（与 BGE-M3 同源，中英 cross-encoder）；`Reranker` ABC（P2 引入）默认桩离线可测。
- 作用：召回后精排，**第一精度杠杆**。

## 四、抽取 / 摘要 LLM

**需求**：稳定 JSON、指令遵循、中英、长上下文。

| 档 | 云（LiteLLM 串） | 本地（Ollama） |
| --- | --- | --- |
| 质量优先 | `openai/gpt-4o`、`anthropic/claude-3-5-sonnet`、`qwen/qwen-max` | `ollama/qwen2.5:72b` |
| 均衡（默认） | `openai/gpt-4o-mini`、`deepseek/deepseek-chat`、`qwen/qwen-plus` | `ollama/qwen2.5:32b` |

**建议**：抽取用质量优先（GIGO 源头）；摘要可降一档省成本。P1 全程 `sys.modules` 桩离线。配置：`CALLIODESMO_LLM_MODEL/_API_KEY/_API_BASE`。

## 五、合成 / 分析 / Agent LLM

- **P2 合成**：`gpt-4o-mini` 起步够用；**P5 自纠错**（CRAG/SelfCheck）升 `gpt-4o`/Claude/Qwen-Max（需更强推理）。
- **P6 九类分析**：结构化报告，质量优先。
- **P7 Agent**：需 function-calling + 长程规划（`gpt-4o`/Claude/Qwen-Max）；权限内行动。

## 六、配置一览

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `CALLIODESMO_LLM_MODEL` | `openai/gpt-4o-mini` | LiteLLM 模型串 |
| `CALLIODESMO_LLM_API_KEY` / `_API_BASE` | - | key / 自定义 endpoint |
| `CALLIODESMO_EMBEDDING_PROVIDER` | `bge-m3` | 嵌入后端 |
| `CALLIODESMO_EMBEDDING_MODEL` / `_DIMENSION` | `BAAI/bge-m3` / `1024` | 嵌入模型 / 维度 |
| `CALLIODESMO_RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | 重排模型（P2+） |

## 七、推荐组合（决策矩阵）

| 场景 | 离线/test | dev | prod（质量） | prod（成本） |
| --- | --- | --- | --- | --- |
| 抽取 | 桩 | gpt-4o-mini | gpt-4o / Qwen-Max / Claude | gpt-4o-mini / DeepSeek-V3 |
| 社区/文档摘要 | 桩 | gpt-4o-mini | gpt-4o-mini / Qwen-Plus | gpt-4o-mini / DeepSeek |
| 嵌入 | Hash | BGE-M3 | BGE-M3 | BGE-M3 |
| 重排 | 桩 | bge-reranker-v2-m3 | 同 | 同 |
| 合成 / Agent | 桩 | gpt-4o-mini | gpt-4o / Claude / Qwen-Max | gpt-4o-mini |

## 八、边界与后续

- 真实模型需 API key / 显存；模型升级经**评估 harness 回归**判定，不靠主观。
- 本地规模化（P9）：vLLM / Ollama 批量 + 缓存 + 量化（awq/gptq）降显存。
- 模型迭代快：**接口可换 + 评估护航**比押注单一模型更重要。
