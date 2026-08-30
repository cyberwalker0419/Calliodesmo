// AnalysisPage 测试（P6 Task 19）。
// 克隆 useIngest.test.tsx / ContributionDetail.test.tsx 范式：
//   vi.stubGlobal('fetch') + URL 路由 mock + QueryClientProvider + userEvent。
// useAuth 经 vi.mock 桩注入（页面经 useAccess -> useAuth 取权限）。
// 覆盖：九类选择器（第一批可选 / 第二批灰显「即将上线」）；MaterialPicker 消费
// GET /analysis/documents 出参；提交 mutation 参数组装（summary + doc_ids /
// qa + question）；qa 空问题前端校验拦截；进度与阶段文案 -> 终态成功提示；
// failed job 错误盒 + 重试；提交错误（400）错误盒；无 analyze 权限提交禁用。
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { MemoryRouter } from "react-router-dom";
import type { MeResponse } from "@/api/types";

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

import { AnalysisPage } from "./AnalysisPage";

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

const DOCS = [
  { doc_id: "d-1", label: "示例文档A", access_level: "INTERNAL", chunk_count: 3 },
  { doc_id: "d-2", label: "示例文档B", access_level: "CONFIDENTIAL", chunk_count: 5 },
];

/** 后端 stub：documents / tasks / jobs / 报告详情四端点；jobs 先 running 后 succeeded。 */
function mockBackend(opts: { jobsFailed?: boolean; submitStatus?: number } = {}) {
  mockFetch.mockReset();
  let jobPolls = 0;
  mockFetch.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === "/api/analysis/documents") {
      return new Response(JSON.stringify(DOCS), { status: 200 });
    }
    if (url === "/api/analysis/reports/r-1") {
      // Task 20：成功态「查看报告」经 ReportDialog 懒加载信封
      return new Response(
        JSON.stringify({
          task_type: "summary",
          status: "ok",
          generated_at: "2026-08-30T10:00:00Z",
          model: "test/stub",
          prompt_version: "summary.v1",
          usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
          warnings: [],
          source_chunk_ids: ["d-1#0"],
          payload: {
            summary: "报告 r-1 的摘要正文。",
            key_points: ["要点一"],
            confidence: 0.9,
          },
        }),
        { status: 200 }
      );
    }
    if (url === "/api/analysis/tasks" && init?.method === "POST") {
      if (opts.submitStatus && opts.submitStatus >= 400) {
        return new Response(JSON.stringify({ detail: "doc_ids 含不可见文档，请核对选择范围" }), {
          status: opts.submitStatus,
        });
      }
      return new Response(
        JSON.stringify({ job_id: "j-1", status: "pending", task_type: "summary" }),
        { status: 202 }
      );
    }
    if (url.startsWith("/api/jobs/")) {
      jobPolls += 1;
      if (opts.jobsFailed) {
        return new Response(
          JSON.stringify({
            id: "j-1",
            filename: "",
            status: "failed",
            progress: 60,
            progress_stage: "llm",
            result: null,
            error: "材料为空：可见范围内无可分析文本块",
            task_type: "analyze",
          }),
          { status: 200 }
        );
      }
      if (jobPolls === 1) {
        return new Response(
          JSON.stringify({
            id: "j-1",
            filename: "",
            status: "running",
            progress: 25,
            progress_stage: "prompt",
            task_type: "analyze",
          }),
          { status: 200 }
        );
      }
      return new Response(
        JSON.stringify({
          id: "j-1",
          filename: "",
          status: "succeeded",
          progress: 100,
          progress_stage: "done",
          result: { report_id: "r-1", status: "ok" },
          task_type: "analyze",
          report_id: "r-1",
        }),
        { status: 200 }
      );
    }
    return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
  });
}

function wrap(children: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  // Task 20 起 AnalysisPage 经 useNavigate 提供报告历史跳转，需 Router 上下文
  return createElement(
    MemoryRouter,
    null,
    createElement(QueryClientProvider, { client }, children)
  );
}

async function renderPage() {
  render(wrap(<AnalysisPage />));
  // 等 MaterialPicker 消费 documents 出参渲染完成
  await screen.findByLabelText(/示例文档A/);
}

beforeEach(() => {
  mockMeRef.current = makeMe(["query", "analyze"]);
  mockBackend();
});

describe("TaskTypePicker（九类选择器）", () => {
  it("第一批 5 类可选；第二批 4 类灰显「即将上线」且不可点", async () => {
    await renderPage();
    // 第一批：可选（非 disabled）
    for (const label of ["摘要", "关键信息", "时间线", "实体识别", "问答"]) {
      expect(screen.getByRole("button", { name: new RegExp(label) })).toBeEnabled();
    }
    // 第二批：禁用 + 「即将上线」角标 ×4
    for (const label of ["关系映射", "任务", "概念", "自定义"]) {
      expect(screen.getByRole("button", { name: new RegExp(label) })).toBeDisabled();
    }
    expect(screen.getAllByText("即将上线")).toHaveLength(4);
  });

  it("选中类型高亮切换（点「时间线」后高亮迁移）", async () => {
    const user = userEvent.setup();
    await renderPage();
    const timeline = screen.getByRole("button", { name: /时间线/ });
    await user.click(timeline);
    // 高亮态由 data-active 标记（克隆 AskPanel cn() 高亮范式，测试以 aria-pressed 断言）
    expect(timeline).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /摘要/ })).toHaveAttribute(
      "aria-pressed",
      "false"
    );
  });
});

