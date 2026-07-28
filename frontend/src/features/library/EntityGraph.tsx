import { Info, Crosshair, Star } from "lucide-react";
import { useMemo, useState, useCallback, useRef, useEffect } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { SubgraphNode, SubgraphEdge } from "@/api/types";
import { useSubgraph } from "./useSubgraph";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const TYPE_COLORS: Record<string, string> = {
  person: "#2563eb",
  organization: "#16a34a",
  org: "#16a34a",
  model: "#9333ea",
  location: "#ea580c",
};
const LEGEND: Array<[string, string]> = [
  ["person", "#2563eb"],
  ["organization", "#16a34a"],
  ["model", "#9333ea"],
  ["location", "#ea580c"],
];

interface GraphNode {
  id: string;
  name: string;
  type: string;
  color: string;
  expanded?: boolean;
  focus?: boolean;
  x?: number;
  y?: number;
}
interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
  label?: string;
}

const CENTER_ZOOM = 1.0; // 初始/居中缩放（避免过大）

export function EntityGraph({
  initialSeeds,
  scope = null,
  onSeedsChange,
  onNodes,
  centerOnName,
}: {
  initialSeeds: string[];
  scope?: string | null;
  onSeedsChange?: (seeds: string[]) => void;
  onNodes?: (names: string[]) => void;
  centerOnName?: string | null;
}) {
  const [seeds, setSeeds] = useState<string[]>(initialSeeds);
  const [hops, setHops] = useState(1);
  const [limit, setLimit] = useState(50);
  const [selected, setSelected] = useState<SubgraphNode | null>(null);
  const [focusIds, setFocusIds] = useState<string[]>([]);
  const expandedRef = useRef<Set<string>>(new Set(initialSeeds));
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgRef = useRef<any>(null);
  // 节点对象缓存：跨重拉保留位置（切回同一实体图布局不抖动）
  const nodeCacheRef = useRef<Map<string, GraphNode>>(new Map());
  // 待居中目标（仅触发时居中，不随每次重拉乱动）
  const pendingCenterRef = useRef<string | null>(null);
  // 展开后一次性把图中实体同步勾选
  const autoSyncRef = useRef(false);
  const { data, isFetching } = useSubgraph(seeds, hops, limit, scope);

  useEffect(() => {
    setSeeds(initialSeeds);
    expandedRef.current = new Set(initialSeeds);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSeeds.join("|")]);

  // 列表勾选实体 -> 居中到该实体（仅触发时居中，切回不抖动）
  useEffect(() => {
    if (centerOnName) pendingCenterRef.current = centerOnName;
  }, [centerOnName]);

  // 报告图中实体 + 展开后一次性同步勾选
  useEffect(() => {
    const names = (data?.nodes ?? []).map((n) => n.name);
    onNodes?.(names);
    if (autoSyncRef.current && onSeedsChange) {
      autoSyncRef.current = false;
      onSeedsChange(names);
    }
  }, [data, onNodes, onSeedsChange]);

  const { nodes, links } = useMemo(() => {
    const raw = data?.nodes ?? [];
    const edges = data?.edges ?? [];
    const cache = nodeCacheRef.current;
    const gn: GraphNode[] = [];
    for (const n of raw) {
      let node = cache.get(n.name);
      if (!node) {
        node = {
          id: n.name,
          name: n.name,
          type: n.type ?? "unknown",
          color: TYPE_COLORS[(n.type ?? "").toLowerCase()] ?? "#64748b",
          x: undefined,
          y: undefined,
        };
        cache.set(n.name, node);
      }
      // 刷新非位置字段
      node.type = n.type ?? "unknown";
      node.color = TYPE_COLORS[(n.type ?? "").toLowerCase()] ?? "#64748b";
      node.expanded = expandedRef.current.has(n.name);
      node.focus = focusIds.includes(n.name);
      gn.push(node);
    }
    const gl: GraphLink[] = edges.map((e: SubgraphEdge) => ({
      source: e.source,
      target: e.target,
      label: e.type ?? undefined,
    }));
    return { nodes: gn, links: gl };
  }, [data, focusIds]);

  const centerOn = useCallback((name: string | null) => {
    const fg = fgRef.current;
    if (!fg || !name) return;
    const node = nodeCacheRef.current.get(name);
    if (node && node.x != null && node.y != null) {
      fg.centerAt(node.x, node.y, 400);
      fg.zoom(CENTER_ZOOM, 400);
    }
  }, []);

  const onNodeClick = useCallback(
    (node: GraphNode, ev: MouseEvent) => {
      if (ev.altKey) {
        // 设/取消焦点 -> 居中最后一个焦点
        setFocusIds((prev) => {
          const next = prev.includes(node.id) ? prev.filter((x) => x !== node.id) : [...prev, node.id];
          pendingCenterRef.current = next.length ? next[next.length - 1] : null;
          return next;
        });
        return;
      }
      if (ev.ctrlKey || ev.shiftKey) {
        // 展开/折叠 -> 居中操作节点 + 一次性同步勾选图中实体
        const next = new Set(seeds);
        if (next.has(node.id)) {
          next.delete(node.id);
          expandedRef.current.delete(node.id);
        } else {
          next.add(node.id);
          expandedRef.current.add(node.id);
        }
        const arr = [...next];
        pendingCenterRef.current = node.id;
        autoSyncRef.current = true;
        setSeeds(arr);
        return;
      }
      const raw = data?.nodes.find((n) => n.name === node.id);
      setSelected(raw ?? null);
    },
    [data, seeds]
  );

  const fitAll = useCallback(() => {
    try {
      fgRef.current?.zoomToFit(100, 80);
    } catch {
      /* ignore */
    }
  }, []);

  const centerOnFocus = useCallback(() => {
    const target = focusIds.length ? focusIds[focusIds.length - 1] : seeds[0] ?? null;
    centerOn(target);
  }, [focusIds, seeds, centerOn]);

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          跳数
          <Input type="number" min={0} max={5} value={hops} onChange={(e) => setHops(Math.max(0, Math.min(5, Number(e.target.value) || 0)))} className="h-7 w-14" />
        </label>
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          上限
          <Input type="number" min={1} max={500} value={limit} onChange={(e) => setLimit(Math.max(1, Math.min(500, Number(e.target.value) || 1)))} className="h-7 w-16" />
        </label>
        <Button type="button" size="sm" variant="outline" onClick={fitAll} className="h-7 gap-1 px-2 text-xs">
          <Crosshair className="h-3 w-3" /> 居中全部
        </Button>
        <Button type="button" size="sm" variant={focusIds.length ? "default" : "outline"} onClick={centerOnFocus} className="h-7 gap-1 px-2 text-xs">
          <Star className="h-3 w-3" /> 居中焦点{focusIds.length ? `(${focusIds.length})` : ""}
        </Button>
        {data?.truncated && <Badge variant="outline" className="text-amber-600">已截断</Badge>}
        <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
          <Info className="h-3 w-3" /> 单击看详情；Alt+单击设焦点；Ctrl/Shift+单击展开折叠
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>类型:</span>
        {LEGEND.map(([t, c]) => (
          <span key={t} className="inline-flex items-center gap-1">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: c }} />
            {t}
          </span>
        ))}
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-full border-2 border-slate-900" style={{ background: "transparent" }} />
          已展开
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "#eab308" }} />
          焦点
        </span>
      </div>
      <div className="relative flex-1 overflow-hidden rounded-md border bg-muted/20">
        {isFetching && nodes.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">加载子图…</div>
        ) : nodes.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">无可见子图（检查权限或勾选种子实体）</div>
        ) : (
          <ForceGraph2D
            ref={fgRef}
            graphData={{ nodes, links }}
            nodeId="id"
            nodeLabel={(n: GraphNode) => `${n.name}${n.type && n.type !== "unknown" ? `（${n.type}）` : ""}${n.focus ? " ★" : ""}`}
            onEngineStop={() => {
              // 仅当有待居中目标时居中（选择/展开/焦点触发）；否则保留用户视图不动
              if (pendingCenterRef.current) {
                centerOn(pendingCenterRef.current);
                pendingCenterRef.current = null;
              }
            }}
            nodeCanvasObject={(node: GraphNode, ctx, globalScale) => {
              const r = node.focus ? 6 : 5;
              if (node.x == null || node.y == null) return;
              ctx.fillStyle = node.color;
              ctx.beginPath();
              ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
              ctx.fill();
              if (node.focus) {
                ctx.strokeStyle = "#eab308";
                ctx.lineWidth = 3;
                ctx.stroke();
              } else if (node.expanded) {
                ctx.strokeStyle = "#0f172a";
                ctx.lineWidth = 2;
                ctx.stroke();
              }
              if (globalScale > 1.1) {
                const fs = Math.max(6, 7 / globalScale);
                ctx.font = `${fs}px sans-serif`;
                ctx.textAlign = "center";
                ctx.textBaseline = "top";
                ctx.fillStyle = "#334155";
                ctx.fillText(node.name, node.x, node.y + r + 2);
              }
            }}
            nodePointerAreaPaint={(node: GraphNode, color, ctx) => {
              if (node.x == null || node.y == null) return;
              ctx.fillStyle = color;
              ctx.beginPath();
              ctx.arc(node.x, node.y, 10, 0, 2 * Math.PI);
              ctx.fill();
            }}
            linkLabel={(l: GraphLink) => l.label ?? ""}
            linkDirectionalArrowLength={4}
            linkCanvasObjectMode="after"
            linkCanvasObject={(link: GraphLink, ctx, globalScale) => {
              if (!link.label || globalScale < 1.3) return;
              const s = link.source as GraphNode;
              const t = link.target as GraphNode;
              if (s == null || t == null || s.x == null || s.y == null || t.x == null || t.y == null) return;
              const x = (s.x + t.x) / 2;
              const y = (s.y + t.y) / 2;
              const fs = Math.max(5, 6 / globalScale);
              ctx.font = `${fs}px sans-serif`;
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              const w = ctx.measureText(link.label).width + 5;
              ctx.fillStyle = "rgba(255,255,255,0.85)";
              ctx.fillRect(x - w / 2, y - 6, w, 11);
              ctx.fillStyle = "#64748b";
              ctx.fillText(link.label, x, y);
            }}
            onNodeClick={onNodeClick}
            cooldownTicks={50}
          />
        )}
      </div>
      {selected && (
        <div className="rounded-md border bg-card p-3 text-sm">
          <div className="mb-1 flex items-center gap-2">
            <span className="font-medium">{selected.name}</span>
            {selected.type && <Badge variant="secondary">{selected.type}</Badge>}
            <Badge variant="outline">{selected.access_level}</Badge>
            {expandedRef.current.has(selected.name) && <Badge variant="default">已展开</Badge>}
            {focusIds.includes(selected.name) && <Badge className="bg-amber-500">焦点</Badge>}
          </div>
          <p className="text-muted-foreground">{selected.description}</p>
        </div>
      )}
    </div>
  );
}