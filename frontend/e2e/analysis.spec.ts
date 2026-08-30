// e2e analysis（P7 T16）：提交 summary -> 轮询 -> 报告历史可见。
import { test, expect } from "@playwright/test";
import { ADMIN, login, waitForBackend } from "./helpers";

test.beforeAll(async () => {
  await waitForBackend();
});

test("提交分析 -> 报告历史出现行", async ({ page }) => {
  test.setTimeout(300_000); // 真模型分析回合
  await login(page, ADMIN);
  await page.goto("/app/analysis");
  await page.getByRole("button", { name: "提交分析" }).click();
  await page.goto("/app/analysis/reports");
  // 轮询等待新报告行（摘要类）出现
  await expect
    .poll(
      async () => {
        await page.reload();
        return await page.getByText(/摘要/).count();
      },
      { timeout: 240_000, intervals: [5000] }
    )
    .toBeGreaterThan(0);
});
