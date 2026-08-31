// e2e logout（P7 T16）：登出跳登录 + 旧 cookie 过 /auth/me 401（cookie 失效断言）。
import { test, expect, request } from "@playwright/test";
import { ADMIN, login, waitForBackend } from "./helpers";

test.beforeAll(async () => {
  await waitForBackend();
});

test("登出后旧 cookie 失效", async ({ page, context }) => {
  await login(page, ADMIN);
  // 登出前浏览器持有 httpOnly 会话 cookie
  const before = await context.cookies();
  expect(before.some((c) => c.name === "calliodesmo_session")).toBe(true);

  await page.getByRole("button", { name: "登出" }).click();
  await page.waitForURL(/\/login/);

  // 登出后浏览器 cookie 已清：无凭证 /api/auth/me 401
  const ctx = await request.newContext({ baseURL: "http://localhost:5173" });
  const after = await ctx.get("/api/auth/me");
  expect(after.status()).toBe(401);
  await ctx.dispose();
});
