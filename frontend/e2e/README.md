# frontend/e2e —— Playwright 冒烟链路（P7 T16，重锚 W47→W44）

六组 spec：auth（错/对凭据）· qa（三模式 + 提问回卡）· analysis（提交→轮询→报告）·
admin（analyst 越权 403 探测）· agent（会话两回合）· logout（cookie 失效断言）。
双视口经 `playwright.config.ts` projects（desktop / mobile）。

## 启动顺序（硬性，防「后端未启 spec 全红」虚假不稳定）

```bash
# 1) 语料入库（首次，供 qa / analysis 接地；生产 schema）
uv run calliodesmo ingest data/demo
# 2) 后端（演示数据）：仓库根
uv run calliodesmo serve --seed-demo --port 8200
# 3) e2e：frontend/
npm run e2e
```

`helpers.waitForBackend` 在 beforeAll 等 `127.0.0.1:8200/healthz`，未启即报错指路。
`playwright.config.ts` webServer 复用已跑的 5173 dev server（`reuseExistingServer`）。

## 边界

- **不进 CI**：需真 PG+Neo4j+真模型，与 CI `-m "not db"` 纪律冲突；留痕锚点
  2026-W49 随审计硬化重评（P7 计划范围外表）。
- 真模型回合耗时长：相关 spec `test.setTimeout` 放宽（qa 180s / analysis·agent 300s）。
- 浏览器经 `npx playwright install chromium` 安装（本地一次性）。
