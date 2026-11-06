// P8 T7：QA 答案卡片核验摘要 + 自动路由回显测试。
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { QueryResponse, VerificationSidecar } from "@/api/types";
import { AnswerCard } from "./AnswerCard";

const VERIFICATION: VerificationSidecar = {
  version: 1,
  source: "qa",
  claims: [],
  totals: {
    claims: 1,
    checkable: 1,
    supported: 1,
    unsupported: 0,
    uncertain: 0,
    contradicted: 0,
    uncited: 0,
    citations: 1,
    citations_supported: 1,
  },
  metrics: {
    citation_precision: 1,
    claim_grounding: 1,
    unsupported_rate: 0,
    contradiction_rate: 0,
    uncited_claim_rate: 0,
    calibrated_confidence: 0.9,
  },
  needs_review: false,
};

const RESULT: QueryResponse = {
  answer: "镨钕氧化物用于制造钕铁硼永磁材料 [doc#0]。",
  mode: "local",
  source_chunk_ids: ["doc#0"],
  context_chunks: [{ chunk_id: "doc#0", content: "镨钕氧化物用于制造钕铁硼永磁材料。" }],
  model: "test/model",
  verification: VERIFICATION,
  routed_mode: "agent",
  routing: {
    requested_mode: "auto",
    routed_mode: "agent",
    executed_mode: "local",
    confidence: 0.7,
    reasons: ["动作指令：帮我", "Agent 模式需专用端点，已回退 local"],
    fallback: true,
  },
};

describe("AnswerCard", () => {
  it("渲染接地度摘要与自动路由回显", () => {
    render(<AnswerCard result={RESULT} />);
    expect(screen.getByText("接地度验证")).toBeInTheDocument();
    expect(screen.getByText("自动路由 → agent（回退）")).toBeInTheDocument();
    expect(screen.getByText("有据 1")).toBeInTheDocument();
  });

  it("无 verification / routing 时向后兼容", () => {
    const legacy: QueryResponse = {
      answer: "旧响应",
      mode: "native_rag",
      source_chunk_ids: [],
      context_chunks: [],
      model: "",
    };
    render(<AnswerCard result={legacy} />);
    expect(screen.getByText("旧响应")).toBeInTheDocument();
    expect(screen.queryByText("接地度验证")).toBeNull();
    expect(screen.queryByText(/自动路由/)).toBeNull();
  });
});
