import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Plus } from "lucide-react";
import { api } from "@/api/client";
import type { ContributionOut } from "@/api/types";
import { useAccess } from "@/auth/useAccess";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/use-toast";
import { ContributionDetail } from "./ContributionDetail";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  draft: "secondary",
  submitted: "default",
  approved: "default",
  rejected: "destructive",
  merged: "outline",
  closed: "secondary",
};

const EMPTY_FORM = {
  source_scope: "personal",
  target_scope: "project",
  target_project_id: "",
  title: "",
  doc_ids: "",
  description: "",
};

export function ContributionsPanel() {
  const qc = useQueryClient();
  const access = useAccess();
  const { data, isLoading } = useQuery({
    queryKey: ["collab-contributions"],
    queryFn: () => api.get<ContributionOut[]>("/collab"),
  });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const create = useMutation({
    mutationFn: (body: unknown) => api.post<ContributionOut>("/collab", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["collab-contributions"] });
      toast({ title: "推送已创建" });
      setOpen(false);
      setForm(EMPTY_FORM);
    },
    onError: (e) =>
      toast({ variant: "destructive", title: "创建失败", description: String(e) }),
  });

  const act = useMutation({
    mutationFn: (vars: { id: string; action: string; reason?: string }) => {
      if (vars.action === "reject") {
        return api.post<ContributionOut>(`/collab/${vars.id}/reject`, {
          reason: vars.reason ?? "",
        });
      }
      return api.post<ContributionOut>(`/collab/${vars.id}/${vars.action}`, {});
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["collab-contributions"] }),
    onError: (e) =>
      toast({ variant: "destructive", title: "操作失败", description: String(e) }),
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate({
      source_scope: form.source_scope,
      target_scope: form.target_scope,
      target_project_id: form.target_project_id || null,
      title: form.title,
      doc_ids: form.doc_ids
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      description: form.description,
    });
  };

  // 自审阻断：源用户不能 approve/merge 自己的推送（后端守卫，前端禁用按钮 UX）
  const isSelf = (c: ContributionOut) => c.source_user_id === access.me?.user_id;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">协作推送</h2>
        {access.canPush() && (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <Plus className="mr-2 h-4 w-4" />
                建推送
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>新建贡献请求</DialogTitle>
              </DialogHeader>
              <form onSubmit={onSubmit} className="space-y-3">
                <div>
                  <Label>标题</Label>
                  <Input
                    value={form.title}
                    onChange={(e) => setForm({ ...form, title: e.target.value })}
                    required
                  />
                </div>
                <div>
                  <Label>文档 id（逗号分隔）</Label>
                  <Input
                    value={form.doc_ids}
                    onChange={(e) => setForm({ ...form, doc_ids: e.target.value })}
                    placeholder="d1,d2"
                  />
                </div>
                <div>
                  <Label>目标 project id</Label>
                  <Input
                    value={form.target_project_id}
                    onChange={(e) =>
                      setForm({ ...form, target_project_id: e.target.value })
                    }
                    placeholder="project uuid"
                  />
                </div>
                <div>
                  <Label>描述</Label>
                  <Input
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                  />
                </div>
                <DialogFooter>
                  <Button type="submit" disabled={create.isPending}>
                    创建
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        )}
      </div>
      {isLoading ? (
        <Skeleton className="h-32" />
      ) : !data || data.length === 0 ? (
        <p className="text-sm text-muted-foreground">（无贡献请求）</p>
      ) : (
        <div className="rounded-md border">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className="p-2 text-left">标题</th>
                <th className="p-2 text-left">源 → 目标</th>
                <th className="p-2 text-left">状态</th>
                <th className="p-2 text-left">指派</th>
                <th className="p-2 text-left">操作</th>
              </tr>
            </thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.id} className="border-b">
                  <td className="p-2">{c.title}</td>
                  <td className="p-2 text-muted-foreground">
                    {c.source_scope} → {c.target_scope}
                  </td>
                  <td className="p-2">
                    <Badge variant={STATUS_VARIANT[c.status] ?? "secondary"}>
                      {c.status}
                    </Badge>
                  </td>
                  <td className="p-2 text-xs text-muted-foreground">
                    {c.assignee_id ? c.assignee_id.slice(0, 8) : "待指派"}
                  </td>
                  <td className="p-2 space-x-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setDetailId(c.id);
                        setDetailOpen(true);
                      }}
                    >
                      详情
                    </Button>
                    {access.canPush() && c.status === "draft" && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={act.isPending}
                        onClick={() => act.mutate({ id: c.id, action: "submit" })}
                      >
                        提交
                      </Button>
                    )}
                    {access.canApprove() && c.status === "submitted" && (
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={act.isPending || isSelf(c)}
                          onClick={() => act.mutate({ id: c.id, action: "approve" })}
                        >
                          批准
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={act.isPending}
                          onClick={() =>
                            act.mutate({ id: c.id, action: "reject", reason: "" })
                          }
                        >
                          驳回
                        </Button>
                      </>
                    )}
                    {access.canApprove() && c.status === "approved" && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={act.isPending || isSelf(c)}
                        onClick={() => act.mutate({ id: c.id, action: "merge" })}
                      >
                        合并
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ContributionDetail
        contributionId={detailId}
        title={data?.find((c) => c.id === detailId)?.title ?? ""}
        open={detailOpen}
        onOpenChange={setDetailOpen}
        canApprove={access.canApprove()}
      />
    </div>
  );
}
