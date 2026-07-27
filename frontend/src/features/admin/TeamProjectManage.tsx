import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Network, Plus } from "lucide-react";
import { api } from "@/api/client";
import type { ProjectOut, TeamOut, UserOut } from "@/api/types";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "@/components/ui/use-toast";

export function TeamProjectManage() {
  return (
    <div className="space-y-4">
      <h1 className="flex items-center gap-2 text-lg font-semibold">
        <Network className="h-5 w-5" /> 团队 / 项目管理
      </h1>
      <Tabs defaultValue="teams">
        <TabsList>
          <TabsTrigger value="teams">团队</TabsTrigger>
          <TabsTrigger value="projects">项目</TabsTrigger>
        </TabsList>
        <TabsContent value="teams">
          <TeamsPanel />
        </TabsContent>
        <TabsContent value="projects">
          <ProjectsPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function TeamsPanel() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["admin-teams"],
    queryFn: () => api.get<TeamOut[]>("/admin/teams"),
  });
  const users = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => api.get<UserOut[]>("/admin/users"),
  });
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [memberTeam, setMemberTeam] = useState<string | null>(null);
  const [memberUser, setMemberUser] = useState("");

  const createTeam = useMutation({
    mutationFn: (n: string) => api.post<TeamOut>("/admin/teams", { name: n, description: "" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-teams"] });
      setOpen(false);
      setName("");
    },
  });

  const addMember = useMutation({
    mutationFn: (v: { team: string; user: string }) =>
      api.post(`/admin/teams/${v.team}/members`, { user_id: v.user, role_in_team: "member" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-teams"] });
      setMemberTeam(null);
      setMemberUser("");
      toast({ title: "成员已加入" });
    },
    onError: (e) => toast({ variant: "destructive", description: String(e) }),
  });

  const removeMember = useMutation({
    mutationFn: (v: { team: string; user: string }) =>
      api.del(`/admin/teams/${v.team}/members/${v.user}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-teams"] }),
  });

  if (isLoading) return <Skeleton className="h-32 w-full" />;
  return (
    <div className="space-y-3">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button size="sm">
            <Plus className="h-4 w-4" /> 新建团队
          </Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建团队</DialogTitle>
          </DialogHeader>
          <div className="space-y-1">
            <Label htmlFor="tn">团队名</Label>
            <Input id="tn" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <DialogFooter>
            <Button onClick={() => createTeam.mutate(name)} disabled={createTeam.isPending}>
              创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <div className="space-y-2">
        {(data ?? []).map((t) => (
          <div key={t.id} className="rounded-md border p-3">
            <div className="flex items-center justify-between">
              <span className="font-medium">{t.name}</span>
              <Badge variant="outline">{t.members.length} 成员</Badge>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {t.members.map((m) => (
                <Badge key={m.user_id} variant="secondary" className="gap-1">
                  {m.username}
                  <button
                    onClick={() => removeMember.mutate({ team: t.id, user: m.user_id })}
                    className="ml-1 text-xs opacity-60 hover:opacity-100"
                  >
                    ×
                  </button>
                </Badge>
              ))}
              <Dialog open={memberTeam === t.id} onOpenChange={(o) => setMemberTeam(o ? t.id : null)}>
                <DialogTrigger asChild>
                  <button className="rounded border px-1.5 text-xs hover:bg-accent">+ 加成员</button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>加入 {t.name}</DialogTitle>
                  </DialogHeader>
                  <Select value={memberUser} onValueChange={setMemberUser}>
                    <SelectTrigger>
                      <SelectValue placeholder="选择用户" />
                    </SelectTrigger>
                    <SelectContent>
                      {(users.data ?? []).map((u) => (
                        <SelectItem key={u.id} value={u.id}>
                          {u.username}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <DialogFooter>
                    <Button
                      onClick={() => addMember.mutate({ team: t.id, user: memberUser })}
                      disabled={!memberUser}
                    >
                      加入
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ProjectsPanel() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["admin-projects"],
    queryFn: () => api.get<ProjectOut[]>("/admin/projects"),
  });
  const teams = useQuery({
    queryKey: ["admin-teams"],
    queryFn: () => api.get<TeamOut[]>("/admin/teams"),
  });
  const users = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => api.get<UserOut[]>("/admin/users"),
  });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", team_id: "" });
  const [memberProj, setMemberProj] = useState<string | null>(null);
  const [memberUser, setMemberUser] = useState("");

  const create = useMutation({
    mutationFn: (f: { name: string; team_id: string }) =>
      api.post<ProjectOut>("/admin/projects", { ...f, description: "" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-projects"] });
      setOpen(false);
      setForm({ name: "", team_id: "" });
    },
  });

  const addMember = useMutation({
    mutationFn: (v: { proj: string; user: string }) =>
      api.post(`/admin/projects/${v.proj}/members`, {
        user_id: v.user,
        role: "analyst",
        role_in_project: "member",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-projects"] });
      setMemberProj(null);
      setMemberUser("");
    },
  });

  const removeMember = useMutation({
    mutationFn: (v: { proj: string; user: string }) =>
      api.del(`/admin/projects/${v.proj}/members/${v.user}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-projects"] }),
  });

  if (isLoading) return <Skeleton className="h-32 w-full" />;
  return (
    <div className="space-y-3">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button size="sm">
            <Plus className="h-4 w-4" /> 新建项目
          </Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建项目</DialogTitle>
          </DialogHeader>
          <div className="space-y-1">
            <Label htmlFor="pn">项目名</Label>
            <Input id="pn" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="space-y-1">
            <Label>所属团队</Label>
            <Select value={form.team_id} onValueChange={(v) => setForm({ ...form, team_id: v })}>
              <SelectTrigger>
                <SelectValue placeholder="选择团队" />
              </SelectTrigger>
              <SelectContent>
                {(teams.data ?? []).map((t) => (
                  <SelectItem key={t.id} value={t.id}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button onClick={() => create.mutate(form)} disabled={create.isPending || !form.team_id}>
              创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <div className="space-y-2">
        {(data ?? []).map((p) => (
          <div key={p.id} className="rounded-md border p-3">
            <div className="flex items-center justify-between">
              <span className="font-medium">{p.name}</span>
              <Badge variant="outline">{p.members.length} 成员</Badge>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {p.members.map((m) => (
                <Badge key={m.user_id} variant="secondary" className="gap-1">
                  {m.role ?? "member"}
                  <button
                    onClick={() => removeMember.mutate({ proj: p.id, user: m.user_id })}
                    className="ml-1 text-xs opacity-60 hover:opacity-100"
                  >
                    ×
                  </button>
                </Badge>
              ))}
              <Dialog open={memberProj === p.id} onOpenChange={(o) => setMemberProj(o ? p.id : null)}>
                <DialogTrigger asChild>
                  <button className="rounded border px-1.5 text-xs hover:bg-accent">+ 加成员</button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>加入 {p.name}</DialogTitle>
                  </DialogHeader>
                  <Select value={memberUser} onValueChange={setMemberUser}>
                    <SelectTrigger>
                      <SelectValue placeholder="选择用户" />
                    </SelectTrigger>
                    <SelectContent>
                      {(users.data ?? []).map((u) => (
                        <SelectItem key={u.id} value={u.id}>
                          {u.username}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <DialogFooter>
                    <Button
                      onClick={() => addMember.mutate({ proj: p.id, user: memberUser })}
                      disabled={!memberUser}
                    >
                      加入
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}