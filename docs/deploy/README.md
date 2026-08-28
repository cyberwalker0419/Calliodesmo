# 部署指南

生产部署二选一；测试/开发环境独立在 [testing.md](testing.md)。

## 生产方式

| 方式 | 适合 | 文档 |
| --- | --- | --- |
| **Docker 全栈** | 想省心、一键含基础设施 | [docker.md](docker.md) |
| **本地原生**（uv，无 Docker） | 已有 / 想自管 PostgreSQL+pgvector 与 Neo4j | [native.md](native.md) |

## 测试 / 开发环境

桩模型冒烟（`test/stub` + `hash` + `none`）、pytest 测试套件、前端联调 —— 见 [testing.md](testing.md)。

## 模型配置（三层）

LLM / 嵌入 / 重排三层**独立可切**（本地或远端 HTTP），只改 `.env` 不动代码。配置示例见 `.env.example`，各路径细节见对应指南。
