// 分析域 TanStack Query hooks（P6 Task 18）。
// 逐行克隆 features/ingest/useIngest.ts 范式：
// - 提交用 useMutation（POST -> 202 + job_id）；
// - 轮询用 useQuery + refetchInterval 函数式（非终态 1200ms、终态返回 false 停、
//   enabled 门控）；
// - 报告历史 / 详情 / 可见文档清单为普通 useQuery（Task 19/20 消费）。
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  getReport,
  listAnalysisDocuments,
  listReports,
  submitAnalysisTask,
} from "./api";
import { api } from "@/api/client";
import type { AnalysisJobRequest, JobOut } from "@/api/types";

/** 提交分析任务 -> 202 + job_id（异步 analyze job；进度经 useAnalysisJob 轮询）。 */
export function useSubmitAnalysis() {
  return useMutation({
    mutationFn: (req: AnalysisJobRequest) => submitAnalysisTask(req),
  });
}

const TERMINAL = new Set(["succeeded", "failed"]);

/** 轮询分析 job 进度；终态（succeeded/failed）自动停轮询。
 *
 * 与 useIngest 的 useJob 同打 GET /jobs/{id}（Job 泛化，Task 11）：
 * analyze job 出参携带 task_type="analyze"，终态成功时 report_id 指向报告行，
 * Task 19/20 据此跳转报告详情。queryKey 以 "analysis-job" 命名空间隔离，
 * 避免与摄入页 useJob 的缓存互相干扰。
 */
export function useAnalysisJob(jobId: string | null) {
  return useQuery({
    queryKey: ["analysis-job", jobId],
    queryFn: () => api.get<JobOut>(`/jobs/${jobId}`),
    enabled: jobId !== null,
    // 非终态每 1.2s 轮询；终态后 refetchInterval 函数返回 false 停止
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL.has(status) ? false : 1200;
    },
  });
}

/** 报告历史：GET /analysis/reports（三维可见性过滤 + 分页；默认 limit=20 offset=0）。 */
export function useReports(params: { limit?: number; offset?: number } = {}) {
  const limit = params.limit ?? 20;
  const offset = params.offset ?? 0;
  return useQuery({
    queryKey: ["analysis-reports", limit, offset],
    queryFn: () => listReports({ limit, offset }),
  });
}

/** 报告详情：GET /analysis/reports/{id}（完整信封；reportId 为 null 时 enabled 门控）。 */
export function useReport(reportId: string | null) {
  return useQuery({
    queryKey: ["analysis-report", reportId],
    queryFn: () => getReport(reportId as string),
    enabled: reportId !== null,
  });
}

/** 可见文档清单：GET /analysis/documents（Task 19 MaterialPicker 数据源）。 */
export function useAnalysisDocuments() {
  return useQuery({
    queryKey: ["analysis-documents"],
    queryFn: () => listAnalysisDocuments(),
  });
}
