import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderKanban } from "lucide-react";
import { useState } from "react";
import { api } from "@/api/client";
import type { CommunityOut } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/use-toast";
import { CommunityVersionsDialog } from "./CommunityVersionsDialog";

const LEVELS = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "SECRET"];

export function DocumentCommunityManage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["admin-doc-communities"],
    queryFn: () => api.get<CommunityOut[]>("/admin/document-communities"),
  });
  const docComms = (data ?? []).filter((c) => c.level === 1);

  const rename = useMutation({
    mutationFn: (v: { id: string; title: string }) =>
      api.patch(`/admin/document-communities/${v.id}`, { title: v.title }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-doc-communities"] }),
  });
  const setAccess = useMutation({
    mutationFn: (v: { id: string; access_level: string }) =>
      api.patch(`/admin/document-communities/${v.id}`, { access_level: v.access_level }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-doc-communities"] }),
  });

  return (
    <div className="space-y-4">
      <h1 className="flex items-center gap-2 text-lg font-semibold">
        <FolderKanban className="h-5 w-5" /> 文档社区手动管理
      </h1>
      <p className="text-sm text-muted-foreground">
        在自动派生之上手动命名、设 access_level；版本回滚/合并/拆分见各行「版本」按钮。
      </p>
      {isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : docComms.length === 0 ? (
        <p className="text-sm text-muted-foreground">暂无文档社区（需先 ingest 文档派生 level=1 社区）。</p>
      ) : (
        <div className="space-y-2">
          {docComms.map((c) => (
            <CommunityRow
              key={c.community_id}
              c={c}
              onRename={(title) =>
                rename.mutate(
                  { id: c.community_id, title },
                  {
                    onSuccess: () => toast({ title: "已重命名" }),
                    onError: (e) =>
                      toast({ variant: "destructive", description: String(e) }),
                  }
                )
              }
              onAccess={(access_level) =>
                setAccess.mutate(
                  { id: c.community_id, access_level },
                  {
                    onSuccess: () => toast({ title: "access_level 已更新" }),
                    onError: (e) =>
                      toast({ variant: "destructive", description: String(e) }),
                  }
                )
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

function CommunityRow({
  c,
  onRename,
  onAccess,
}: {
  c: CommunityOut;
  onRename: (title: string) => void;
  onAccess: (level: string) => void;
}) {
  const [title, setTitle] = useState(c.title);
  const [versionOpen, setVersionOpen] = useState(false);
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border p-3">
      <div className="flex-1">
        <Input value={title} onChange={(e) => setTitle(e.target.value)} className="h-8" />
        <p className="mt-1 truncate text-xs text-muted-foreground">{c.summary}</p>
      </div>
      <Badge variant="outline">{String(c.metadata?.doc_id ?? c.community_id)}</Badge>
      <Select value={c.access_level} onValueChange={onAccess}>
        <SelectTrigger className="h-8 w-36">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {LEVELS.map((l) => (
            <SelectItem key={l} value={l}>
              {l}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        size="sm"
        variant="outline"
        disabled={title === c.title}
        onClick={() => onRename(title)}
      >
        重命名
      </Button>
      <Button size="sm" variant="secondary" onClick={() => setVersionOpen(true)}>
        版本
      </Button>
      <CommunityVersionsDialog
        community={c}
        open={versionOpen}
        onOpenChange={setVersionOpen}
      />
    </div>
  );
}