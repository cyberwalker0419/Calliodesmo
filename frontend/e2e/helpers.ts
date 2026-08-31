// e2e 公共件（P7 T16）：后端等待 / 登录 / 账号装配。
// 启动顺序见 README.md：先 `uv run calliodesmo serve --seed-demo --port 8200`。
import { Page, expect, request } from "@playwright/test";

export const ADMIN = { username: "admin", password: "admin-123456" };
export const BACKEND = "http://127.0.0.1:8200";

/** 首条 spec 等 /healthz（后端未启时登录类 spec 全红的防坑，见 README）。 */
export async function waitForBackend(timeoutMs = 60_000) {
  const t0 = Date.now();
  for (;;) {
    try {
      const r = await fetch(`${BACKEND}/healthz`);
      if (r.ok) return;
    } catch {
      /* 未起 */
    }
    if (Date.now() - t0 > timeoutMs) {
      throw new Error(
        "后端 8200 未就绪：先执行 uv run calliodesmo serve --seed-demo --port 8200"
      );
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
}

export async function login(page: Page, creds: { username: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel("用户名").fill(creds.username);
  await page.getByLabel("密码").fill(creds.password);
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL(/\/app\//, { timeout: 30_000 });
}

async function adminToken(ctx: Awaited<ReturnType<typeof request.newContext>>) {
  const r = await ctx.post("/api/auth/token", {
    data: `username=${ADMIN.username}&password=${ADMIN.password}`,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return (await r.json()).access_token as string;
}

/** 经 admin API 建 analyst 角色用户，回凭据（越权探针用；用户名每次唯一）。 */
export async function createAnalyst(suffix: string) {
  const ctx = await request.newContext({ baseURL: "http://localhost:5173" });
  const token = await adminToken(ctx);
  const auth = { Authorization: `Bearer ${token}` };
  const username = `e2e-analyst-${suffix}`;
  const password = `pw-${suffix}-A1!`;
  const created = await ctx.post("/api/admin/users", {
    headers: auth,
    data: { username, password, clearance: "internal" },
  });
  if (created.status() === 201) {
    const uid = (await created.json()).user_id;
    await ctx.post(`/api/admin/users/${uid}/roles`, {
      headers: auth,
      data: { role: "analyst", scope: "personal" },
    });
  }
  await ctx.dispose();
  return { username, password };
}

export { expect };
