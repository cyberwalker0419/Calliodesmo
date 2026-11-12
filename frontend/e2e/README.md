# frontend/e2e —— Playwright 冒烟链路（P7 T16，重锚 W47→W44）

六组 spec：auth（错/对凭据）· qa（三模式 + 提问回卡）· analysis（提交→轮询→报告）·
admin（analyst 越权 403 探测）· agent（会话两回合）· logout（cookie 失效断言）。
双视口经 `playwright.config.ts` projects（desktop / mobile）。

## 启动顺序（硬性，防「后端未启 spec 全红」虚假不稳定）

```bash
# 1) 后端（演示数据；慢模型建议收紧 Agent 预算，让回合在 e2e 窗口内收敛）
CALLIODESMO_AGENT_MAX_STEPS=1 CALLIODESMO_AGENT_WALL_CLOCK_SECONDS=90   uv run calliodesmo serve --seed-demo --port 8200
# 2) e2e：frontend/（串行，避免真模型并发争抢 GPU）
npm run e2e
```

`helpers.waitForBackend` 在 beforeAll 等 `127.0.0.1:8200/healthz`，未启即报错指路。
`playwright.config.ts` webServer 复用已跑的 5173 dev server（`reuseExistingServer`）。

## 边界

- **不进 CI**：需真 PG+Neo4j+真模型，与 CI `-m "not db"` 纪律冲突；留痕锚点
  2026-W49 随审计硬化重评（P7 计划范围外表）。
- 真模型回合耗时长：`workers: 1` 串行；qa 240s、analysis 600s、agent 900s。
- analysis spec 先轮询 `/api/analysis/reports` 总数，确认新报告落库后单次导航；不再
  `page.reload()` 循环（会打断 /auth/me 启动，停在 RequireAuth 骨架屏）。
- agent spec 只验结构（回合落定 + 工具轨迹/预算收敛 + 接地度面板），不依赖具体答案
  文本——慢模型触发预算收敛的 partial 也视为通过；答案质量由 `--real` 质量轨负责。
- 浏览器经 `npx playwright install chromium` 安装（本地一次性）。
