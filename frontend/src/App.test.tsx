// AppLayout 测试（P7 T1：移动端折叠侧栏）。
// 锁三条行为：① 汉堡按钮存在且点击展开抽屉（抽屉内含导航项）；
// ② 点击抽屉内导航项自动收起；③ 点击遮罩收起抽屉。
// jsdom 无媒体查询——验证行为状态而非 CSS 断点（断点由 Tailwind md: 类承载）。
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement, type ReactNode } from "react";
import type { MeResponse } from "@/api/types";

const mockMeRef = vi.hoisted(() => ({ current: null as MeResponse | null }));
vi.mock("@/features/auth/AuthContext", () => ({
  useAuth: () => ({
    me: mockMeRef.current,
    loading: false,
    login: async () => {},
    logout: async () => {},
  }),
}));

vi.mock("react-router-dom", () => ({
  NavLink: ({ to, children }: { to: string; children: ReactNode }) =>
    createElement("a", { href: to }, children),
  Outlet: () => createElement("div", { "data-testid": "outlet" }),
  useNavigate: () => () => {},
}));

import AppLayout from "./App";

function makeMe(): MeResponse {
  return {
    user_id: "u-1",
    username: "analyst-1",
    clearance: "INTERNAL",
    permissions: ["query", "analyze", "ingest"],
    library_scopes: ["personal"],
    team_ids: [],
    project_ids: [],
  };
}

describe("AppLayout 移动端折叠侧栏", () => {
  beforeEach(() => {
    mockMeRef.current = makeMe();
  });

  it("汉堡按钮点击展开抽屉，导航项可见", async () => {
    render(createElement(AppLayout));
    // 桌面侧栏与抽屉均含「问答面板」，初始抽屉不存在
    expect(screen.queryByRole("dialog", { name: "导航菜单" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "打开导航菜单" }));
    const drawer = screen.getByRole("dialog", { name: "导航菜单" });
    expect(drawer).toBeTruthy();
    // 抽屉内含权限可见的导航项
    expect(drawer.textContent).toContain("问答面板");
    expect(drawer.textContent).toContain("分析");
  });

  it("点击抽屉内导航项后抽屉收起", async () => {
    render(createElement(AppLayout));
    await userEvent.click(screen.getByRole("button", { name: "打开导航菜单" }));
    const drawer = screen.getByRole("dialog", { name: "导航菜单" });
    const link = [...drawer.querySelectorAll("a")].find((a) =>
      a.textContent?.includes("问答面板")
    )!;
    await userEvent.click(link);
    expect(screen.queryByRole("dialog", { name: "导航菜单" })).toBeNull();
  });

  it("点击遮罩收起抽屉", async () => {
    render(createElement(AppLayout));
    await userEvent.click(screen.getByRole("button", { name: "打开导航菜单" }));
    expect(screen.getByRole("dialog", { name: "导航菜单" })).toBeTruthy();
    await userEvent.click(screen.getByTestId("drawer-backdrop"));
    expect(screen.queryByRole("dialog", { name: "导航菜单" })).toBeNull();
  });
});
