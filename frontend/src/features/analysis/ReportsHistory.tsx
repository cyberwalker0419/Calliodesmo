// 报告历史页（P6 Task 20）：列表（消费 listReports，limit/offset 分页）+
// 状态 / 类型 / 密级标签 + 点击进详情（ReportDialog 懒加载，克隆
// ContributionsPanel + ContributionDetail 交互范式）+ 导出权限透传。
// 权限：列表 / 详情端点均 ANALYZE 门控（后端 api/analysis.py），导航由
// App.tsx access.can(ANALYZE) 隐藏；页内守卫为双保险（直访兜底）。
// 导出按钮可用性透传 canExport（后端守卫仅 EXPORT；种子三角色均含
// export，禁用态仅自定义角色场景出现，见计划决策 1）。
import { useState } from "react";
import {
  ANALYSIS_TASK_TYPES,
  PERMISSIONS,
  type AnalysisTaskType,
} from "@/api/types";
import { useAccess } from "@/auth/useAccess";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ReportDialog } from "./ReportViewer";
import { useReports } from "./useAnalysis";

/** 每页条数（后端 limit 上限 100；10 条便于分页器演示与滚动控制）。 */
const PAGE_SIZE = 10;

/** 报告状态徽章着色（ok / partial 两态落库；failed 防御）。 */
const STATUS_CLASS: Record<string, string> = {
  ok: "bg-emerald-600",
  partial: "bg-amber-500 text-white",
  failed: "bg-destructive",
};

/** task_type -> 中文标签（未收录类型回退原值）。 */
function typeLabel(taskType: AnalysisTaskType | string): string {
  return ANALYSIS_TASK_TYPES.find((t) => t.value === taskType)?.label ?? taskType;
}

/** ISO 时刻 -> 「YYYY-MM-DD HH:mm」展示（与 ReportViewer 同截断口径）。 */
function formatCreatedAt(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

export function ReportsHistory() {
  const access = useAccess();
  const canAnalyze = access.can(PERMISSIONS.ANALYZE);
  const canExport = access.can(PERMISSIONS.EXPORT);
  const [page, setPage] = useState(0);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const offset = page * PAGE_SIZE;
  const { data, isLoading, isError, error } = useReports(
    canAnalyze ? { limit: PAGE_SIZE, offset } : { limit: PAGE_SIZE, offset, enabled: false }
  );

  if (!canAnalyze) {
    return (
      <div className="mx-auto max-w-3xl space-y-4">
        <h2 className="text-lg font-semibold">报告历史</h2>
        <p className="text-sm text-muted-foreground">
          无 analyze 权限，联系管理员（导航已隐藏，直访兜底）。
        </p>
      </div>
    );
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">报告历史</h2>
        <span className="text-xs text-muted-foreground">
          报告固定个人库（仅本人可见，含 admin）
        </span>
      </div>

      {isLoading ? (
        <Skeleton className="h-32" />
      ) : isError ? (
        <p className="text-sm text-destructive">
          加载报告历史失败：{error instanceof Error ? error.message : "未知错误"}
        </p>
      ) : items.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          （暂无可见报告；先在「分析」页提交一次分析任务）
        </p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50">
                <tr>
                  <th className="p-2 text-left">类型</th>
                  <th className="p-2 text-left">分析对象</th>
                  <th className="p-2 text-left">状态</th>
                  <th className="p-2 text-left">密级</th>
                  <th className="p-2 text-left">生成时间</th>
                  <th className="p-2 text-left">块数</th>
                  <th className="p-2 text-left">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <tr key={r.id} className="border-b last:border-b-0">
                    <td className="whitespace-nowrap p-2">
                      <Badge variant="secondary">{typeLabel(r.task_type)}</Badge>
                    </td>
                    <td className="max-w-48 truncate p-2" title={r.subject_label}>
                      {r.subject_label}
                    </td>
                    <td className="p-2">
                      <Badge className={STATUS_CLASS[r.status] ?? "bg-secondary"}>
                        {r.status}
                      </Badge>
                    </td>
                    <td className="p-2">
                      <Badge variant="outline">{r.access_level}</Badge>
                    </td>
                    <td className="whitespace-nowrap p-2 text-xs text-muted-foreground">
                      {formatCreatedAt(r.created_at)}
                    </td>
                    <td className="p-2 text-xs text-muted-foreground">
                      {r.source_chunk_count}
                    </td>
                    <td className="p-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setDetailId(r.id);
                          setDetailOpen(true);
                        }}
                      >
                        详情
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 分页（后端 total 为过滤后可见总行数） */}
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              共 {total} 条 · 第 {page + 1}/{pageCount} 页
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
              >
                上一页
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setPage((p) => p + 1)}
              >
                下一页
              </Button>
            </div>
          </div>
        </>
      )}

      <ReportDialog
        reportId={detailId}
        open={detailOpen}
        onOpenChange={setDetailOpen}
        canExport={canExport}
      />
    </div>
  );
}
