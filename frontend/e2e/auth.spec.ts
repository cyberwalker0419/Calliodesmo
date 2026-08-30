// e2e auth（P7 T16）：错误凭据提示 / 正确登录跳转。
import { test, expect } from "@playwright/test";
import { ADMIN, login, waitForBackend } from "./helpers";

test.beforeAll(async () => {
  await waitForBackend();
});

test("错误凭据提示用户名或密码错误", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("用户名").fill(ADMIN.username);
  await page.getByLabel("密码").fill("wrong-password");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByText("用户名或密码错误")).toBeVisible();
  expect(page.url()).toContain("/login");
});

test("正确凭据登录跳 /app/qa", async ({ page }) => {
  await login(page, ADMIN);
  expect(page.url()).toContain("/app/qa");
  // 桌面见导航项；移动见汉堡按钮（抽屉收纳）
  const navLink = page.getByRole("link", { name: "问答面板" });
  const burger = page.getByRole("button", { name: "打开导航菜单" });
  expect((await navLink.isVisible().catch(() => false)) || (await burger.isVisible().catch(() => false))).toBe(true);
});
