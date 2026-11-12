// e2e analysis（P7 T16；P8 稳定性修正）：提交 summary -> 轮询 API 等新报告 -> 页面单次加载。
// 修正点：原实现每 5s `page.reload()`，会在 SPA 仍处于 /auth/me loading 时打断启动，
// 永远停在骨架屏（2026-11-11 失败现场：截图仅剩 RequireAuth Skeleton，后端仅 1 次
// /analysis/reports 200）。改为先轮询接口，确认新报告落库后再单次导航，避免 reload 循环。
import { test, expect } from "@playwright/test";
import { ADMIN, login, waitForBackend } from "./helpers";

test.beforeAll(async () => {
  await waitForBackend();
});

async function reportTotal(page: Parameters<typeof login>[0]): Promise<number> {
  return page.evaluate(async () => {
    const r = await fetch("/api/analysis/reports?limit=1&offset=0", {
      credentials: "include",
    });
    if (!r.ok) return -1;
    return (await r.json()).total as number;
  });
}

test("提交分析 -> 报告历史出现行", async ({ page }) => {
  test.setTimeout(600_000); // 真模型分析回合（串行 e2e，留足慢模型余量）
  await login(page, ADMIN);
  await page.goto("/app/analysis");
  const before = await reportTotal(page);
  await page.getByRole("button", { name: "提交分析" }).click();

  // 轮询后端接口（不重载页面）：报告总数超过提交前即视为新报告落库。
  await expect
    .poll(async () => reportTotal(page), { timeout: 480_000, intervals: [5000] })
    .toBeGreaterThan(before);

  // 落库后单次加载列表页；此时 SPA 启动不会被后续 reload 打断。
  await page.goto("/app/analysis/reports");
  await expect(page.getByText(/摘要|summary/).first()).toBeVisible({ timeout: 60_000 });
});
