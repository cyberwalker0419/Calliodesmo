// ReportViewer 测试（P6 Task 20）。
// 克隆 ContributionDetail.test.tsx / AnalysisPage.test.tsx 范式：
// vi.stubGlobal('fetch') + QueryClientProvider + userEvent。
// 覆盖（计划 Step 1 口径）：
// - 第一批 5 类分节渲染存在性（摘要 / 关键信息 / 时间线 / 实体识别 / 问答）；
// - 证据 chips 点击展开 / 收起 quote；
// - partial 状态横幅 + warnings 展示；
// - 信封元信息（model / prompt_version / usage / generated_at）；
// - 导出按钮：无 export 权限禁用 / 有权限渲染下载链接（href + download）。
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import type { AnalysisEnvelope } from "@/api/types";
import { ReportViewer } from "./ReportViewer";

function wrap(children: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return createElement(QueryClientProvider, { client }, children);
}

function renderViewer(envelope: AnalysisEnvelope, props: { canExport?: boolean } = {}) {
  return render(
    wrap(<ReportViewer envelope={envelope} reportId="r-1" canExport={props.canExport ?? false} />)
  );
}

const SUMMARY_ENVELOPE: AnalysisEnvelope = {
  task_type: "summary",
  status: "ok",
  generated_at: "2026-08-30T10:00:00Z",
  model: "test/stub",
  prompt_version: "summary.v1",
  usage: { prompt_tokens: 120, completion_tokens: 45, total_tokens: 165 },
  warnings: [],
  source_chunk_ids: ["doc-a#0", "doc-a#1"],
  payload: {
    summary: "离线桩占位摘要：验证渲染链路。",
    key_points: ["要点一", "要点二"],
    confidence: 0.9,
    evidence: [{ chunk_id: "doc-a#0", quote: "原文引文一", confidence: 1.0 }],
  },
};

const KEY_INFO_ENVELOPE: AnalysisEnvelope = {
  ...SUMMARY_ENVELOPE,
  task_type: "key_information",
  prompt_version: "key_information.v1",
  payload: {
    items: [
      { label: "时间", value: "2026年8月29日", confidence: 0.9 },
      { label: "当事方", value: "示例组织", confidence: 0.8, evidence: [] },
    ],
  },
};

const TIMELINE_ENVELOPE: AnalysisEnvelope = {
  ...SUMMARY_ENVELOPE,
  task_type: "timeline",
  prompt_version: "timeline.v1",
  payload: {
    items: [
      {
        date_raw: "2026年8月29日",
        date_normalized: "2026-08-29",
        granularity: "exact",
        description: "事件一",
        confidence: 0.95,
        evidence: [{ chunk_id: "doc-b#1", quote: "时间线引文", confidence: 1.0 }],
      },
      {
        date_raw: "会后不久",
        date_normalized: null,
        granularity: "relative",
        description: "事件二",
        confidence: 0.3,
      },
    ],
  },
};

const ENTITY_ENVELOPE: AnalysisEnvelope = {
  ...SUMMARY_ENVELOPE,
  task_type: "entity_recognition",
  prompt_version: "entity_recognition.v1",
  payload: {
    items: [
      {
        name: "示例组织",
        type: "organization",
        description: "占位实体描述",
        confidence: 0.7,
      },
    ],
  },
};

const QA_ENVELOPE: AnalysisEnvelope = {
  ...SUMMARY_ENVELOPE,
  task_type: "qa",
  prompt_version: "qa.v1",
  payload: {
    question: "核心结论是什么？",
    answer: "核心结论为 X。",
    citations: ["doc-a#0"],
    confidence: 0.8,
  },
};

const PARTIAL_ENVELOPE: AnalysisEnvelope = {
  ...SUMMARY_ENVELOPE,
  status: "partial",
  warnings: ["证据失配占比超阈值，降级为 partial"],
};

