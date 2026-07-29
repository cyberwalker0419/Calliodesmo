import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { GitBranch, History, Split } from "lucide-react";
import { api } from "@/api/client";
import type { CommunityOut, CommunityVersionOut } from "@/api/types";
import { useAccess } from "@/auth/useAccess";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/use-toast";

interface CommunityVersionsDialogProps {
  community: CommunityOut | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * CommunityVersions：社区版本管理（消费 /admin/community-versions + rollback/merge/split）。
 *
 * - 版本列表：append 式快照，每行可回滚到该版本（回滚=新建版本，不删历史）
 * - 合并：选其它社区合并到当前社区（target=当前，sources 输入）
 * - 拆分：按 doc_groups 拆分当前社区（每行一组 doc_id）
 *
 * 操作需 manage_community 权限（后端 _COMMUNITY_GUARD 守卫）；无权限时按钮禁用。
 */
export function CommunityVersionsDialog({
  community,
  open,
  onOpenChange,
}: CommunityVersionsDialogProps) {
  const qc = useQueryClient();
  const access = useAccess();
  const canManage = access.hasManageCommunity();
  const id = community?.community_id ?? "";

  const { data: versions, isLoading } = useQuery({
    queryKey: ["community-versions", id],
    queryFn: () => api.get<CommunityVersionOut[]>(`/admin/community-versions/${id}`),
    enabled: !!id && open,
  });

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["community-versions", id] });
    qc.invalidateQueries({ queryKey: ["admin-doc-communities"] });
  };

  const rollback = useMutation({
    mutationFn: (version: number) =>
      api.post<CommunityVersionOut>(
        `/admin/document-communities/${id}/rollback?version=${version}`
      ),
    onSuccess: () => {
      invalidateAll();
      toast({ title: "已回滚（新建版本）" });
    },
    onError: (e) =>
      toast({ variant: "destructive", title: "回滚失败", description: String(e) }),
  });

  const [mergeSources, setMergeSources] = useState("");
  const merge = useMutation({
    mutationFn: (source_ids: string[]) =>
      api.post<CommunityOut>("/admin/document-communities/merge", {
        target_id: id,
        source_ids,
      }),
    onSuccess: () => {
      invalidateAll();
      toast({ title: "已合并" });
      setMergeSources("");
    },
    onError: (e) =>
      toast({ variant: "destructive", title: "合并失败", description: String(e) }),
  });

  const [splitText, setSplitText] = useState("");
  const split = useMutation({
    mutationFn: (docGroups: string[][]) =>
      api.post<CommunityOut[]>(`/admin/document-communities/${id}/split`, {
        doc_groups: docGroups,
      }),
    onSuccess: (res) => {
      invalidateAll();
      toast({ title: `已拆分为 ${res.length} 个社区` });
      setSplitText("");
    },
    onError: (e) =>
      toast({ variant: "destructive", title: "拆分失败", description: String(e) }),
  });

  const onMerge = () => {
    const source_ids = mergeSources
      .split(/[\s,，]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (source_ids.length === 0) {
      toast({ variant: "destructive", title: "请输入源社区 id" });
      return;
    }
    merge.mutate(source_ids);
  };

  const onSplit = () => {
    // 每行一组，逗号分隔 doc_id -> [[doc_id,...],...]
    const groups = splitText
      .split("\n")
      .map((line) =>
        line
          .split(/[\s,，]+/)
          .map((s) => s.trim())
          .filter(Boolean)
      )
      .filter((g) => g.length > 0);
    if (groups.length < 2) {
      toast({ variant: "destructive", title: "拆分至少需 2 组 doc_id（每行一组）" });
      return;
    }
    split.mutate(groups);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <History className="h-4 w-4" />
            <span>社区版本</span>
            <span className="truncate text-sm font-normal text-muted-foreground">
              {community?.title ?? ""}
            </span>
          </DialogTitle>
        </DialogHeader>

        <Tabs defaultValue="versions">
          <TabsList>
            <TabsTrigger value="versions">
              版本（{versions?.length ?? 0}）
            </TabsTrigger>
            <TabsTrigger value="merge">
              <GitBranch className="mr-1 h-3 w-3" />
              合并
            </TabsTrigger>
            <TabsTrigger value="split">
              <Split className="mr-1 h-3 w-3" />
              拆分
            </TabsTrigger>
          </TabsList>

          <TabsContent value="versions" className="mt-3 space-y-2">
            {isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : !versions || versions.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted-foreground">
                （无版本快照。手动重命名/改 access_level 或合并/拆分后生成版本。）
              </p>
            ) : (
              <div className="max-h-72 overflow-auto rounded-md border">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 border-b bg-muted/50">
                    <tr>
                      <th className="p-2 text-left">版本</th>
                      <th className="p-2 text-left">创建时间</th>
                      <th className="p-2 text-left">操作者</th>
                      <th className="p-2 text-left">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {versions.map((v) => (
                      <tr key={v.id} className="border-b last:border-0">
                        <td className="p-2">
                          <Badge variant="outline">v{v.version}</Badge>
                        </td>
                        <td className="p-2 text-xs text-muted-foreground">
                          {new Date(v.created_at).toLocaleString()}
                        </td>
                        <td className="p-2 text-xs text-muted-foreground">
                          {v.created_by ? v.created_by.slice(0, 8) : "—"}
                        </td>
                        <td className="p-2">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={!canManage || rollback.isPending}
                            onClick={() => rollback.mutate(v.version)}
                          >
                            回滚到此版
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </TabsContent>

          <TabsContent value="merge" className="mt-3 space-y-2">
            <p className="text-xs text-muted-foreground">
              将其它社区合并到当前社区（当前社区为 target，输入的为 source）。合并后
              target 生成新版本快照。
            </p>
            <div>
              <Label>源社区 id（逗号分隔，可多行）</Label>
              <Textarea
                value={mergeSources}
                onChange={(e) => setMergeSources(e.target.value)}
                placeholder="doc-xxx.md, doc-yyy.md"
                className="h-20 font-mono text-xs"
              />
            </div>
            <Button
              size="sm"
              disabled={!canManage || merge.isPending}
              onClick={onMerge}
            >
              合并到当前社区
            </Button>
          </TabsContent>

          <TabsContent value="split" className="mt-3 space-y-2">
            <p className="text-xs text-muted-foreground">
              按 doc_id 组拆分当前社区。每行一组（逗号分隔 doc_id），至少 2 组。
              拆分后各新社区生成版本快照。
            </p>
            <div>
              <Label>doc 分组（每行一组）</Label>
              <Textarea
                value={splitText}
                onChange={(e) => setSplitText(e.target.value)}
                placeholder={"doc-a.md, doc-b.md\ndoc-c.md"}
                className="h-24 font-mono text-xs"
              />
            </div>
            <Button
              size="sm"
              disabled={!canManage || split.isPending}
              onClick={onSplit}
            >
              拆分当前社区
            </Button>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
