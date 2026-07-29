import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, FileText, GitBranch, Layers, Users } from "lucide-react";
import { api } from "@/api/client";
import type { DiffOut } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
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

/**
 * ContributionDetail：差异清单详情（消费 GET /collab/{id}/diff）。
 *
 * 懒加载：仅 ``open`` 时拉取 diff（GET 端点会在 manifest 缺失时自动 collect+build）。
 * 展示 5 个计数卡片（实体/关系/chunk/社区/冲突）+ Tabs 明细（实体名/关系/chunk/社区 id）。
 * 冲突仅计数（同名不同义明细留 v2）。
 */
export function ContributionDetail({
  contributionId,
  title,
  open,
  onOpenChange,
}: ContributionDetailProps) {
  const { data: diff, isLoading, error } = useQuery({
    queryKey: ["collab-diff", contributionId],
    queryFn: () => api.get<DiffOut>(`/collab/${contributionId}/diff`),
    enabled: !!contributionId && open,
  });

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
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
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
            </div>

            {diff.conflicts > 0 && (
              <p className="flex items-center gap-1 text-xs text-muted-foreground">
                <AlertTriangle className="h-3 w-3 text-destructive" />
                目标库存在 {diff.conflicts} 项同名同类型实体（v1 按 name 精确合并；
                同名不同义明细留 v2）。
              </p>
            )}

            <Tabs defaultValue="entities">
              <TabsList>
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
            </Tabs>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