describe("MaterialPicker（材料选择）", () => {
  it("消费 GET /analysis/documents 出参：label / access_level / chunk_count 齐现", async () => {
    await renderPage();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/analysis/documents",
      expect.objectContaining({ method: "GET" })
    );
    expect(screen.getByLabelText(/示例文档A/)).toBeInTheDocument();
    expect(screen.getByLabelText(/示例文档B/)).toBeInTheDocument();
    expect(screen.getByText("INTERNAL")).toBeInTheDocument();
    expect(screen.getByText("CONFIDENTIAL")).toBeInTheDocument();
    expect(screen.getByText("3 块")).toBeInTheDocument();
    expect(screen.getByText("5 块")).toBeInTheDocument();
  });

  it("空清单给出空态提示", async () => {
    mockFetch.mockReset();
    mockFetch.mockImplementation(async (url: string) => {
      if (url === "/api/analysis/documents") {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    });
    render(wrap(<AnalysisPage />));
    expect(await screen.findByText(/暂无可见文档/)).toBeInTheDocument();
  });
});

describe("提交参数组装", () => {
  it("summary + 多选 doc_ids -> POST /analysis/tasks 请求体齐备", async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByLabelText(/示例文档A/));
    await user.click(screen.getByLabelText(/示例文档B/));
    await user.click(screen.getByRole("button", { name: /提交分析/ }));
    await waitFor(() => {
      const call = mockFetch.mock.calls.find(
        ([u, init]) => u === "/api/analysis/tasks" && init?.method === "POST"
      );
      expect(call).toBeTruthy();
    });
    const call = mockFetch.mock.calls.find(([u]) => u === "/api/analysis/tasks");
    const body = JSON.parse(call?.[1]?.body);
    expect(body.task_type).toBe("summary");
    expect([...body.doc_ids].sort()).toEqual(["d-1", "d-2"]);
  });

  it("qa 类：question 进请求体 + 全可见库范围文案", async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByRole("button", { name: /问答/ }));
    expect(
      await screen.findByText(/问答范围为全可见库（文档范围限定待 P9）/)
    ).toBeInTheDocument();
    await user.type(
      screen.getByPlaceholderText(/输入要分析的问题/),
      "示例文档的核心结论是什么？"
    );
    await user.click(screen.getByRole("button", { name: /提交分析/ }));
    await waitFor(() => {
      const call = mockFetch.mock.calls.find(
        ([u, init]) => u === "/api/analysis/tasks" && init?.method === "POST"
      );
      expect(call).toBeTruthy();
    });
    const call = mockFetch.mock.calls.find(([u]) => u === "/api/analysis/tasks");
    const body = JSON.parse(call?.[1]?.body);
    expect(body.task_type).toBe("qa");
    expect(body.question).toBe("示例文档的核心结论是什么？");
    // 未选文档 -> 不携带 doc_ids（全可见范围）
    expect(body.doc_ids ?? []).toEqual([]);
  });

  it("qa 空问题提交 -> 前端校验拦截（不发 POST）", async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByRole("button", { name: /问答/ }));
    await user.click(screen.getByRole("button", { name: /提交分析/ }));
    expect(await screen.findByText(/问答分析需要填写问题/)).toBeInTheDocument();
    expect(
      mockFetch.mock.calls.find(([u]) => u === "/api/analysis/tasks")
    ).toBeUndefined();
  });
});

describe("进度轮询与终态", () => {
  it("提交 -> 进度条 + 阶段文案 -> 成功提示（含报告入口）-> 查看报告懒加载信封", async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByLabelText(/示例文档A/));
    await user.click(screen.getByRole("button", { name: /提交分析/ }));
    // 首查 running：阶段文案「构造提示」（STAGE_LABEL prompt）出现
    expect(await screen.findByText(/构造提示/, {}, { timeout: 4000 })).toBeInTheDocument();
    // 轮询至 succeeded：成功提示 + 报告入口（Task 20：查看报告 / 报告历史按钮）
    expect(await screen.findByText("分析完成", {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText(/r-1/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /查看报告/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /报告历史/ })).toBeEnabled();
    // 点「查看报告」：ReportDialog 懒加载信封并渲染摘要正文
    await user.click(screen.getByRole("button", { name: /查看报告/ }));
    expect(
      await screen.findByText(/报告 r-1 的摘要正文/, {}, { timeout: 4000 })
    ).toBeInTheDocument();
  });

  it("job failed -> destructive 错误盒 + 重试面板", async () => {
    mockBackend({ jobsFailed: true });
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByRole("button", { name: /提交分析/ }));
    expect(await screen.findByText("分析失败", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(
      screen.getByText(/材料为空：可见范围内无可分析文本块/)
    ).toBeInTheDocument();
    // 重试：清状态回到可再提交（进度 / 错误盒消失）
    await user.click(screen.getByRole("button", { name: /重试/ }));
    await waitFor(() => expect(screen.queryByText("分析失败")).toBeNull());
  });

  it("提交即 400 -> 错误盒展示后端 detail", async () => {
    mockBackend({ submitStatus: 400 });
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByLabelText(/示例文档A/));
    await user.click(screen.getByRole("button", { name: /提交分析/ }));
    expect(
      await screen.findByText(/doc_ids 含不可见文档，请核对选择范围/, {}, { timeout: 4000 })
    ).toBeInTheDocument();
  });
});

describe("权限门控", () => {
  it("无 analyze 权限：提交禁用 + 提示（导航隐藏之外的页面内双保险）", async () => {
    mockMeRef.current = makeMe(["query"]);
    render(wrap(<AnalysisPage />));
    // 等 documents 查询落定，避免 act 警告
    await screen.findByLabelText(/示例文档A/);
    const submit = screen.getByRole("button", { name: /提交分析/ });
    expect(submit).toBeDisabled();
    expect(screen.getByText(/无 analyze 权限/)).toBeInTheDocument();
  });
});
