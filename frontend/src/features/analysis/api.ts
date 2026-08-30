// 分析域 API 客户端（P6 Task 18）：提交 202 / 报告历史与详情 / 导出链接 / 可见文档清单。
// 端点与后端 src/calliodesmo/api/analysis.py 逐一对齐（根 + /api 前缀双挂，
// 客户端统一走 /api 前缀，同既有路由口径）；复用 @/api/client 的会话与错误处理。

import { api } from "@/api/client";
import type {
  AnalysisAccepted,
  AnalysisDocumentOut,
  AnalysisEnvelope,
  AnalysisJobRequest,
  ReportListOut,
} from "@/api/types";

/** POST /analysis/tasks -> 202 + job_id（异步 analyze job，进度经 GET /jobs/{id} 轮询）。 */
export function submitAnalysisTask(req: AnalysisJobRequest): Promise<AnalysisAccepted> {
  return api.post<AnalysisAccepted>("/analysis/tasks", req);
}

/** GET /analysis/reports：报告历史（三维可见性过滤 + limit/offset 分页，默认 20/0）。 */
export function listReports(
  params: { limit?: number; offset?: number } = {}
): Promise<ReportListOut> {
  const limit = params.limit ?? 20;
  const offset = params.offset ?? 0;
  return api.get<ReportListOut>("/analysis/reports", { limit, offset });
}

/** GET /analysis/reports/{report_id}：完整信封（不可见 / 不存在 -> 404，客户端抛 ApiError）。 */
export function getReport(reportId: string): Promise<AnalysisEnvelope> {
  return api.get<AnalysisEnvelope>(`/analysis/reports/${reportId}`);
}

/** 构造导出附件下载链接（GET /analysis/reports/{id}/export?format=json|md）。
 *
 * 浏览器导航触发附件下载（Content-Disposition），同源 cookie 会话随导航自动携带；
 * md 按信封 JSON 分节渲染（后端 render_report_markdown，不返回大段自由文本）。
 */
export function exportReportUrl(reportId: string, format: "json" | "md" = "json"): string {
  return `/api/analysis/reports/${reportId}/export?format=${format}`;
}

/** GET /analysis/documents：可见文档清单（按 doc_id 聚合；Task 19 MaterialPicker 数据源）。 */
export function listAnalysisDocuments(): Promise<AnalysisDocumentOut[]> {
  return api.get<AnalysisDocumentOut[]>("/analysis/documents");
}
