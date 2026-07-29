import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import type { CommunityOut, ProfileCardOut } from "@/api/types";
import { EntityGraph } from "./EntityGraph";
import { ScopeSwitcher, type ScopeValue } from "./ScopeSwitcher";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { normName, hasName } from "@/lib/names";

function EntityList({
  seeds,
  graphNodes,
  onToggle,
  onFocus,
  scope,
}: {
  seeds: string[];
  graphNodes: string[];
  onToggle: (name: string) => void;
  onFocus: (name: string) => void;
  scope: string | null;
}) {
  const [q, setQ] = useState("");
  const { data, isLoading } = useQuery({
    queryKey: ["profile-cards", scope],
    queryFn: () => api.get<ProfileCardOut[]>("/library/profile-cards", { scope: scope ?? undefined }),
  });
  const graphSet = useMemo(() => new Set(graphNodes.map(normName)), [graphNodes]);
  const seedSet = useMemo(() => new Set(seeds.map(normName)), [seeds]);
  const filtered = useMemo(
    () => (data ?? []).filter((c) => !q || c.entity_name.toLowerCase().includes(q.toLowerCase())),
    [data, q]
  );
  return (
    <div className="space-y-2">
      <Input placeholder="搜索实体名..." value={q} onChange={(e) => setQ(e.target.value)} className="h-8" />
      {isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : !filtered.length ? (
        <p className="text-sm text-muted-foreground">无可见实体（检查权限或种子演示数据）。</p>
      ) : (
        <div className="max-h-[420px] divide-y overflow-auto rounded-md border">
          {filtered.map((c) => {
            const key = normName(c.entity_name);
            const inGraph = graphSet.has(key);
            const isSeed = seedSet.has(key);
            return (
              <div
                key={c.entity_name}
                className={
                  "flex items-center gap-2 px-2 py-1.5 text-sm hover:bg-accent/60 " +
                  (inGraph ? "bg-amber-50 dark:bg-amber-950/30" : "")
                }
              >
                <input
                  type="checkbox"
                  checked={inGraph}
                  onChange={() => onToggle(c.entity_name)}
                  className="h-3.5 w-3.5"
                />
                <button
                  onClick={() => onFocus(c.entity_name)}
                  className="flex flex-1 items-center justify-between gap-2 truncate text-left"
                >
                  <span className="truncate font-medium">{c.entity_name}</span>
                  <span className="flex shrink-0 items-center gap-1">
                    {isSeed && <Badge className="bg-amber-500 px-1 text-[10px]">种子</Badge>}
                    {c.entity_type && <Badge variant="secondary">{c.entity_type}</Badge>}
                    <Badge variant="outline">{c.access_level}</Badge>
                  </span>
                </button>
              </div>
            );
          })}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        勾选实体查看其关系网络；图中出现的实体会自动勾选，取消勾选将其从图中移除（种子 = 已展开的实体）。
      </p>
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
      <dl className="grid grid-cols-[100px_1fr] gap-y-1 text-sm">
        {data.aliases.length > 0 && (
          <>
            <dt className="text-muted-foreground">别名</dt>
            <dd>{data.aliases.join("、")}</dd>
          </>
        )}
        {data.role && (
          <>
            <dt className="text-muted-foreground">职务</dt>
            <dd>{data.role}</dd>
          </>
        )}
        {data.organization && (
          <>
            <dt className="text-muted-foreground">所属组织</dt>
            <dd>{data.organization}</dd>
          </>
        )}
        {data.associates.length > 0 && (
          <>
            <dt className="text-muted-foreground">关联人</dt>
            <dd>{data.associates.join("、")}</dd>
          </>
        )}
        {data.timespan && (
          <>
            <dt className="text-muted-foreground">时间跨度</dt>
            <dd>{data.timespan}</dd>
          </>
        )}
      </dl>
      {data.description && <p className="text-sm text-muted-foreground">{data.description}</p>}
      {data.narrative && (
        <div className="rounded-md bg-muted/40 p-3">
          <div className="mb-1 text-xs font-medium text-muted-foreground">概览叙述（不参与检索）</div>
          <p className="text-sm">{data.narrative}</p>
        </div>
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
                <span className="flex items-center gap-1">
                  <Badge variant="outline">{c.member_entity_names.length} 实体</Badge>
                  <Badge variant="outline">{c.access_level}</Badge>
                </span>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">{c.summary || "（社区无摘要）"}</p>
              <div className="mt-1 text-xs text-muted-foreground">
                社区主题/归组依据由 LLM 据成员共现与语义生成；点击成员可在图谱查看其关系。
              </div>
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

export function LibraryPage() {
  const [tab, setTab] = useState("graph");
  // seeds = 展开集合（图谱查询种子）；hidden = 用户从图中移除的实体；graphNodes = 当前图中实体
  const [seeds, setSeeds] = useState<string[]>([]);
  const [hidden, setHidden] = useState<string[]>([]);
  const [graphNodes, setGraphNodes] = useState<string[]>([]);
  const [focused, setFocused] = useState<string | null>(null);
  const [centerOnName, setCenterOnName] = useState<string | null>(null);
  const [scope, setScope] = useState<ScopeValue>(null);

  // 无种子时图已卸载，同步清空“图中”集合，避免残留勾选
  useEffect(() => {
    if (seeds.length === 0) setGraphNodes([]);
  }, [seeds.length]);

  // 勾选 = 该实体当前在图中；取消勾选 = 从图中移除（折叠种子 + 隐藏以杜绝作为邻居残留）
  const toggle = (n: string) => {
    if (hasName(graphNodes, n)) {
      if (hasName(seeds, n)) setSeeds((s) => s.filter((x) => normName(x) !== normName(n)));
      setHidden((h) => (hasName(h, n) ? h : [...h, n]));
      setCenterOnName(null);
    } else {
      setHidden((h) => h.filter((x) => normName(x) !== normName(n)));
      if (!hasName(seeds, n)) setSeeds((s) => [...s, n]);
      setCenterOnName(n);
    }
  };
  // 点实体名：看档案 + 视角移到该节点（若在图中）
  const focusEntity = (n: string) => {
    setFocused(n);
    if (hasName(graphNodes, n)) setCenterOnName(n);
  };
  const fromCommunity = (n: string) => {
    setSeeds([n]);
    setHidden([]);
    setFocused(n);
    setCenterOnName(n);
    setTab("graph");
  };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">知识库浏览</h1>
        <ScopeSwitcher value={scope} onChange={setScope} />
      </div>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="graph">实体图谱</TabsTrigger>
          <TabsTrigger value="communities">社区导航</TabsTrigger>
        </TabsList>
        <TabsContent value="graph" className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="space-y-3">
            <EntityList
              seeds={seeds}
              graphNodes={graphNodes}
              onToggle={toggle}
              onFocus={focusEntity}
              scope={scope}
            />
            {focused && <ProfileCardDetail name={focused} />}
          </div>
          <div className="h-[600px]">
            {seeds.length ? (
              <EntityGraph
                initialSeeds={seeds}
                hidden={hidden}
                scope={scope}
                onSeedsChange={setSeeds}
                onNodes={setGraphNodes}
                centerOnName={centerOnName}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                勾选左侧实体（可多选）查看关系图谱。
              </div>
            )}
          </div>
        </TabsContent>
        <TabsContent value="communities">
          <CommunityNav onSelect={fromCommunity} scope={scope} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