describe("各节渲染存在性（第一批 5 类）", () => {
  it("summary：摘要正文 / 要点分节 / 置信标记 / 信封元信息", async () => {
    const user = userEvent.setup();
    renderViewer(SUMMARY_ENVELOPE);
    // 摘要正文（默认分节）
    expect(screen.getByText(/离线桩占位摘要：验证渲染链路/)).toBeInTheDocument();
    // 置信标记（两位小数）
    expect(screen.getByText(/置信 0\.90/)).toBeInTheDocument();
    // 切到「要点」分节
    await user.click(screen.getByRole("tab", { name: /要点/ }));
    expect(screen.getByText("要点一")).toBeInTheDocument();
    expect(screen.getByText("要点二")).toBeInTheDocument();
    // 信封元信息：model / prompt_version / usage / generated_at
    expect(screen.getByText("test/stub")).toBeInTheDocument();
    expect(screen.getByText("summary.v1")).toBeInTheDocument();
    expect(screen.getByText("prompt_tokens")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText(/2026-08-30/)).toBeInTheDocument();
    // 材料分节存在
    expect(screen.getByRole("tab", { name: /材料/ })).toBeInTheDocument();
  });

  it("key_information：label/value 条目逐条渲染", () => {
    renderViewer(KEY_INFO_ENVELOPE);
    expect(screen.getByText("时间")).toBeInTheDocument();
    expect(screen.getByText("2026年8月29日")).toBeInTheDocument();
    expect(screen.getByText("当事方")).toBeInTheDocument();
    expect(screen.getByText("示例组织")).toBeInTheDocument();
    expect(screen.getByText(/置信 0\.90/)).toBeInTheDocument();
  });

  it("timeline：有序列表 + granularity 标注 + 归一化日期 + 原始表述", () => {
    renderViewer(TIMELINE_ENVELOPE);
    const list = screen.getByRole("list");
    expect(list.tagName).toBe("OL");
    // granularity 标注（中文化）
    expect(screen.getByText("精确")).toBeInTheDocument();
    expect(screen.getByText("相对")).toBeInTheDocument();
    // 原始表述与归一化日期
    expect(screen.getByText("2026年8月29日")).toBeInTheDocument();
    expect(screen.getByText("2026-08-29")).toBeInTheDocument();
    expect(screen.getByText("会后不久")).toBeInTheDocument();
    // relative 无归一化日期：事件二不臆造
    expect(screen.getByText("事件一")).toBeInTheDocument();
    expect(screen.getByText("事件二")).toBeInTheDocument();
  });

  it("entity_recognition：实体名 / 类型 / 描述", () => {
    renderViewer(ENTITY_ENVELOPE);
    expect(screen.getByText("示例组织")).toBeInTheDocument();
    expect(screen.getByText("organization")).toBeInTheDocument();
    expect(screen.getByText("占位实体描述")).toBeInTheDocument();
  });

  it("qa：问题 / 答案 / 来源引注", () => {
    renderViewer(QA_ENVELOPE);
    expect(screen.getByText(/核心结论是什么？/)).toBeInTheDocument();
    expect(screen.getByText(/核心结论为 X。/)).toBeInTheDocument();
    // 来源引注（引注为材料块 id，无 quote 可展开）
    expect(screen.getByText("doc-a#0")).toBeInTheDocument();
  });
});

describe("证据 chips 展开 quote", () => {
  it("点击证据 chip 展开引文，再点收起", async () => {
    const user = userEvent.setup();
    renderViewer(SUMMARY_ENVELOPE);
    const chip = screen.getByRole("button", { name: /doc-a#0/ });
    // 初始不展示引文
    expect(screen.queryByText(/原文引文一/)).toBeNull();
    await user.click(chip);
    expect(screen.getByText(/原文引文一/)).toBeInTheDocument();
    await user.click(chip);
    expect(screen.queryByText(/原文引文一/)).toBeNull();
  });
});

describe("partial 状态横幅与 warnings", () => {
  it("partial 信封：横幅与告警展示", () => {
    renderViewer(PARTIAL_ENVELOPE);
    expect(screen.getByText(/部分状态报告/)).toBeInTheDocument();
    expect(
      screen.getByText(/证据失配占比超阈值，降级为 partial/)
    ).toBeInTheDocument();
  });

  it("ok 信封：无 partial 横幅", () => {
    renderViewer(SUMMARY_ENVELOPE);
    expect(screen.queryByText(/部分状态报告/)).toBeNull();
  });
});

describe("导出按钮（消费 export 端点）", () => {
  it("无 export 权限：导出按钮禁用", () => {
    renderViewer(SUMMARY_ENVELOPE, { canExport: false });
    expect(screen.getByRole("button", { name: /导出 JSON/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /导出 MD/ })).toBeDisabled();
  });

  it("有 export 权限：渲染附件下载链接（href 指向 export 端点 + download）", () => {
    renderViewer(SUMMARY_ENVELOPE, { canExport: true });
    const json = screen.getByRole("link", { name: /导出 JSON/ });
    expect(json).toHaveAttribute(
      "href",
      "/api/analysis/reports/r-1/export?format=json"
    );
    expect(json).toHaveAttribute("download");
    const md = screen.getByRole("link", { name: /导出 MD/ });
    expect(md).toHaveAttribute("href", "/api/analysis/reports/r-1/export?format=md");
  });
});
