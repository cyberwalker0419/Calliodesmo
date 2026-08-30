// useAnalysis / 分析 API 客户端测试（P6 Task 18）。
// 克隆 features/ingest/useIngest.test.tsx 范式：
//   vi.stubGlobal('fetch') + QueryClientProvider + renderHook。
// 覆盖：九类元数据 ANALYSIS_TASK_TYPES 批次契约；提交 202 + job_id；
// 轮询函数式三态（非终态 1200ms 续轮 / 终态返回 false 停 / enabled 门控）；
// 报告列表 / 详情 / 文档清单客户端与导出 URL 构造。
import { describe, expect, it } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import {
  useAnalysisDocuments,
  useAnalysisJob,
  useReport,
  useReports,
  useSubmitAnalysis,
} from "./useAnalysis";
import { exportReportUrl } from "./api";
import { ANALYSIS_TASK_TYPES } from "@/api/types";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function wrap() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    client,
    wrapper: ({ children }: { children: React.ReactNode }) =>
      createElement(QueryClientProvider, { client }, children),
  };
}

describe("ANALYSIS_TASK_TYPES（九类元数据契约）", () => {
  it("九类齐备且全部可选（Task 21-22 接线后「即将上线」批次门控已移除）", () => {
    expect(ANALYSIS_TASK_TYPES).toHaveLength(9);
    expect(ANALYSIS_TASK_TYPES.map((t) => t.value).sort()).toEqual(
      [
        "concepts",
        "custom",
        "entity_recognition",
        "key_information",
        "qa",
        "relation_mapping",
        "summary",
        "tasks",
        "timeline",
      ].sort()
    );
    // 每项 label / icon 齐备（icon 为 lucide-react 既有图标组件，渲染可用性由 preview 闭环验证）
    for (const t of ANALYSIS_TASK_TYPES) {
      expect(t.label.trim().length).toBeGreaterThan(0);
      expect(t.icon).toBeTruthy();
    }
    // value 无重复
    expect(new Set(ANALYSIS_TASK_TYPES.map((t) => t.value)).size).toBe(9);
  });
});

describe("useSubmitAnalysis", () => {
  it("提交分析任务 -> 202 + job_id（POST /analysis/tasks，JSON 体）", async () => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ job_id: "j-1", status: "pending", task_type: "summary" }),
        { status: 202 }
      )
    );
    const { wrapper } = wrap();
    const { result } = renderHook(() => useSubmitAnalysis(), { wrapper });
    result.current.mutate({ task_type: "summary", doc_ids: ["d-1", "d-2"] });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.job_id).toBe("j-1");
    expect(result.current.data?.task_type).toBe("summary");
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/analysis/tasks");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    const body = JSON.parse(init.body);
    expect(body.task_type).toBe("summary");
    expect(body.doc_ids).toEqual(["d-1", "d-2"]);
  });
});

describe("useAnalysisJob（轮询函数式三态）", () => {
  it("非终态 1200ms 续轮 -> 终态停（running -> succeeded 后 refetchInterval=false）", async () => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "j-1",
          status: "running",
          progress: 60,
          progress_stage: "llm",
          task_type: "analyze",
        }),
        { status: 200 }
      )
    );
    mockFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "j-1",
          status: "succeeded",
          progress: 100,
          progress_stage: "done",
          result: { report_id: "r-1", status: "ok" },
          task_type: "analyze",
          report_id: "r-1",
        }),
        { status: 200 }
      )
    );
    const { wrapper } = wrap();
    const { result } = renderHook(() => useAnalysisJob("j-1"), { wrapper });
    // 首查 running -> 1.2s 后轮询 succeeded（waitFor 需覆盖轮询间隔）
    await waitFor(() => expect(result.current.data?.status).toBe("succeeded"), {
      timeout: 5000,
    });
    // Task 11 扩展字段透传：task_type / report_id（analyze 终态成功指向报告行）
    expect(result.current.data?.task_type).toBe("analyze");
    expect(result.current.data?.report_id).toBe("r-1");
    // 终态后停止轮询：等待超过轮询间隔，fetch 调用数不再增长
    const calls = mockFetch.mock.calls.length;
    await new Promise((r) => setTimeout(r, 1500));
    expect(mockFetch.mock.calls.length).toBe(calls);
  });

  it("jobId 为 null 时 enabled 门控不发起查询", async () => {
    mockFetch.mockReset();
    const { wrapper } = wrap();
    const { result } = renderHook(() => useAnalysisJob(null), { wrapper });
    expect(result.current.isLoading).toBe(false);
    expect(mockFetch).not.toHaveBeenCalled();
  });
});

describe("报告列表 / 详情客户端", () => {
  it("useReports -> GET /analysis/reports?limit=&offset=（items + total）", async () => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [
            {
              id: "r-1",
              task_type: "summary",
              status: "ok",
              subject_label: "示例文档摘要",
              access_level: "INTERNAL",
              library_scope: "personal",
              model: "test/stub",
              created_at: "2026-08-30T00:00:00Z",
              source_chunk_count: 3,
            },
          ],
          total: 1,
        }),
        { status: 200 }
      )
    );
    const { wrapper } = wrap();
    const { result } = renderHook(() => useReports(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const [url] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/analysis/reports?limit=20&offset=0");
    expect(result.current.data?.total).toBe(1);
    expect(result.current.data?.items[0]?.subject_label).toBe("示例文档摘要");
    expect(result.current.data?.items[0]?.source_chunk_count).toBe(3);
  });

  it("useReport -> GET /analysis/reports/{id} 返回完整信封", async () => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          task_type: "summary",
          status: "ok",
          generated_at: "2026-08-30T00:00:00Z",
          model: "test/stub",
          prompt_version: "summary.v1",
          usage: { prompt_tokens: 10, completion_tokens: 20 },
          warnings: [],
          source_chunk_ids: ["c-1"],
          payload: { summary: "摘要正文", key_points: ["要点一"] },
        }),
        { status: 200 }
      )
    );
    const { wrapper } = wrap();
    const { result } = renderHook(() => useReport("r-1"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const [url] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/analysis/reports/r-1");
    expect(result.current.data?.task_type).toBe("summary");
    expect(result.current.data?.prompt_version).toBe("summary.v1");
    expect(result.current.data?.payload).toHaveProperty("summary");
  });

  it("useReport(null) enabled 门控不发起查询", () => {
    mockFetch.mockReset();
    const { wrapper } = wrap();
    const { result } = renderHook(() => useReport(null), { wrapper });
    expect(result.current.isLoading).toBe(false);
    expect(mockFetch).not.toHaveBeenCalled();
  });
});

describe("可见文档清单与导出", () => {
  it("useAnalysisDocuments -> GET /analysis/documents（doc_id 聚合项）", async () => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          { doc_id: "d-1", label: "示例文档", access_level: "SECRET", chunk_count: 5 },
        ]),
        { status: 200 }
      )
    );
    const { wrapper } = wrap();
    const { result } = renderHook(() => useAnalysisDocuments(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const [url] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/analysis/documents");
    expect(result.current.data?.[0]?.doc_id).toBe("d-1");
    expect(result.current.data?.[0]?.chunk_count).toBe(5);
  });

  it("exportReportUrl 构造附件下载链接（默认 json，可选 md）", () => {
    expect(exportReportUrl("r-1")).toBe("/api/analysis/reports/r-1/export?format=json");
    expect(exportReportUrl("r-1", "md")).toBe("/api/analysis/reports/r-1/export?format=md");
  });
});
