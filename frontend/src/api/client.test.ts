import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, getToken, setToken, setUnauthorizedHandler } from "./client";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

beforeEach(() => {
  setToken(null);
  sessionStorage.clear();
  mockFetch.mockReset();
});

afterEach(() => {
  setUnauthorizedHandler(null);
});

describe("api client", () => {
  it("注入 Bearer 头并解析 JSON", async () => {
    setToken("jwt-xyz");
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    );
    const data = await api.get<{ ok: boolean }>("/healthz");
    expect(data.ok).toBe(true);
    const [, init] = mockFetch.mock.calls[0];
    expect(init.headers.Authorization).toBe("Bearer jwt-xyz");
    expect(init.credentials).toBe("include");
  });

  it("204 返回 undefined", async () => {
    mockFetch.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const data = await api.del("/auth/logout");
    expect(data).toBeUndefined();
  });

  it("401 清 token 并触发 unauthorized 回调", async () => {
    setToken("jwt-xyz");
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch.mockResolvedValueOnce(new Response(null, { status: 401 }));
    await expect(api.get("/whatever")).rejects.toThrow();
    expect(getToken()).toBeNull();
    expect(handler).toHaveBeenCalled();
  });

  it("非 2xx 抛 ApiError 含 detail", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "缺少权限" }), { status: 403 })
    );
    await expect(api.get("/admin/users")).rejects.toMatchObject({
      status: 403,
      detail: "缺少权限",
    });
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "缺少权限" }), { status: 403 })
    );
    try {
      await api.get("/admin/users");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
    }
  });

  it("form 提交不注入 JSON 头", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ access_token: "t" }), { status: 200 })
    );
    const data = await api.form<{ access_token: string }>(
      "/auth/token",
      new URLSearchParams({ username: "u", password: "p" })
    );
    expect(data.access_token).toBe("t");
    const init = mockFetch.mock.calls[0][1];
    expect(init.method).toBe("POST");
    expect(init.headers?.["Content-Type"]).toBeUndefined();
  });
});
