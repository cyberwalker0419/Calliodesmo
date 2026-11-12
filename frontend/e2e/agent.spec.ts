// e2e agent（P7 T16）：建会话 -> 提问 -> 助手回答可见（多轮 + 工具轨迹面）。
import { test, expect } from "@playwright/test";
import { ADMIN, login, waitForBackend } from "./helpers";

test.beforeAll(async () => {
  await waitForBackend();
});

test("Agent 两回合：建会话 -> 提问 -> 回答 -> 续问", async ({ page }) => {
  test.setTimeout(900_000); // 两回合真模型（慢模型/工具调用余量）
  await login(page, ADMIN);
  await page.goto("/app/agent");
  // 桌面侧栏「新建会话」/ 移动选择条「新建」双形态
  const desktopNew = page.getByRole("button", { name: "新建会话" });
  if (await desktopNew.isVisible().catch(() => false)) {
    await desktopNew.click();
  } else {
    await page.getByRole("button", { name: "新建" }).click();
  }
  await page.waitForTimeout(800);
  const sel = page.locator("select");
  if (await sel.isVisible().catch(() => false)) {
    await sel.selectOption({ index: 1 });
  } else {
    await page.locator("aside button").nth(1).click();
  }

  const ask = async (q: string) => {
    await page.locator("textarea").fill(q);
    await page.getByRole("button", { name: "提问" }).click();
  };

  // P8 口径：真模型慢时允许预算收敛的 partial；只验回合落定 + 工具轨迹 + 接地度面板。
  await ask("APT28 擅长什么攻击手段？");
  await expect(
    page.getByText(/预算超限|search_knowledge/).first()
  ).toBeVisible({ timeout: 540_000 });
  await expect(page.getByText("接地度验证").first()).toBeVisible({ timeout: 60_000 });

  await ask("再确认一次？");
  await expect
    .poll(async () => await page.getByText("接地度验证").count(), {
      timeout: 540_000,
      intervals: [3000],
    })
    .toBeGreaterThan(1);
});
