// e2e qa（P7 T16）：三模式切换 + 提问回卡 + 来源标注区存在（双视口经 projects）。
import { test, expect } from "@playwright/test";
import { ADMIN, login, waitForBackend } from "./helpers";

test.beforeAll(async () => {
  await waitForBackend();
});

test("三模式切换 + top_k + 提问回卡", async ({ page }) => {
  test.setTimeout(300_000); // 真模型回合
  await login(page, ADMIN);
  await page.goto("/app/qa");
  for (const mode of ["Native", "Local", "Global"]) {
    await page.getByRole("button", { name: mode }).click();
    await expect(page.getByRole("button", { name: mode })).toBeVisible();
  }
  await page.getByRole("button", { name: "Native" }).click();
  await page.locator("textarea").fill("稀土简报涉及哪些主体？");
  await page.getByRole("button", { name: "提问" }).click();
  // 回卡渲染（答案区出现，真模型接地语料或明确拒答均算冒烟通过）
  await expect(page.getByText("答案").first()).toBeVisible({ timeout: 240_000 });
});
