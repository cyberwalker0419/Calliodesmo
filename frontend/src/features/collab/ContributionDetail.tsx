import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCheck,
  FileText,
  GitBranch,
  Layers,
  Users,
  X,
} from "lucide-react";
import { api } from "@/api/client";
import type {
  AlignmentPending,
  AlignmentReviewOut,
  DiffOut,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/use-toast";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";

interface ContributionDetailProps {
  contributionId: string | null;
  title: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canApprove?: boolean;
}

/** 计数卡片：图标 + 数字 + 标签。 */
function StatCard({
  icon,
  value,
  label,
  tone = "default",
}: {
  icon: ReactNode;
  value: number;
  label: string;
  tone?: "default" | "warn";
}) {
  return (
    <div
      className={`flex flex-col items-center rounded-md border p-2 text-center ${
        tone === "warn" ? "border-destructive/40 bg-destructive/5" : "bg-muted/30"
      }`}
    >
      <div className="text-muted-foreground">{icon}</div>
      <div className="mt-1 text-lg font-semibold leading-none">{value}</div>
      <div className="mt-0.5 text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

/** 明细列表：空态友好提示。 */
function DetailList({
  items,
  emptyText,
  render,
}: {
  items: string[] | string[][];
  emptyText: string;
  render: (item: string | string[], i: number) => ReactNode;
}) {
  if (!items || items.length === 0) {
    return <p className="py-4 text-center text-sm text-muted-foreground">{emptyText}</p>;
  }
  return (
    <ul className="max-h-64 space-y-1 overflow-auto py-1 text-sm">
      {items.map((item, i) => (
        <li
          key={i}
          className="rounded-sm bg-muted/30 px-2 py-1 font-mono text-xs break-all"
        >
          {render(item, i)}
        </li>
      ))}
    </ul>
  );
}

/** 待审对齐对列表项：source↔target + 相似度 + 类型/描述对比 + 批准/驳回。 */
function AlignmentCard({
  pair,
  canApprove,
  onResolve,
  busy,
}: {
  pair: AlignmentPending;
  canApprove: boolean;
  onResolve: (pairId: string, action: "approve" | "reject") => void;
  busy: boolean;
}) {
  const pct = Math.round(pair.score * 100);
  const tone =
    pair.score >= 0.95 ? "text-emerald-500" : pair.score >= 0.85 ? "text-amber-500" : "text-muted-foreground";
  return (
    <div className="rounded-md border p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate font-mono text-sm font-medium">{pair.source_name}</span>
          <span className="text-muted-foreground">→</span>
          <span className="truncate font-mono text-sm font-medium">{pair.target_name}</span>
          <Badge variant="outline" className="ml-1 shrink-0 text-[10px]">
            {pair.type ?? "—"}
          </Badge>
        </div>
        <span className={`shrink-0 text-sm font-semibold ${tone}`}>
          {pct}%
        </span>
      </div>
      <div className="mt-2 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
        <div className="rounded-sm bg-muted/30 p-2">
          <div className="mb-0.5 font-medium text-foreground">源 · {pair.source_type ?? "—"}</div>
          {pair.source_description || "（无描述）"}
        </div>
        <div className="rounded-sm bg-muted/30 p-2">
          <div className="mb-0.5 font-medium text-foreground">目标 · {pair.target_type ?? "—"}</div>
          {pair.target_description || "（无描述）"}
        </div>
      </div>
      {canApprove && (
        <div className="mt-2 flex justify-end gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => onResolve(pair.pair_id, "reject")}
          >
            <X className="mr-1 h-3 w-3" />
            驳回
          </Button>
          <Button
            size="sm"
            disabled={busy}
            onClick={() => onResolve(pair.pair_id, "approve")}
          >
            <CheckCheck className="mr-1 h-3 w-3" />
            批准合并
          </Button>
        </div>
      )}
    </div>
  );
}

/**
 * ContributionDetail：差异清单详情（消费 GET /collab/{id}/diff）。
 *
 * 懒加载：仅 ``open`` 时拉取 diff（GET 端点会在 manifest 缺失时自动 collect+build）。
 * 展示 6 个计数卡片（实体/关系/chunk/社区/冲突/待审对齐）+ Tabs 明细（实体名/关系/chunk/社区 id/对齐）。
 * 对齐复核（P4.5 Task 6）：待审对 + 批准/驳回；自审/无 APPROVE 时仅展示无操作按钮。
 */
export function ContributionDetail({
  contributionId,
  title,
  open,
  onOpenChange,
  canApprove = false,
}: ContributionDetailProps) {
  const qc = useQueryClient();
  const { data: diff, isLoading, error } = useQuery({
    queryKey: ["collab-diff", contributionId],
    queryFn: () => api.get<DiffOut>(`/collab/${contributionId}/diff`),
    enabled: !!contributionId && open,
  });

  const resolve = useMutation({
    mutationFn: (vars: { pairId: string; action: "approve" | "reject" }) =>
      api.post<AlignmentReviewOut>(
        `/collab/${contributionId}/alignment-review/${vars.action}`,
        { pair_id: vars.pairId }
      ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["collab-diff", contributionId] });
      toast({
        title: vars.action === "approve" ? "已批准合并" : "已驳回",
      });
    },
    onError: (e) =>
      toast({ variant: "destructive", title: "复核失败", description: String(e) }),
  });

  const pending = diff?.alignment_pending ?? [];
  const pendingCount = pending.filter((p) => p.status !== "approved" && p.status !== "rejected").length;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span>差异清单</span>
            <span className="truncate text-sm font-normal text-muted-foreground">
              {title}
            </span>
          </DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        ) : error ? (
          <p className="text-sm text-destructive">
            加载差异失败：{(error as Error).message}
          </p>
        ) : diff ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
              <StatCard
                icon={<Users className="h-4 w-4" />}
                value={diff.new_entities}
                label="实体"
              />
              <StatCard
                icon={<GitBranch className="h-4 w-4" />}
                value={diff.new_relations}
                label="关系"
              />
              <StatCard
                icon={<FileText className="h-4 w-4" />}
                value={diff.chunks}
                label="文本块"
              />
              <StatCard
                icon={<Layers className="h-4 w-4" />}
                value={diff.communities}
                label="社区"
              />
              <StatCard
                icon={<AlertTriangle className="h-4 w-4" />}
                value={diff.conflicts}
                label="同名冲突"
                tone={diff.conflicts > 0 ? "warn" : "default"}
              />
              <StatCard
                icon={<CheckCheck className="h-4 w-4" />}
                value={pendingCount}
                label="待审对齐"
                tone={pendingCount > 0 ? "warn" : "default"}
              />
            </div>

            {diff.conflicts > 0 && (
              <p className="flex items-center gap-1 text-xs text-muted-foreground">
                <AlertTriangle className="h-3 w-3 text-destructive" />
                目标库存在 {diff.conflicts} 项同名同类型实体（v1 按 name 精确合并；
                同名不同义明细见下方「对齐复核」Tab）。
              </p>
            )}

            {pending.length > 0 && (
              <p className="flex items-center gap-1 text-xs text-muted-foreground">
                <CheckCheck className="h-3 w-3 text-amber-500" />
                {pendingCount} 对待审对齐（相似度 0.85-0.95）：批准并入目标库或驳回保留新节点。
              </p>
            )}

            <Tabs defaultValue="entities">
              <TabsList className="flex-wrap">
                <TabsTrigger value="entities">
                  实体（{diff.entity_names.length}）
                </TabsTrigger>
                <TabsTrigger value="relations">
                  关系（{diff.relation_summaries.length}）
                </TabsTrigger>
                <TabsTrigger value="chunks">
                  文本块（{diff.chunk_ids.length}）
                </TabsTrigger>
                <TabsTrigger value="communities">
                  社区（{diff.community_ids.length}）
                </TabsTrigger>
                <TabsTrigger value="alignment">
                  对齐复核（{pendingCount}）
                </TabsTrigger>
              </TabsList>
              <TabsContent value="entities" className="mt-2">
                <DetailList
                  items={diff.entity_names}
                  emptyText="（无实体）"
                  render={(n) => String(n)}
                />
              </TabsContent>
              <TabsContent value="relations" className="mt-2">
                <DetailList
                  items={diff.relation_summaries}
                  emptyText="（无关系）"
                  render={(r) => {
                    const [s, t, type] = r as string[];
                    return (
                      <span>
                        <span className="text-foreground">{s}</span>
                        <span className="mx-1 text-muted-foreground">→</span>
                        <span className="text-foreground">{t}</span>
                        {type ? (
                          <Badge variant="outline" className="ml-2 text-[10px]">
                            {type}
                          </Badge>
                        ) : null}
                      </span>
                    );
                  }}
                />
              </TabsContent>
              <TabsContent value="chunks" className="mt-2">
                <DetailList
                  items={diff.chunk_ids}
                  emptyText="（无文本块）"
                  render={(c) => String(c)}
                />
              </TabsContent>
              <TabsContent value="communities" className="mt-2">
                <DetailList
                  items={diff.community_ids}
                  emptyText="（无社区）"
                  render={(c) => String(c)}
                />
              </TabsContent>
              <TabsContent value="alignment" className="mt-2">
                {pending.length === 0 ? (
                  <p className="py-4 text-center text-sm text-muted-foreground">
                    （暂无待审对齐对）
                  </p>
                ) : (
                  <div className="max-h-80 space-y-2 overflow-auto py-1">
                    {pending.map((p) => (
                      <AlignmentCard
                        key={p.pair_id}
                        pair={p}
                        canApprove={canApprove}
                        busy={resolve.isPending}
                        onResolve={(pairId, action) => resolve.mutate({ pairId, action })}
                      />
                    ))}
                  </div>
                )}
              </TabsContent>
            </Tabs>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
