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

interface GraphNode {
  id: string;
  name: string;
  type: string;
  color: string;
  expanded?: boolean;
}
interface GraphLink {
  source: string;
  target: string;
  label?: string;
}

export function EntityGraph({ initialSeeds }: { initialSeeds: string[] }) {
  const [seeds, setSeeds] = useState<string[]>(initialSeeds);
  const [hops, setHops] = useState(1);
  const [limit, setLimit] = useState(50);
  const [selected, setSelected] = useState<SubgraphNode | null>(null);
  const expandedRef = useRef<Set<string>>(new Set(initialSeeds));
  const { data, isFetching } = useSubgraph(seeds, hops, limit);

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

  // react-force-graph-2d 无原生双击事件：单击切换"选中"，按住 Ctrl/Shift 单击切换"展开/折叠"
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
                className={
                  "px-2 py-1 text-xs " + (hops === h ? "bg-primary text-primary-foreground" : "")
                }
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
                className={
                  "px-2 py-1 text-xs " +
                  (limit === l ? "bg-primary text-primary-foreground" : "")
                }
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
          <Info className="h-3 w-3" /> Ctrl/Shift+单击节点展开/折叠邻居
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
            nodeLabel="name"
            nodeColor="color"
            nodeRelSize={5}
            linkDirectionalArrowLength={4}
            onNodeClick={onNodeClick}
            width={640}
            height={360}
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
            {expandedRef.current.has(selected.name) && (
              <Badge variant="default">已展开</Badge>
            )}
          </div>
          <p className="text-muted-foreground">{selected.description}</p>
        </div>
      )}
    </div>
  );
}
