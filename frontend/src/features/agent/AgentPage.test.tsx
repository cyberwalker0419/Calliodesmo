// AgentPage 测试（P7 T15）：会话列表 + 消息流渲染 + ToolTrace 展开 + 轮询终态停。
// 克隆 ReportsHistory.test.tsx / useAnalysis.test.tsx 范式（mock fetch + renderHook）。
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { AgentPage } from "./AgentPage";
import { useAgentJob } from "./useAgent";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { wrapper: ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children) };
}

const SESSIONS = {
  items: [
    {
      id: "s-1",
      mode: "react",
      label: "会话 1",
      access_level: "INTERNAL",
      library_scope: "personal",
      created_at: "2026-08-31T00:00:00Z",
    },
  ],
  total: 1,
};

const MESSAGES = [
  {
    id: "m-1",
    session_id: "s-1",
    role: "user",
    content: "GPT-4 由谁开发？",
    run_id: null,
    created_at: "2026-08-31T00:00:00Z",
  },
  {
    id: "m-2",
    session_id: "s-1",
    role: "assistant",
    content: "GPT-4 由 OpenAI 开发。",
    run_id: "r-1",
    created_at: "2026-08-31T00:00:01Z",
  },
];

const RUNS = [
  {
    id: "r-1",
    session_id: "s-1",
    status: "succeeded",
    steps: 2,
    usage: { total_tokens: 5 },
    tool_trace: [
      {
        call: { id: "c1", name: "search_knowledge", arguments: { question: "q" } },
        result: { ok: true, output: "OpenAI 开发了 GPT-4。", error: null },
      },
    ],
    error: null,
    created_at: "2026-08-31T00:00:01Z",
  },
];

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockImplementation(async (url: string) => {
    const u = String(url);
    if (u.includes("/messages")) return new Response(JSON.stringify(MESSAGES));
    if (u.includes("/runs")) return new Response(JSON.stringify(RUNS));
    if (u.includes("/agent/sessions")) return new Response(JSON.stringify(SESSIONS));
    return new Response(JSON.stringify({}), { status: 404 });
  });
});

describe("AgentPage", () => {
  it("会话列表渲染 + 切换加载消息流", async () => {
    const { wrapper } = wrap();
    render(createElement(AgentPage), { wrapper });
    await screen.findByText("会话 1");
    await userEvent.click(screen.getByText("会话 1"));
    await screen.findByText("GPT-4 由谁开发？");
    expect(await screen.findByText("GPT-4 由 OpenAI 开发。")).toBeTruthy();
  });

  it("ToolTrace chip 展开输出", async () => {
    const { wrapper } = wrap();
    render(createElement(AgentPage), { wrapper });
    await userEvent.click(await screen.findByText("会话 1"));
    const chip = await screen.findByText("search_knowledge");
    await userEvent.click(chip);
    expect(await screen.findByText(/OpenAI 开发了 GPT-4/)).toBeTruthy();
  });
});

describe("useAgentJob（轮询终态停）", () => {
  it("非终态 1200ms 续轮 -> 终态停", async () => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "j-1", status: "running", task_type: "agent" }))
    );
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "j-1", status: "succeeded", task_type: "agent" }))
    );
    const { wrapper } = wrap();
    const { result } = renderHook(() => useAgentJob("j-1"), { wrapper });
    await waitFor(() => expect(result.current.data?.status).toBe("succeeded"), {
      timeout: 5000,
    });
    // 终态后停轮询：等待超过 1200ms 间隔，fetch 计数不再增长
    const callsAtTerminal = mockFetch.mock.calls.length;
    await new Promise((r) => setTimeout(r, 1600));
    expect(mockFetch.mock.calls.length).toBe(callsAtTerminal);
  });
});
