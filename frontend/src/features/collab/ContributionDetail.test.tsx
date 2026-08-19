import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { ContributionDetail } from "./ContributionDetail";
import type { DiffOut } from "@/api/types";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

const DIFF: DiffOut = {
  new_entities: 8,
  new_relations: 7,
  chunks: 1,
  communities: 1,
  conflicts: 8,
  entity_names: ["OpenAI Labs", "GPT series"],
  relation_summaries: [["OpenAI Labs", "GPT series", "developed"]],
  chunk_ids: ["c#0"],
  community_ids: ["doc-1"],
  alignment_pending: [
    {
      pair_id: "lab-vs-openai",
      source_name: "OpenAI Labs",
      target_name: "OpenAI",
      score: 0.9,
      type: "Organization",
      source_type: "Organization",
      target_type: "Organization",
      source_description: "AI research lab",
      target_description: "AI research lab",
      status: "pending",
    },
  ],
};

function wrap(children: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return createElement(QueryClientProvider, { client }, children);
}

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockResolvedValueOnce(
    new Response(JSON.stringify(DIFF), { status: 200 })
  );
});

async function renderDetail(
  props?: Partial<React.ComponentProps<typeof ContributionDetail>>
) {
  render(
    wrap(
      <ContributionDetail
        contributionId="c-1"
        title="Push labs"
        open
        onOpenChange={() => {}}
        canApprove
        {...props}
      />
    )
  );
  await screen.findByRole("tab", { name: /对齐复核/ });
}

/** 用 userEvent 真实点击切到「对齐复核」Tab（jsdom 下 Radix Tabs 需以用户事件激活）。 */
async function openAlignmentPanel() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("tab", { name: /对齐复核/ }));
  const score = await screen.findByText("90%");
  const holder = score.closest("[role=tabpanel]");
  if (!holder) throw new Error("对齐复核面板未渲染");
  return within(holder as HTMLElement);
}

describe("ContributionDetail 对齐复核 Tab", () => {
  it("渲染计数卡（含待审对齐）与待审对列表（源/目标/类型/相似度/按钮）", async () => {
    await renderDetail();
    // 计数卡标签都在
    expect(screen.getByText("待审对齐")).toBeTruthy();
    expect(screen.getByText("同名冲突")).toBeTruthy();
    // 对齐复核 Tab 存在
    expect(screen.getByRole("tab", { name: /对齐复核/ })).toBeTruthy();

    const panel = await openAlignmentPanel();
    // 待审对内容
    expect(panel.getByText("OpenAI Labs")).toBeTruthy();
    expect(panel.getByText("90%")).toBeTruthy();
    expect(panel.getAllByText(/Organization/).length).toBeGreaterThan(0);
    expect(panel.getByText(/源 · Organization/)).toBeTruthy();
    expect(panel.getAllByText(/AI research lab/).length).toBe(2);
    expect(panel.getByRole("button", { name: /批准合并/ })).toBeTruthy();
    expect(panel.getByRole("button", { name: /驳回/ })).toBeTruthy();
  });

  it("批准按钮调用 alignment-review/approve 端点（带 pair_id）", async () => {
    await renderDetail();
    const panel = await openAlignmentPanel();
    mockFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ pair_id: "lab-vs-openai", status: "approved" }),
        { status: 200 }
      )
    );
    const user = userEvent.setup();
    await user.click(panel.getByRole("button", { name: /批准合并/ }));
    await waitFor(() => {
      const calls = mockFetch.mock.calls.filter(([url]) =>
        String(url).includes("/alignment-review/approve")
      );
      expect(calls.length).toBe(1);
      const init = calls[0][1] as RequestInit;
      expect(JSON.parse(String(init.body))).toEqual({ pair_id: "lab-vs-openai" });
    });
  });

  it("canApprove=false 时不渲染操作按钮（只读展示仍显示数据）", async () => {
    await renderDetail({ canApprove: false });
    const panel = await openAlignmentPanel();
    expect(panel.queryByRole("button", { name: /批准合并/ })).toBeNull();
    expect(panel.queryByRole("button", { name: /驳回/ })).toBeNull();
    expect(panel.getByText("OpenAI Labs")).toBeTruthy();
  });
});
