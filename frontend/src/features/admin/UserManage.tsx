import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Plus, UserCog } from "lucide-react";
import { api } from "@/api/client";
import type { UserOut } from "@/api/types";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/use-toast";

const CLEARANCES = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "SECRET"];

export function UserManage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => api.get<UserOut[]>("/admin/users"),
  });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ username: "", password: "", clearance: "INTERNAL" });

  const create = useMutation({
    mutationFn: (body: { username: string; password: string; clearance: string }) =>
      api.post<UserOut>("/admin/users", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      toast({ title: "用户已创建" });
      setOpen(false);
      setForm({ username: "", password: "", clearance: "INTERNAL" });
    },
    onError: (e) =>
      toast({ variant: "destructive", title: "创建失败", description: String(e) }),
  });

  const patchClearance = useMutation({
    mutationFn: (vars: { id: string; clearance: string }) =>
      api.patch<UserOut>(`/admin/users/${vars.id}`, { clearance: vars.clearance }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const toggleActive = useMutation({
    mutationFn: (vars: { id: string; is_active: boolean }) =>
      api.patch<UserOut>(`/admin/users/${vars.id}`, { is_active: vars.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const deactivate = useMutation({
    mutationFn: (id: string) => api.del(`/admin/users/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <UserCog className="h-5 w-5" /> 用户管理
        </h1>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm">
              <Plus className="h-4 w-4" /> 新建用户
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>新建用户</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <div className="space-y-1">
                <Label htmlFor="nu">用户名</Label>
                <Input
                  id="nu"
                  value={form.username}
                  onChange={(e) => setForm({ ...form, username: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="np">密码</Label>
                <Input
                  id="np"
                  type="password"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label>访问等级</Label>
                <Select
                  value={form.clearance}
                  onValueChange={(v) => setForm({ ...form, clearance: v })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CLEARANCES.map((c) => (
                      <SelectItem key={c} value={c}>
                        {c}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button onClick={() => create.mutate(form)} disabled={create.isPending}>
                创建
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : (
        <div className="overflow-hidden rounded-md border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-3 py-2">用户名</th>
                <th className="px-3 py-2">访问等级</th>
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {(data ?? []).map((u) => (
                <tr key={u.id}>
                  <td className="px-3 py-2 font-medium">{u.username}</td>
                  <td className="px-3 py-2">
                    <Select
                      value={u.clearance}
                      onValueChange={(v) => patchClearance.mutate({ id: u.id, clearance: v })}
                    >
                      <SelectTrigger className="h-7 w-32">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {CLEARANCES.map((c) => (
                          <SelectItem key={c} value={c}>
                            {c}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant={u.is_active ? "default" : "secondary"}>
                      {u.is_active ? "激活" : "停用"}
                    </Badge>
                  </td>
                  <td className="px-3 py-2">
                    {u.is_active ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          if (confirm(`停用 ${u.username}？（软删除，保留审计）`))
                            deactivate.mutate(u.id);
                        }}
                      >
                        停用
                      </Button>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => toggleActive.mutate({ id: u.id, is_active: true })}
                      >
                        恢复
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}