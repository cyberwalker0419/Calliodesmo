import { Info } from "lucide-react";
import { useMemo, useState, useCallback, useRef, useEffect } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { SubgraphNode, SubgraphEdge } from "@/api/types";
import { useSubgraph } from "./useSubgraph";
import { Badge } from "@/components/ui/badge";

const TYPE_COLORS: Record<string, string> = {
  person: "#2563eb",
  organization: "#16a34a",
  org: "#16a34a",
  model: "#9333ea",
  location: "#ea580c",
};

// 图例展示的类型（org 与 organization 同色，去重）
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
  x?: number;
  y?: number;
}
// 构造时 source/target 为实体名字符串；react-force-graph-2d 渲染时会被解析为节点对象（带 x/y）
interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
  label?: string;
}

export function EntityGraph({ initialSeeds, scope = null }: { initialSeeds: string[]; scope?: string | null }) {
  const [seeds, setSeeds] = useState<string[]>(initialSeeds);
  const [hops, setHops] = useState(1);
  const [limit, setLimit] = useState(50);
  const [selected, setSelected] = useState<SubgraphNode | null>(null);
  const expandedRef = useRef<Set<string>>(new Set(initialSeeds));
  const { data, isFetching } = useSubgraph(seeds, hops, limit, scope);

  useEffect(() => {
    setSeeds(initialSeeds);
    expandedRef.current = new Set(initialSeeds);
  }, [initialSeeds.join("|")]);

  const { nodes, links } = useMemo(() => {
    const raw = data?.nodes ?? [];
    const edges = data?.edges ?? [];
    const gn: GraphNode[] = raw.map((n) => ({
      id: n.name,
      name: n.name,
      type: n.type ?? "unknown",
      color: TYPE_COLORS[(n.type ?? "").toLowerCase()] ?? "#64748b",
      expanded: expandedRef.current.has(n.name),
    }));
    const gl: GraphLink[] = edges.map((e: SubgraphEdge) => ({
      source: e.source,
      target: e.target,
      label: e.type ?? undefined,
    }));
    return { nodes: gn, links: gl };
  }, [data]);

  const onNodeClick = useCallback(
    (node: GraphNode, ev: MouseEvent) => {
      if (ev.ctrlKey || ev.shiftKey) {
        setSeeds((prev) => {
          const next = new Set(prev);
          if (next.has(node.id)) {
            next.delete(node.id);
            expandedRef.current.delete(node.id);
          } else {
            next.add(node.id);
            expandedRef.current.add(node.id);
          }
          return [...next];
        });
        return;
      }
      const raw = data?.nodes.find((n) => n.name === node.id);
      setSelected(raw ?? null);
    },
    [data]
  );

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">跳数</span>
          <div className="inline-flex rounded-md border">
            {[1, 2, 3].map((h) => (
              <button
                key={h}
                onClick={() => setHops(h)}
                className={"px-2 py-1 text-xs " + (hops === h ? "bg-primary text-primary-foreground" : "")}
              >
                {h}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">节点上限</span>
          <div className="inline-flex rounded-md border">
            {[50, 100, 200, 500].map((l) => (
              <button
                key={l}
                onClick={() => setLimit(l)}
                className={"px-2 py-1 text-xs " + (limit === l ? "bg-primary text-primary-foreground" : "")}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
        {data?.truncated && (
          <Badge variant="outline" className="text-amber-600">
            已截断，提高上限或折叠部分节点查看更多
          </Badge>
        )}
        <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
          <Info className="h-3 w-3" /> Ctrl/Shift+单击展开/折叠；拖拽节点/平移画布
        </span>
      </div>
      {/* 类型图例 */}
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>类型:</span>
        {LEGEND.map(([t, c]) => (
          <span key={t} className="inline-flex items-center gap-1">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: c }} />
            {t}
          </span>
        ))}
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "#64748b" }} />
          其他
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2.5 w-2.5 rounded-full border-2 border-slate-900" />
          已展开
        </span>
      </div>
      <div className="relative flex-1 overflow-hidden rounded-md border bg-muted/20">
        {isFetching && nodes.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            加载子图…
          </div>
        ) : nodes.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            无可见子图（检查权限或选择种子实体）
          </div>
        ) : (
          <ForceGraph2D
            graphData={{ nodes, links }}
            nodeId="id"
            nodeLabel={(n: GraphNode) =>
              `${n.name}${n.type && n.type !== "unknown" ? `（${n.type}）` : ""}`
            }
            nodeCanvasObject={(node: GraphNode, ctx) => {
              const r = 5;
              if (node.x == null || node.y == null) return;
              ctx.fillStyle = node.color;
              ctx.beginPath();
              ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
              ctx.fill();
              if (node.expanded) {
                ctx.strokeStyle = "#0f172a";
                ctx.lineWidth = 2;
                ctx.stroke();
              }
              ctx.font = "10px sans-serif";
              ctx.textAlign = "center";
              ctx.textBaseline = "top";
              ctx.fillStyle = "#334155";
              ctx.fillText(node.name, node.x, node.y + r + 2);
            }}
            nodePointerAreaPaint={(node: GraphNode, color, ctx) => {
              if (node.x == null || node.y == null) return;
              ctx.fillStyle = color;
              ctx.beginPath();
              ctx.arc(node.x, node.y, 9, 0, 2 * Math.PI);
              ctx.fill();
            }}
            linkLabel={(l: GraphLink) => l.label ?? ""}
            linkDirectionalArrowLength={4}
            linkCanvasObjectMode="after"
            linkCanvasObject={(link: GraphLink, ctx) => {
              if (!link.label) return;
              const s = link.source as GraphNode;
              const t = link.target as GraphNode;
              if (s == null || t == null || s.x == null || s.y == null || t.x == null || t.y == null) return;
              const x = (s.x + t.x) / 2;
              const y = (s.y + t.y) / 2;
              ctx.font = "9px sans-serif";
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              const w = ctx.measureText(link.label).width + 6;
              ctx.fillStyle = "rgba(255,255,255,0.85)";
              ctx.fillRect(x - w / 2, y - 7, w, 13);
              ctx.fillStyle = "#475569";
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
          </div>
          <p className="text-muted-foreground">{selected.description}</p>
        </div>
      )}
    </div>
  );
}