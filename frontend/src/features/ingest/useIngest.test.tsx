import { describe, expect, it } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { useIngest, useJob } from "./useIngest";

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

describe("useIngest", () => {
  it("multipart 上传 -> 202 + job_id", async () => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ job_id: "j-1", status: "pending", filename: "a.md" }), {
        status: 202,
      })
    );
    const { wrapper } = wrap();
    const { result } = renderHook(() => useIngest(), { wrapper });
    result.current.mutate({ file: new File(["# x"], "a.md", { type: "text/markdown" }) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.job_id).toBe("j-1");
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/ingest");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    // FormData 直传（浏览器带 multipart boundary），不带 JSON Content-Type
    expect(init.headers["Content-Type"]).toBeUndefined();
  });
});

describe("useJob", () => {
  it("轮询至终态停（running -> succeeded 后 refetchInterval=false）", async () => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ id: "j-1", status: "running", progress: 30, progress_stage: "extract" }),
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
          result: { documents: 1, chunks: 2, entities: 3, relations: 1, communities: 1, profile_cards: 2 },
        }),
        { status: 200 }
      )
    );
    const { wrapper } = wrap();
    const { result } = renderHook(() => useJob("j-1"), { wrapper });
    // 首查 running -> 1.2s 后轮询 succeeded（waitFor 需覆盖轮询间隔）
    await waitFor(() => expect(result.current.data?.status).toBe("succeeded"), {
      timeout: 5000,
    });
    expect(result.current.data?.result?.chunks).toBe(2);
    // 终态后停止轮询：等待超过轮询间隔，fetch 调用数不再增长
    const calls = mockFetch.mock.calls.length;
    await new Promise((r) => setTimeout(r, 1500));
    expect(mockFetch.mock.calls.length).toBe(calls);
  });

  it("jobId 为 null 时不发起查询", async () => {
    mockFetch.mockReset();
    const { wrapper } = wrap();
    const { result } = renderHook(() => useJob(null), { wrapper });
    expect(result.current.isLoading).toBe(false);
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
