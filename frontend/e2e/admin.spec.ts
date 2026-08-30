// e2e admin（P7 T16）：analyst 越权探测——导航无管理项 + 直击 URL 不得见用户表 + API 403。
import { test, expect, request } from "@playwright/test";
import { createAnalyst, login, waitForBackend } from "./helpers";

test.beforeAll(async () => {
  await waitForBackend();
});

test("analyst 越权探测：导航隐藏 + API 403", async ({ page }) => {
  const creds = await createAnalyst(String(Date.now() % 100000));
  await login(page, creds);

  // 导航不含管理项（隐藏式门控）
  await expect(page.getByRole("link", { name: "用户管理" })).toHaveCount(0);

  // 直击 URL：页面不渲染用户表（无 manage_users 权限）
  await page.goto("/app/admin/users");
  await expect(page.getByRole("table")).toHaveCount(0);

  // API 层 403
  const ctx = await request.newContext({ baseURL: "http://localhost:5173" });
  const r = await ctx.post("/api/auth/token", {
    data: `username=${creds.username}&password=${creds.password}`,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  const token = (await r.json()).access_token;
  const guarded = await ctx.get("/api/admin/users", {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(guarded.status()).toBe(403);
  await ctx.dispose();
});
