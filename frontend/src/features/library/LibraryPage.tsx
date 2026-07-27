import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "@/api/client";
import type { CommunityOut, EntityOut, ProfileCardOut } from "@/api/types";
import { EntityGraph } from "./EntityGraph";
import { ScopeSwitcher, type ScopeValue } from "./ScopeSwitcher";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

function ProfileCardList({
  onSelect,
  scope,
}: {
  onSelect: (name: string) => void;
  scope: string | null;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["profile-cards", scope],
    queryFn: () =>
      api.get<ProfileCardOut[]>("/library/profile-cards", { scope: scope ?? undefined }),
  });
  if (isLoading) return <Skeleton className="h-20 w-full" />;
  if (!data?.length)
    return <p className="text-sm text-muted-foreground">无可见档案卡（检查权限或种子演示数据）。</p>;
  return (
    <div className="divide-y rounded-md border">
      {data.map((c) => (
        <button
          key={c.entity_name}
          onClick={() => onSelect(c.entity_name)}
          className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-accent/60"
        >
          <span className="font-medium">{c.entity_name}</span>
          <span className="flex items-center gap-2">
            {c.entity_type && <Badge variant="secondary">{c.entity_type}</Badge>}
            <Badge variant="outline">{c.access_level}</Badge>
          </span>
        </button>
      ))}
    </div>
  );
}

function ProfileCardDetail({ name }: { name: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["profile-card", name],
    queryFn: () => api.get<ProfileCardOut>(`/library/profile-cards/${name}`),
  });
  if (isLoading) return <Skeleton className="h-40 w-full" />;
  if (!data) return <p className="text-sm text-muted-foreground">档案卡不可见或不存在。</p>;
  return (
    <div className="space-y-3 rounded-md border bg-card p-4">
      <div className="flex items-center gap-2">
        <h3 className="text-base font-semibold">{data.entity_name}</h3>
        {data.entity_type && <Badge variant="secondary">{data.entity_type}</Badge>}
        <Badge variant="outline">{data.access_level}</Badge>
        <Badge variant="outline">{data.library_scope}</Badge>
      </div>
      <Separator />
      <dl className="grid grid-cols-[120px_1fr] gap-y-1 text-sm">
        {data.aliases.length > 0 && <><dt className="text-muted-foreground">别名</dt><dd>{data.aliases.join("、")}</dd></>}
        {data.role && <><dt className="text-muted-foreground">职务</dt><dd>{data.role}</dd></>}
        {data.organization && <><dt className="text-muted-foreground">所属组织</dt><dd>{data.organization}</dd></>}
        {data.associates.length > 0 && <><dt className="text-muted-foreground">关联人</dt><dd>{data.associates.join("、")}</dd></>}
        {data.timespan && <><dt className="text-muted-foreground">时间跨度</dt><dd>{data.timespan}</dd></>}
      </dl>
      {data.description && <p className="text-sm text-muted-foreground">{data.description}</p>}
      {data.narrative && (
        <div className="rounded-md bg-muted/40 p-3">
          <div className="mb-1 text-xs font-medium text-muted-foreground">概览叙述（不参与检索）</div>
          <p className="text-sm">{data.narrative}</p>
        </div>
      )}
      {data.evidence_chunk_ids.length > 0 && (
        <div className="text-xs text-muted-foreground">证据：{data.evidence_chunk_ids.join("、")}</div>
      )}
    </div>
  );
}

function CommunityNav({
  onSelect,
  scope,
}: {
  onSelect: (name: string) => void;
  scope: string | null;
}) {
  const [level, setLevel] = useState("1");
  const { data, isLoading } = useQuery({
    queryKey: ["communities", level, scope],
    queryFn: () =>
      api.get<CommunityOut[]>("/library/communities", {
        level: Number(level),
        scope: scope ?? undefined,
      }),
  });
  return (
    <div className="space-y-3">
      <Tabs value={level} onValueChange={setLevel}>
        <TabsList>
          <TabsTrigger value="1">文档社区</TabsTrigger>
          <TabsTrigger value="0">实体社区</TabsTrigger>
        </TabsList>
      </Tabs>
      {isLoading ? (
        <Skeleton className="h-20 w-full" />
      ) : !data?.length ? (
        <p className="text-sm text-muted-foreground">无可见社区。</p>
      ) : (
        <div className="space-y-2">
          {data.map((c) => (
            <div key={c.community_id} className="rounded-md border p-3">
              <div className="flex items-center justify-between">
                <span className="font-medium">{c.title}</span>
                <Badge variant="outline">{c.access_level}</Badge>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">{c.summary}</p>
              {c.member_entity_names.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {c.member_entity_names.map((n) => (
                    <button
                      key={n}
                      onClick={() => onSelect(n)}
                      className="rounded border px-1.5 py-0.5 text-xs hover:bg-accent"
                    >
                      {n}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function EntityDetail({ name, scope }: { name: string; scope: string | null }) {
  const { data, isLoading } = useQuery({
    queryKey: ["entity", name],
    queryFn: () => api.get<EntityOut>(`/library/entities/${encodeURIComponent(name)}`),
  });
  const seeds = useMemo(() => (name ? [name] : []), [name]);
  if (isLoading) return <Skeleton className="h-60 w-full" />;
  if (!data) return <p className="text-sm text-muted-foreground">实体不可见或不存在。</p>;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="space-y-3 rounded-md border bg-card p-4">
        <div className="flex items-center gap-2">
          <h3 className="text-base font-semibold">{data.name}</h3>
          {data.type && <Badge variant="secondary">{data.type}</Badge>}
          <Badge variant="outline">{data.access_level}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">{data.description}</p>
        {data.neighbors.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">直接邻居</div>
            <div className="flex flex-wrap gap-1">
              {data.neighbors.map((n) => (
                <Badge key={n.name} variant="outline">{n.name}</Badge>
              ))}
            </div>
          </div>
        )}
        {data.relations.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">关系</div>
            <ul className="space-y-1 text-sm">
              {data.relations.map((r, i) => (
                <li key={i}>
                  <span className="font-medium">{r.source}</span>
                  <span className="text-muted-foreground">{` -${r.type ?? ""}-> `}</span>
                  <span className="font-medium">{r.target}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <div className="h-[420px]">
        <EntityGraph initialSeeds={seeds} scope={scope} />
      </div>
    </div>
  );
}

export function LibraryPage() {
  const [selected, setSelected] = useState<string | null>(null);
  const [scope, setScope] = useState<ScopeValue>(null);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">知识库浏览</h1>
        <ScopeSwitcher value={scope} onChange={setScope} />
      </div>
      <Tabs defaultValue="cards">
        <TabsList>
          <TabsTrigger value="cards">档案卡</TabsTrigger>
          <TabsTrigger value="communities">社区导航</TabsTrigger>
          <TabsTrigger value="entity">实体详情</TabsTrigger>
        </TabsList>
        <TabsContent value="cards" className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ProfileCardList onSelect={setSelected} scope={scope} />
          {selected && <ProfileCardDetail name={selected} />}
        </TabsContent>
        <TabsContent value="communities">
          <CommunityNav onSelect={setSelected} scope={scope} />
        </TabsContent>
        <TabsContent value="entity">
          {selected ? (
            <EntityDetail name={selected} scope={scope} />
          ) : (
            <p className="text-sm text-muted-foreground">从档案卡或社区选择一个实体查看详情与子图。</p>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}