// P8 T7：接地度面板测试（判定徽标 / needs_review / 声明展开 / 证据引文 / 空侧车）。
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { VerificationSidecar } from "@/api/types";
import { VerificationPanel } from "./VerificationPanel";

const SIDECAR: VerificationSidecar = {
  version: 1,
  source: "analysis",
  claims: [
    {
      text: "镨钕氧化物报价小幅上行",
      kind: "claim",
      cited: true,
      chunk_id: "doc#0",
      verdict: "supported",
      confidence: 0.95,
      calibrated_confidence: 0.9,
      reason: "引注直接支撑声明",
      evidence: [
        {
          chunk_id: "doc#0",
          quote: "镨钕氧化物报价小幅上行",
          start: 0,
          end: 12,
          match_type: "quote",
        },
      ],
    },
    {
      text: "该组织在 2018 至 2020 年间活跃",
      kind: "claim",
      cited: true,
      chunk_id: "doc#1",
      verdict: "contradicted",
      confidence: 0.9,
      calibrated_confidence: 0.9,
      reason: "年份区间不一致",
      evidence: [],
    },
    {
      text: "这是一句没有引注的补充说明",
      kind: "claim",
      cited: false,
      chunk_id: null,
      verdict: "uncited",
      confidence: 0,
      calibrated_confidence: 0,
      reason: "无引注：未做支持性判定",
      evidence: [],
    },
  ],
  totals: {
    claims: 3,
    checkable: 2,
    supported: 1,
    unsupported: 0,
    uncertain: 0,
    contradicted: 1,
    uncited: 1,
    citations: 2,
    citations_supported: 1,
  },
  metrics: {
    citation_precision: 0.5,
    claim_grounding: 0.5,
    unsupported_rate: 0,
    contradiction_rate: 0.5,
    uncited_claim_rate: 0.33,
    calibrated_confidence: 0.9,
  },
  needs_review: true,
};

describe("VerificationPanel", () => {
  it("空侧车不渲染（旧报告兼容）", () => {
    const { container } = render(<VerificationPanel verification={null} />);
    expect(container.textContent).toBe("");
  });

  it("汇总指标与 needs_review 徽标", () => {
    render(<VerificationPanel verification={SIDECAR} />);
    expect(screen.getByText("接地度验证")).toBeInTheDocument();
    expect(screen.getByText("需复核")).toBeInTheDocument();
    expect(screen.getByText("接地 0.50")).toBeInTheDocument();
    expect(screen.getByText("矛盾 1")).toBeInTheDocument();
    expect(screen.getByText("未引注 1")).toBeInTheDocument();
  });

  it("默认收起声明；点击后展示三态判定与未引注", async () => {
    const user = userEvent.setup();
    render(<VerificationPanel verification={SIDECAR} />);
    expect(screen.queryByText("镨钕氧化物报价小幅上行")).toBeNull();
    await user.click(screen.getByText(/声明级判定（3）/));
    expect(screen.getByText("镨钕氧化物报价小幅上行")).toBeInTheDocument();
    expect(screen.getByText("有据")).toBeInTheDocument();
    expect(screen.getByText("矛盾")).toBeInTheDocument();
    expect(screen.getByText("未引注")).toBeInTheDocument();
    expect(screen.getByText("无引注：未做支持性判定")).toBeInTheDocument();
  });

  it("展开证据显示引文与匹配类型", async () => {
    const user = userEvent.setup();
    render(<VerificationPanel verification={SIDECAR} defaultOpen />);
    await user.click(screen.getByRole("button", { name: "展开证据" }));
    expect(screen.getByText(/引注直接支撑声明/)).toBeInTheDocument();
    expect(screen.getByText(/直接引注/)).toBeInTheDocument();
    expect(screen.getAllByText(/镨钕氧化物报价小幅上行/).length).toBeGreaterThan(1);
  });
});
