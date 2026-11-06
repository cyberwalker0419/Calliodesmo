// 报告生命周期操作面板（P8 T7）：版本链 / 回滚 / 软删除 / 复核流。
// 权限：提交复核限 owner（报告固定 personal，详情可见即 owner）；复核通过 / 驳回
// 另需 APPROVE（canApprove 由上层 useAccess 注入，后端守卫为最终闸）。
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  useDeleteReport,
  useReportVersions,
  useReviewReport,
  useRollbackReport,
} from "./useAnalysis";

const REVIEW_STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  pending: "待复核",
  approved: "已通过",
  rejected: "已驳回",
};

const REVIEW_STATUS_CLASS: Record<string, string> = {
  draft: "bg-secondary",
  pending: "bg-amber-500 text-white",
  approved: "bg-emerald-600",
  rejected: "bg-destructive",
};

export interface ReportLifecyclePanelProps {
  reportId: string;
  reviewStatus: string;
  canApprove: boolean;
  onDeleted?: () => void;
}

export function ReportLifecyclePanel({
  reportId,
  reviewStatus,
  canApprove,
  onDeleted,
}: ReportLifecyclePanelProps) {
  const versions = useReportVersions(reportId);
  const rollback = useRollbackReport();
  const remove = useDeleteReport();
  const review = useReviewReport();
  const [showVersions, setShowVersions] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [pendingRollback, setPendingRollback] = useState<number | null>(null);
  // 动作成功后本地即时更新状态（列表随后重取；避免 Dialog 内保持旧状态）
  const [currentStatus, setCurrentStatus] = useState(reviewStatus);
  useEffect(() => setCurrentStatus(reviewStatus), [reviewStatus]);

  const error =
    (rollback.error as Error | null) ??
    (remove.error as Error | null) ??
    (review.error as Error | null);

  return (
    <div className="space-y-2 rounded-md border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">报告生命周期</span>
        <Badge className={REVIEW_STATUS_CLASS[currentStatus] ?? "bg-secondary"}>
          {REVIEW_STATUS_LABEL[currentStatus] ?? currentStatus}
        </Badge>
        <button
          type="button"
          className="ml-auto text-xs text-muted-foreground hover:text-foreground"
          onClick={() => setShowVersions(!showVersions)}
        >
          {showVersions ? "收起版本" : `版本记录（${versions.data?.total ?? 0}）`}
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {(currentStatus === "draft" || currentStatus === "rejected") && (
          <Button
            size="sm"
            variant="outline"
            disabled={review.isPending}
            onClick={() =>
              review.mutate(
                { reportId, action: "submit" },
                { onSuccess: (data) => setCurrentStatus(data.review_status) }
              )
            }
          >
            提交复核
          </Button>
        )}
        {currentStatus === "pending" && canApprove && (
          <>
            <Button
              size="sm"
              disabled={review.isPending}
              onClick={() =>
                review.mutate(
                  { reportId, action: "approve" },
                  { onSuccess: (data) => setCurrentStatus(data.review_status) }
                )
              }
            >
              通过
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={review.isPending}
              onClick={() =>
                review.mutate(
                  { reportId, action: "reject", note: "驳回" },
                  { onSuccess: (data) => setCurrentStatus(data.review_status) }
                )
              }
            >
              驳回
            </Button>
          </>
        )}
        {currentStatus === "pending" && !canApprove && (
          <span className="self-center text-xs text-muted-foreground">
            待复核（需 approve 权限处理）
          </span>
        )}
        {confirmDelete ? (
          <>
            <Button
              size="sm"
              variant="destructive"
              disabled={remove.isPending}
              onClick={() =>
                remove.mutate(reportId, {
                  onSuccess: () => {
                    setConfirmDelete(false);
                    onDeleted?.();
                  },
                })
              }
            >
              确认删除
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>
              取消
            </Button>
          </>
        ) : (
          <Button
            size="sm"
            variant="outline"
            className="text-destructive"
            onClick={() => setConfirmDelete(true)}
          >
            删除
          </Button>
        )}
      </div>

      {error ? <p className="text-xs text-destructive">{error.message}</p> : null}

      {showVersions && (
        <div className="space-y-1">
          {versions.isLoading ? (
            <p className="text-xs text-muted-foreground">加载版本…</p>
          ) : (versions.data?.items ?? []).length === 0 ? (
            <p className="text-xs text-muted-foreground">（无版本）</p>
          ) : (
            <ul className="space-y-1">
              {(versions.data?.items ?? []).map((v) => (
                <li
                  key={v.version}
                  className="flex flex-wrap items-center gap-2 rounded border px-2 py-1 text-xs"
                >
                  <span className="font-medium">v{v.version}</span>
                  <span className="text-muted-foreground">{v.status}</span>
                  <span className="text-muted-foreground">{v.model}</span>
                  <span className="text-muted-foreground">
                    {v.created_at.slice(0, 19).replace("T", " ")}
                  </span>
                  {pendingRollback === v.version ? (
                    <>
                      <Button
                        size="sm"
                        variant="destructive"
                        className="ml-auto h-6 px-2 text-xs"
                        disabled={rollback.isPending}
                        onClick={() =>
                          rollback.mutate(
                            { reportId, version: v.version },
                            { onSuccess: () => setPendingRollback(null) }
                          )
                        }
                      >
                        确认回滚
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 px-2 text-xs"
                        onClick={() => setPendingRollback(null)}
                      >
                        取消
                      </Button>
                    </>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      className="ml-auto h-6 px-2 text-xs"
                      onClick={() => setPendingRollback(v.version)}
                    >
                      回滚到此版本
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
