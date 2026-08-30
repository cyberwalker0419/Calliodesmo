// ReportsHistory 测试（P6 Task 20）。
// 克隆 AnalysisPage.test.tsx 范式：vi.stubGlobal('fetch') + URL 路由 mock +
// QueryClientProvider + userEvent；useAuth 经 vi.mock 桩注入（权限矩阵）。
// 覆盖：列表行渲染（类型/主题/状态/密级标签 + 总数）；limit/offset 分页翻页；
// 详情 Dialog 懒加载信封；导出按钮权限禁用；无 analyze 权限页面守卫。
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import type { AnalysisEnvelope, MeResponse, ReportListItem } from "@/api/types";

// ---- useAuth 桩：权限矩阵经 mockMeRef.current 注入 ----
const mockMeRef = vi.hoisted(() => ({ current: null as MeResponse | null }));
vi.mock("@/features/auth/AuthContext", () => ({
  useAuth: () => ({
    me: mockMeRef.current,
    loading: false,
    login: async () => {},
    logout: async () => {},
  }),
}));

import { ReportsHistory } from "./ReportsHistory";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function makeMe(permissions: string[]): MeResponse {
  return {
    user_id: "u-1",
    username: "analyst-1",
    clearance: "INTERNAL",
    permissions,
    library_scopes: ["personal"],
    team_ids: [],
    project_ids: [],
  };
}

function makeReport(overrides: Partial<ReportListItem>): ReportListItem {
  return {
    id: "r-1",
    task_type: "summary",
    status: "ok",
    subject_label: "全可见范围 · 摘要",
    access_level: "INTERNAL",
    library_scope: "personal",
    model: "test/stub",
    created_at: "2026-08-30T09:00:00Z",
    source_chunk_count: 2,
    ...overrides,
  };
}

const PAGE1: ReportListItem[] = [
  makeReport({ id: "r-1" }),
  makeReport({
    id: "r-2",
    task_type: "timeline",
    status: "partial",
    subject_label: "示例文档 · 时间线",
    access_level: "CONFIDENTIAL",
    source_chunk_count: 5,
  }),
];
const PAGE2: ReportListItem[] = [makeReport({ id: "r-11", task_type: "qa", subject_label: "示例问题 · 问答" })];

const ENVELOPE: AnalysisEnvelope = {
  task_type: "summary",
  status: "ok",
  generated_at: "2026-08-30T09:00:00Z",
  model: "test/stub",
  prompt_version: "summary.v1",
  usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
  warnings: [],
  source_chunk_ids: ["doc-a#0"],
  payload: {
    summary: "历史详情摘要正文。",
    key_points: ["要点甲"],
    confidence: 0.9,
    evidence: [{ chunk_id: "doc-a#0", quote: "详情引文", confidence: 1.0 }],
  },
};

/** 后端 stub：列表（按 limit/offset 路由）+ 详情两端点。 */
function mockBackend() {
  mockFetch.mockReset();
  mockFetch.mockImplementation(async (url: string) => {
    if (url === "/api/analysis/reports/r-1") {
      return new Response(JSON.stringify(ENVELOPE), { status: 200 });
    }
    if (url.startsWith("/api/analysis/reports?")) {
      const qs = new URLSearchParams(url.split("?")[1]);
      const offset = Number(qs.get("offset") ?? 0);
      const items = offset >= 10 ? PAGE2 : PAGE1;
      return new Response(JSON.stringify({ items, total: 12 }), { status: 200 });
    }
    return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
  });
}

function wrap(children: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return createElement(QueryClientProvider, { client }, children);
}

async function renderPage() {
  render(wrap(<ReportsHistory />));
  await screen.findByText("全可见范围 · 摘要");
}

beforeEach(() => {
  mockMeRef.current = makeMe(["analyze", "export"]);
  mockBackend();
});

describe("列表渲染", () => {
  it("行渲染：类型标签 / 主题 / 状态 / 密级 + 总条数", async () => {
    await renderPage();
    expect(screen.getByText("摘要")).toBeInTheDocument();
    expect(screen.getByText("时间线")).toBeInTheDocument();
    expect(screen.getByText("示例文档 · 时间线")).toBeInTheDocument();
    expect(screen.getByText("INTERNAL")).toBeInTheDocument();
    expect(screen.getByText("CONFIDENTIAL")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.getByText("partial")).toBeInTheDocument();
    expect(screen.getByText(/共 12 条/)).toBeInTheDocument();
  });

  it("空列表给出空态提示", async () => {
    mockFetch.mockReset();
    mockFetch.mockImplementation(async () =>
      new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 })
    );
    render(wrap(<ReportsHistory />));
    expect(await screen.findByText(/暂无可见报告/)).toBeInTheDocument();
  });
});

describe("分页（limit/offset）", () => {
  it("下一页以 offset=10 请求；上一页返回第一页", async () => {
    const user = userEvent.setup();
    await renderPage();
    expect(screen.getByRole("button", { name: /上一页/ })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /下一页/ }));
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/analysis/reports?limit=10&offset=10",
        expect.anything()
      );
    });
    expect(await screen.findByText("示例问题 · 问答")).toBeInTheDocument();
    // 第二页（共 12 条 / 每页 10 条）：下一页禁用，上一页可用
    expect(screen.getByRole("button", { name: /下一页/ })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /上一页/ }));
    expect(await screen.findByText("全可见范围 · 摘要")).toBeInTheDocument();
  });
});

describe("详情 Dialog（懒加载信封）", () => {
  it("点「详情」拉取信封并渲染分节内容", async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getAllByRole("button", { name: /详情/ })[0]);
    // 懒加载：打开后才请求 /analysis/reports/r-1
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/analysis/reports/r-1",
        expect.anything()
      );
    });
    expect(await screen.findByText(/历史详情摘要正文/)).toBeInTheDocument();
  });

  it("有 export 权限：详情内导出为下载链接", async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getAllByRole("button", { name: /详情/ })[0]);
    const link = await screen.findByRole("link", { name: /导出 JSON/ });
    expect(link).toHaveAttribute(
      "href",
      "/api/analysis/reports/r-1/export?format=json"
    );
  });

  it("无 export 权限：详情内导出按钮禁用", async () => {
    mockMeRef.current = makeMe(["analyze"]); // 种子三角色均含 export，此为自定义角色口径
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getAllByRole("button", { name: /详情/ })[0]);
    await screen.findByText(/历史详情摘要正文/);
    expect(screen.getByRole("button", { name: /导出 JSON/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /导出 MD/ })).toBeDisabled();
  });
});

describe("页面守卫", () => {
  it("无 analyze 权限：提示无权限（导航隐藏之外的双保险）", async () => {
    mockMeRef.current = makeMe(["query"]);
    render(wrap(<ReportsHistory />));
    expect(await screen.findByText(/无 analyze 权限/)).toBeInTheDocument();
  });
});
