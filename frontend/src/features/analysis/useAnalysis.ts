// 分析域 TanStack Query hooks（P6 Task 18）。
// 逐行克隆 features/ingest/useIngest.ts 范式：
// - 提交用 useMutation（POST -> 202 + job_id）；
// - 轮询用 useQuery + refetchInterval 函数式（非终态 1200ms、终态返回 false 停、
//   enabled 门控）；
// - 报告历史 / 详情 / 可见文档清单为普通 useQuery（Task 19/20 消费）。
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteReport,
  getReport,
  getReportVerification,
  listAnalysisDocuments,
  listReportVersions,
  listReports,
  restoreReport,
  reviewReport,
  rollbackReport,
  submitAnalysisTask,
} from "./api";
import { api } from "@/api/client";
import type { AnalysisJobRequest, JobOut, ReviewAction } from "@/api/types";

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

/** 报告历史：GET /analysis/reports（三维可见性过滤 + 分页；默认 limit=20 offset=0）。
 *
 * ``enabled`` 门控（Task 20）：无 analyze 权限的页面守卫场景不发起查询。
 */
export function useReports(
  params: {
    limit?: number;
    offset?: number;
    enabled?: boolean;
    includeDeleted?: boolean;
  } = {}
) {
  const limit = params.limit ?? 20;
  const offset = params.offset ?? 0;
  const includeDeleted = params.includeDeleted ?? false;
  return useQuery({
    queryKey: ["analysis-reports", limit, offset, includeDeleted],
    queryFn: () => listReports({ limit, offset, includeDeleted }),
    enabled: params.enabled ?? true,
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

/** 报告接地度侧车：GET /analysis/reports/{id}/verification（可空，历史报告兼容）。 */
export function useReportVerification(reportId: string | null, enabled = true) {
  return useQuery({
    queryKey: ["analysis-report-verification", reportId],
    queryFn: () => getReportVerification(reportId as string),
    enabled: enabled && reportId !== null,
  });
}

/** 报告版本链：GET /analysis/reports/{id}/versions。 */
export function useReportVersions(reportId: string | null, enabled = true) {
  return useQuery({
    queryKey: ["analysis-report-versions", reportId],
    queryFn: () => listReportVersions(reportId as string),
    enabled: enabled && reportId !== null,
  });
}

/** 生命周期 mutations：成功后失效报告列表 / 详情 / 版本链。 */
function useInvalidateReport() {
  const queryClient = useQueryClient();
  return (reportId: string) => {
    void queryClient.invalidateQueries({ queryKey: ["analysis-reports"] });
    void queryClient.invalidateQueries({ queryKey: ["analysis-report", reportId] });
    void queryClient.invalidateQueries({
      queryKey: ["analysis-report-versions", reportId],
    });
    void queryClient.invalidateQueries({
      queryKey: ["analysis-report-verification", reportId],
    });
  };
}

export function useDeleteReport() {
  const invalidate = useInvalidateReport();
  return useMutation({
    mutationFn: (reportId: string) => deleteReport(reportId),
    onSuccess: (_data, reportId) => invalidate(reportId),
  });
}

export function useRestoreReport() {
  const invalidate = useInvalidateReport();
  return useMutation({
    mutationFn: (reportId: string) => restoreReport(reportId),
    onSuccess: (_data, reportId) => invalidate(reportId),
  });
}

export function useRollbackReport() {
  const invalidate = useInvalidateReport();
  return useMutation({
    mutationFn: (vars: { reportId: string; version: number }) =>
      rollbackReport(vars.reportId, vars.version),
    onSuccess: (_data, vars) => invalidate(vars.reportId),
  });
}

export function useReviewReport() {
  const invalidate = useInvalidateReport();
  return useMutation({
    mutationFn: (vars: { reportId: string; action: ReviewAction; note?: string }) =>
      reviewReport(vars.reportId, vars.action, vars.note),
    onSuccess: (_data, vars) => invalidate(vars.reportId),
  });
}
