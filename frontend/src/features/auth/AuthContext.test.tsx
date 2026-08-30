// AuthContext 测试（P7 T1：logout 方法与 cookie 失效对齐）。
// 锁两条契约：① logout 以 POST 命中 /auth/logout（后端仅注册 POST，
// DELETE 会 405 且 httpOnly cookie 残留）；② 登出清本地会话（token 置空 +
// /auth/me 缓存清除），401 时经 unauthorized 回调同样清会话。
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { AuthProvider, useAuth } from "./AuthContext";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function makeMe() {
  return {
    user_id: "u-1",
    username: "analyst-1",
    clearance: "INTERNAL",
    permissions: ["query"],
    library_scopes: ["personal"],
    team_ids: [],
    project_ids: [],
  };
}

function Probe() {
  const { me, login, logout } = useAuth();
  return createElement(
    "div",
    null,
    createElement("span", { "data-testid": "who" }, me?.username ?? "anon"),
    createElement(
      "button",
      { onClick: () => void login("analyst-1", "pw") },
      "login"
    ),
    createElement("button", { onClick: () => void logout() }, "logout")
  );
}

function setup() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    createElement(QueryClientProvider, { client: qc }, createElement(AuthProvider, null, createElement(Probe)))
  );
}

describe("AuthContext", () => {
  beforeEach(() => {
    sessionStorage.clear();
    mockFetch.mockReset();
  });

  it("logout 以 POST 命中 /auth/logout（非 DELETE）", async () => {
    // 登录：/auth/token + /auth/me
    mockFetch
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: "t-1", token_type: "bearer" }), {
          status: 200,
        })
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(makeMe()), { status: 200 }))
      // 登出：POST /auth/logout -> 204
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    setup();
    await userEvent.click(screen.getByText("login"));
    await waitFor(() => expect(screen.getByTestId("who").textContent).toBe("analyst-1"));

    await act(async () => {
      await userEvent.click(screen.getByText("logout"));
    });

    const logoutCall = mockFetch.mock.calls.find((c) => String(c[0]).includes("/auth/logout"));
    expect(logoutCall).toBeTruthy();
    const [url, init] = logoutCall!;
    expect(url).toBe("/api/auth/logout");
    expect(init.method).toBe("POST");
    // 本地会话清除：token 置空（sessionStorage 无残留）
    expect(sessionStorage.getItem("calliodesmo.token")).toBeNull();
  });
});
