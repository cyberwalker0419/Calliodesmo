import { Info, Crosshair, Star } from "lucide-react";
import { useMemo, useState, useCallback, useRef, useEffect } from "react";
import cytoscape, { type Core, type ElementDefinition, type NodeSingular, type StylesheetStyle, type LayoutOptions } from "cytoscape";
import fcose from "cytoscape-fcose";
import type { SubgraphNode } from "@/api/types";
import { useSubgraph } from "./useSubgraph";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { normName, hasName } from "@/lib/names";

// 注册 fcose 布局（一次性，模块加载即注册；fcose = 约束力导向，算法级保证节点/标签不重叠）
cytoscape.use(fcose);

// 实体类型归一化：中英别名 -> 统一 key（颜色/图例/聚类环用归一化 key，避免"公司/人物"等中文类型落灰看不清）
const TYPE_ALIASES: Record<string, string> = {
  person: "person", 人物: "person", 人: "person",
  organization: "organization", 组织: "organization", 机构: "organization", 公司: "organization", 企业: "organization", org: "organization", 联盟: "organization", 军事单位: "organization", 单位: "organization", "设施/机构": "organization", 设施: "organization",
  model: "model", 模型: "model", 型号: "model", 装备: "model", 计划: "model",
  location: "location", 地点: "location", 地区: "location", 区域: "location",
  event: "event", 事件: "event", 倡议: "event", 活动: "event", "倡议/活动": "event", 演习: "event",
  weapon: "weapon", 武器: "weapon",
  technology: "technology", 技术: "technology", 系统: "technology", "系统/计划": "technology", 工具: "technology", 平台: "technology", 网络能力: "technology", 安全架构: "technology",
  document: "document", 文档: "document", 文档版本: "document", 法案: "document", 手册: "document",
};
function normalizeType(t: string | null | undefined): string {
  const s = (t ?? "").trim().toLowerCase();
  return TYPE_ALIASES[s] ?? s;
}
const TYPE_COLORS: Record<string, string> = {
  person: "#2563eb",
  organization: "#16a34a",
  model: "#9333ea",
  location: "#ea580c",
  event: "#db2777",
  weapon: "#dc2626",
  technology: "#0891b2",
  document: "#6366f1",
};
const LEGEND: Array<[string, string]> = [
  ["person", "#2563eb"],
  ["organization", "#16a34a"],
  ["model", "#9333ea"],
  ["location", "#ea580c"],
  ["event", "#db2777"],
  ["weapon", "#dc2626"],
  ["technology", "#0891b2"],
  ["document", "#6366f1"],
];
// 聚类（按类型）模式：类型 -> 同心环序（小者居中）
const TYPE_RANK: Record<string, number> = {
  person: 0, organization: 1, model: 2, location: 3, event: 4, weapon: 5, technology: 6, document: 7,
};
const ALL_TYPE_CLASSES = [...Object.keys(TYPE_COLORS), "unknown"];

// Cytoscape 样式表：节点按度数变大小（hub 视觉层级）+ 标签白描边（可读性）；边低不透明降噪 +
// bezier 自动疏散平行边 + 悬停高亮邻域（dim 其余）。治"线条凌乱/无可读性"。
const CY_STYLE: StylesheetStyle[] = [
  {
    selector: "node",
    style: {
      "background-color": "data(color)",
      width: "data(size)",
      height: "data(size)",
      label: "data(name)",
      "text-valign": "bottom",
      "text-halign": "center",
      "text-margin-y": 4,
      "font-size": 11,
      color: "#1e293b",
      "text-outline-color": "#ffffff",
      "text-outline-width": 2.5,
      "text-outline-opacity": 1,
      "border-width": 0,
      "border-opacity": 0.9,
      "bounds-expansion": 12, // 扩大可点击包围盒，小节点/标签也易命中（治"几个节点无法选中"）
      "overlay-opacity": 0,
    },
  },
  {
    selector: "node.expanded",
    style: { "border-width": 2, "border-color": "#0f172a" },
  },
  {
    selector: "node.focus",
    style: { "border-width": 3, "border-color": "#eab308" },
  },
  {
    selector: "edge",
    style: {
      "curve-style": "bezier",
      "line-color": "#94a3b8",
      "line-opacity": 0.4,
      width: 1.4,
      "target-arrow-shape": "triangle",
      "arrow-scale": 0.8,
      "target-arrow-color": "#94a3b8",
      label: "data(label)",
      "font-size": 9,
      "text-background-color": "#ffffff",
      "text-background-opacity": 0.85,
      "text-background-shape": "roundrectangle",
      "text-rotation": "autorotate",
      "overlay-opacity": 0,
    },
  },
  { selector: ".dim", style: { opacity: 0.12, "text-opacity": 0 } },
  { selector: ".hl", style: { "border-width": 3, "border-color": "#0ea5e9", "line-color": "#0ea5e9" } },
];

type LayoutMode = "force" | "cluster" | "hierarchy" | "radial";

export function EntityGraph({
  initialSeeds,
  scope = null,
  onSeedsChange,
  onNodes,
  centerOnName,
  hidden = [],
}: {
  initialSeeds: string[];
  scope?: string | null;
  onSeedsChange?: (seeds: string[]) => void;
  onNodes?: (names: string[]) => void;
  centerOnName?: string | null;
  hidden?: string[]; // 用户从图中移除的实体（不渲染、不参与布局）
}) {
  const [seeds, setSeeds] = useState<string[]>(initialSeeds);
  const [hops, setHops] = useState(1);
  const [limit, setLimit] = useState(50);
  const [selected, setSelected] = useState<SubgraphNode | null>(null);
  const [focusIds, setFocusIds] = useState<string[]>([]);
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("force");
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  // 待居中目标（仅触发时居中一次，不随每次重拉乱动）
  const pendingCenterRef = useRef<string | null>(null);
  // 开局/切模式待 fit 标志
  const pendingFitRef = useRef(false);
  // 是否已完成开局 fit
  const hasOpenedRef = useRef(false);
  // 节点结构（id 集合）变化才重布局；选中/焦点仅改数据不重布局 -> 不漂移
  const prevLayoutRef = useRef<LayoutMode>(layoutMode);
  const prevNodeCountRef = useRef(0);
  // 首次布局标志：首次需 fcose randomize:true 散开（否则全堆原点重叠）；其后增量保位置
  const firstLayoutRef = useRef(true);
  // 布局实例 + 令牌：切模式/增量前先 stop 上一个布局（避免新旧动画并发互相覆盖 -> 切模式瞬间显示成旧布局）；
  // onStop 用令牌判过期（被新布局取代的旧 stop 回调直接跳过，防错位 fit/center）。
  const layoutApiRef = useRef<{ stop: () => void } | null>(null);
  const layoutTokenRef = useRef(0);
  // 各模式节点位置缓存：切走某模式前存当前位置，切回时恢复 -> 切去切回图形不变（治"切回图形变化"）
  const modePositionsRef = useRef<Map<string, Map<string, { x: number; y: number }>>>(new Map());
  // 最新闭包透传给 cy 事件处理器（cy 仅初始化一次，避免陈旧闭包）
  const seedsRef = useRef<string[]>(seeds);
  const onNodesRef = useRef<typeof onNodes>(onNodes);
  const onSeedsChangeRef = useRef<typeof onSeedsChange>(onSeedsChange);
  const dataRef = useRef<ReturnType<typeof useSubgraph>["data"]>(null);
  useEffect(() => { seedsRef.current = seeds; }, [seeds]);
  useEffect(() => { onNodesRef.current = onNodes; }, [onNodes]);
  useEffect(() => { onSeedsChangeRef.current = onSeedsChange; }, [onSeedsChange]);

  const { data, isFetching } = useSubgraph(seeds, hops, limit, scope);
  dataRef.current = data;

  // 左侧增删种子 -> 同步内部 seeds
  useEffect(() => {
    setSeeds(initialSeeds);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSeeds.join("|")]);

  // 元素构建：节点按度数变大小、BFS 算跳数（径向环用）；边 id 唯一化（平行边由 bezier 自动疏散）
  const { nodeDefs, edgeDefs } = useMemo(() => {
    const raw = data?.nodes ?? [];
    const edges = data?.edges ?? [];
    const hiddenSet = new Set(hidden.map(normName));
    const visible = raw.filter((n) => !hiddenSet.has(normName(n.name)));
    const visNames = new Set(visible.map((n) => normName(n.name)));
    // 度数（hub 视觉层级）
    const deg = new Map<string, number>();
    for (const n of visible) deg.set(normName(n.name), 0);
    for (const e of edges) {
      const s = normName(e.source), t = normName(e.target);
      if (visNames.has(s)) deg.set(s, (deg.get(s) ?? 0) + 1);
      if (visNames.has(t)) deg.set(t, (deg.get(t) ?? 0) + 1);
    }
    // BFS 跳数（径向环：种子居中，逐跳向外）
    const adj = new Map<string, Set<string>>();
    for (const n of visible) adj.set(normName(n.name), new Set());
    for (const e of edges) {
      const s = normName(e.source), t = normName(e.target);
      if (visNames.has(s) && visNames.has(t)) { adj.get(s)!.add(t); adj.get(t)!.add(s); }
    }
    const hop = new Map<string, number>();
    const q: string[] = [];
    for (const s of seeds) {
      const k = normName(s);
      if (visNames.has(k) && !hop.has(k)) { hop.set(k, 0); q.push(k); }
    }
    while (q.length) {
      const c = q.shift()!;
      const d = hop.get(c)!;
      for (const nb of adj.get(c) ?? []) if (!hop.has(nb)) { hop.set(nb, d + 1); q.push(nb); }
    }
    const seedSet = new Set(seeds.map(normName));
    const focusSet = new Set(focusIds.map(normName));
    const maxDeg = Math.max(1, ...visible.map((n) => deg.get(normName(n.name)) ?? 0));
    const nodeDefs: ElementDefinition[] = visible.map((n) => {
      const key = normName(n.name);
      const d = deg.get(key) ?? 0;
      const typeKey = normalizeType(n.type);
      const size = 20 + (d / maxDeg) * 20; // 20..40px，度数越高越大；底 20px 保证叶节点易点中
      return {
        group: "nodes",
        data: {
          id: key,
          name: n.name,
          type: n.type ?? "unknown",
          typeKey,
          color: TYPE_COLORS[typeKey] ?? "#64748b",
          size,
          degree: d,
          hop: hop.get(key) ?? 99,
          expanded: seedSet.has(key) ? 1 : 0,
          focus: focusSet.has(key) ? 1 : 0,
        },
        classes: [typeKey, ...(seedSet.has(key) ? ["expanded"] : []), ...(focusSet.has(key) ? ["focus"] : [])],
      };
    });
    const edgeDefs: ElementDefinition[] = edges
      .filter((e) => visNames.has(normName(e.source)) && visNames.has(normName(e.target)))
      .map((e, i) => ({
        group: "edges",
        data: {
          id: `${normName(e.source)}|${normName(e.target)}|${e.type ?? ""}|${i}`,
          source: normName(e.source),
          target: normName(e.target),
          label: e.type ?? "",
        },
      }));
    return { nodeDefs, edgeDefs };
  }, [data, seeds, focusIds, hidden]);

  // 居中到某节点（仅平移，保持当前缩放）
  const centerOn = useCallback((name: string) => {
    const cy = cyRef.current;
    if (!cy) return;
    const n = cy.getElementById(normName(name));
    if (n.empty()) return;
    cy.animate({ center: { eles: n } }, { duration: 400 });
  }, []);
  // 请求居中：节点已存在则立即居中，否则记为待居中、等布局落定后再居中
  const requestCenter = useCallback((name: string) => {
    const cy = cyRef.current;
    const key = normName(name);
    if (cy) {
      const n = cy.getElementById(key);
      if (!n.empty()) {
        centerOn(name);
        pendingCenterRef.current = null;
        return;
      }
    }
    pendingCenterRef.current = key; // 等引擎落定
  }, [centerOn]);

  // 选中左侧实体/社区点选 -> 视角转移到该节点（开局由下方 opening 逻辑处理 fit）
  useEffect(() => {
    if (centerOnName && hasOpenedRef.current) requestCenter(centerOnName);
  }, [centerOnName, requestCenter]);

  // 运行布局：force=fcose(有机防重叠) / cluster=concentric按类型环 / hierarchy=breadthfirst分层 /
  // radial=concentric按跳数环。4 种不同算法 -> 视觉差异明显（治"几个布局看不出区别"）。
  // 布局算一次即静止 -> 拖动只动该节点（治"拖动整图乱"）。
  const runLayout = useCallback((cy: Core, mode: LayoutMode, fresh: boolean) => {
    const myToken = ++layoutTokenRef.current;
    const onStop = () => {
      // 被更新的布局取代（如快速切模式/连续展开）时，旧布局的 stop 回调直接跳过，防错位 fit/center
      if (layoutTokenRef.current !== myToken) return;
      if (pendingFitRef.current) {
        pendingFitRef.current = false;
        cy.animate({ fit: { eles: cy.elements(), padding: 60 } }, { duration: 300 });
      } else if (pendingCenterRef.current) {
        const id = pendingCenterRef.current;
        pendingCenterRef.current = null;
        const n = cy.getElementById(id);
        if (!n.empty()) cy.animate({ center: { eles: n } }, { duration: 400 });
      }
    };
    let opts: LayoutOptions;
    if (mode === "force") {
      opts = {
        name: "fcose",
        animate: true,
        animationDuration: 500,
        randomize: fresh, // 切入/首次随机起；增量更新保留位置（不漂移）
        // 斥力/边长/间距取强值：demo 26 节点/hub 度 11 实测 overlapPairs=0（弱值 6000/90/45 下软斥力
        // 压不过边拉力 -> 节点重叠，强值根治）。numIter 默认 2500 保收敛，animate 仅过渡到已算定位置。
        nodeRepulsion: 30000,
        idealEdgeLength: 120,
        nodeSeparation: 60,
        packComponents: true,
        tile: true,
        tilingPaddingVertical: 40,
        tilingPaddingHorizontal: 40,
        nodeSepIncludingLabels: true,
        uniformNodeDimensions: true,
        stop: onStop,
      } as unknown as LayoutOptions;
    } else if (mode === "hierarchy") {
      const roots = cy.nodes().filter((n) => n.data("expanded") === 1).map((n) => n.id());
      opts = {
        name: "breadthfirst",
        directed: true,
        roots: roots.length ? roots : undefined,
        spacingFactor: 1.15,
        padding: 40,
        animate: true,
        animationDuration: 400,
        stop: onStop,
      } as unknown as LayoutOptions;
    } else {
      // cluster / radial -> concentric，按类型环 / 按跳数环
      const concentric =
        mode === "radial"
          ? (n: NodeSingular) => 100 - (typeof n.data("hop") === "number" ? (n.data("hop") as number) : 99)
          : (n: NodeSingular) => 100 - (TYPE_RANK[String(n.data("typeKey"))] ?? 99);
      opts = {
        name: "concentric",
        concentric,
        levelWidth: () => 1,
        minNodeSpacing: 30,
        padding: 40,
        animate: true,
        animationDuration: 400,
        stop: onStop,
      } as unknown as LayoutOptions;
    }
    // 停掉上一个布局（避免新旧布局动画并发互相覆盖 -> 切模式瞬间定格在旧布局）
    if (layoutApiRef.current) { try { layoutApiRef.current.stop(); } catch { /* noop */ } }
    const layout = cy.layout(opts);
    layoutApiRef.current = layout;
    layout.run();
  }, []);

  // 初始化 Cytoscape（容器就绪即建一次）。核心治本：布局算一次即静止，
  // 拖动只动该节点（d3-force 连续模拟才连锁 -> 拖一节点整图乱）。
  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      style: CY_STYLE,
      minZoom: 0.15,
      maxZoom: 4,
      // 倍率：原 0.25 过小需多次滚轮；提至 2（2x 默认）单次滚轮步进明显增大，操作省力
      wheelSensitivity: 2,
      autounselectify: true,
      boxSelectionEnabled: false,
    });
    cyRef.current = cy;
    if (import.meta.env.DEV) {
      // dev 调试钩子：经 window.__cy 程序化核验布局（重叠/拖动治本/布局差异），见验证闭环
      (window as unknown as { __cy?: Core }).__cy = cy;
    }
    // 低缩放隐藏边标签（降噪）；节点标签保留更久
    const onZoom = () => {
      const z = cy.zoom();
      cy.batch(() => {
        cy.edges().style("text-opacity", z > 1.3 ? 0.7 : 0);
        cy.nodes().style("text-opacity", z > 0.4 ? 1 : 0);
      });
    };
    cy.on("zoom", onZoom);
    onZoom();
    // 悬停高亮邻域：dim 其余 -> 稠密图可读性大幅提升
    let hovered: NodeSingular | null = null;
    cy.on("mouseover", "node", (evt) => {
      hovered = evt.target as NodeSingular;
      const nbhd = hovered.closedNeighborhood();
      cy.elements().not(nbhd).addClass("dim");
      hovered.addClass("hl");
      hovered.connectedEdges().addClass("hl");
    });
    cy.on("mouseout", "node", () => {
      if (hovered) { hovered.removeClass("hl"); hovered.connectedEdges().removeClass("hl"); hovered = null; }
      cy.elements().removeClass("dim");
    });
    // 节点点击：Shift=展开/收起 / Alt=设焦点 / 普通=看详情（Ctrl+单击也看详情，Ctrl 留给"单节点拖动"）
    cy.on("tap", "node", (evt) => {
      const node = evt.target as NodeSingular;
      const name = String(node.data("name"));
      const oe = evt.originalEvent as MouseEvent | undefined;
      if (oe?.altKey) {
        setFocusIds((prev) => {
          const next = hasName(prev, name)
            ? prev.filter((x) => normName(x) !== normName(name))
            : [...prev, name];
          if (next.length) requestCenter(next[next.length - 1]);
          return next;
        });
        return;
      }
      if (oe?.shiftKey) {
        const cur = seedsRef.current;
        const removing = hasName(cur, name);
        const next = removing
          ? cur.filter((x) => normName(x) !== normName(name))
          : [...cur, name];
        setSeeds(next);
        onSeedsChangeRef.current?.(next);
        if (!removing) pendingCenterRef.current = normName(name); // 展开后居中此节点
        return;
      }
      const raw = dataRef.current?.nodes.find((n) => normName(n.name) === normName(name));
      setSelected(raw ?? null);
    });
    // 拖动联动：Ctrl+拖 = 单节点拖（仅该节点跟手，整图不动）；普通拖 = 整连通分量刚性平移
    // （治"柔性联动(d3-force 连续模拟)拖一节点整图乱"：静态布局下刚性平移，无连锁形变）
    let dragComp: ReturnType<Core["elements"]> | null = null;
    let dragLast: { x: number; y: number } | null = null;
    cy.on("grab", "node", (evt) => {
      const n = evt.target as NodeSingular;
      dragLast = { x: n.position().x, y: n.position().y };
      // Ctrl+拖 -> 单节点拖：dragComp 置空，drag 时跳过 shift，仅该节点由 cytoscape 跟手
      const oe = evt.originalEvent as MouseEvent | undefined;
      if (oe?.ctrlKey) { dragComp = null; return; }
      const nid = n.id();
      // 找含此节点的连通分量（一次算定，drag 期间复用，避免每 tick 重算）
      const comp = cy.elements().components().find((c) => c.nodes().some((m) => (m as NodeSingular).id() === nid)) ?? null;
      dragComp = comp ? comp.not(n) : null;
    });
    cy.on("drag", "node", (evt) => {
      const n = evt.target as NodeSingular;
      const p = n.position();
      if (!dragLast) { dragLast = { x: p.x, y: p.y }; return; }
      const dx = p.x - dragLast.x;
      const dy = p.y - dragLast.y;
      dragLast = { x: p.x, y: p.y };
      if (dx === 0 && dy === 0) return;
      // 拖动节点已被 cytoscape 移到光标处；其余分量节点平移同 delta -> 整分量刚性平移，距离全保
      dragComp?.shift({ x: dx, y: dy });
    });
    cy.on("free", "node", () => { dragLast = null; dragComp = null; });
    // 容器尺寸变化 -> 同步画布（不 fit，保持视角）
    const ro = new ResizeObserver(() => { cy.resize(); });
    ro.observe(containerRef.current);
    return () => { ro.disconnect(); cy.destroy(); cyRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 开局（空 -> 非空）：首次非空时标记待 fit，由布局 stop 兜底 fit（保证充分展开后再框）
  useEffect(() => {
    if (!hasOpenedRef.current && nodeDefs.length > 0) {
      hasOpenedRef.current = true;
      pendingFitRef.current = true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeDefs.length > 0]);

  // 同步元素 + 按需重布局（仅结构变化或切模式才重布局；选中/焦点仅改数据不重布局 -> 不漂移）
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const wantIds = new Set(nodeDefs.map((n) => String(n.data.id)));
    // 删去已不可见节点
    cy.nodes().filter((n) => !wantIds.has(n.id())).remove();
    // 增加新节点（保留已有节点位置 -> 不漂移）
    const haveIds = new Set(cy.nodes().map((n) => n.id()));
    const toAdd = nodeDefs.filter((n) => !haveIds.has(String(n.data.id)));
    if (toAdd.length) cy.add(toAdd);
    // 更新所有可见节点数据/样式类（度数/焦点/已展开）
    for (const def of nodeDefs) {
      const id = String(def.data.id);
      const n = cy.getElementById(id);
      if (n.empty()) continue;
      n.data({
        color: def.data.color, size: def.data.size, degree: def.data.degree,
        hop: def.data.hop, expanded: def.data.expanded, focus: def.data.focus, type: def.data.type, typeKey: def.data.typeKey,
      });
      n.removeClass(ALL_TYPE_CLASSES.join(" ") + " expanded focus");
      if (Array.isArray(def.classes)) n.addClass(def.classes.join(" "));
    }
    // 边整体重建（边无需保位置，重建代价低且避免残留）
    cy.edges().remove();
    if (edgeDefs.length) cy.add(edgeDefs);
    // 新节点就近起始位置：cy.add 默认堆在原点 -> fcose randomize:false 从退化共线起点收敛成直线
    // 给新节点在已布局节点质心周围环形散布起始位置，治"展开塌成线"
    if (toAdd.length) {
      const newIdSet = new Set(toAdd.map((d) => String(d.data.id)));
      const placed = cy.nodes().filter((n) => !newIdSet.has(n.id()));
      let sx = 0, sy = 0;
      placed.forEach((n) => { const p = n.position(); sx += p.x; sy += p.y; });
      const bx = placed.length ? sx / placed.length : 0;
      const by = placed.length ? sy / placed.length : 0;
      const cnt = toAdd.length;
      cy.nodes().filter((n) => newIdSet.has(n.id())).forEach((n, i) => {
        const a = (i / Math.max(1, cnt)) * Math.PI * 2 + Math.random() * 0.6;
        const r = 30 + Math.random() * 50;
        n.position({ x: bx + Math.cos(a) * r, y: by + Math.sin(a) * r });
      });
    }

    const modeChanged = prevLayoutRef.current !== layoutMode;
    const structural = toAdd.length > 0 || wantIds.size !== prevNodeCountRef.current || modeChanged;
    prevNodeCountRef.current = wantIds.size;
    if (modeChanged) {
      // 离开旧模式前缓存当前节点位置（切回时恢复，避免"切去切回图形变化"）
      const prevCache = new Map<string, { x: number; y: number }>();
      cy.nodes().forEach((n) => { const p = n.position(); prevCache.set(n.id(), { x: p.x, y: p.y }); });
      modePositionsRef.current.set(prevLayoutRef.current, prevCache);
      firstLayoutRef.current = false;
      // 新模式有缓存且节点集一致 -> 恢复（不重布局）；否则跑布局
      const cached = modePositionsRef.current.get(layoutMode);
      const allCached = !!cached && cy.nodes().every((n) => cached.has((n as NodeSingular).id()));
      if (allCached && cached) {
        cy.nodes().forEach((n) => { const p = cached.get(n.id())!; n.position({ x: p.x, y: p.y }); });
        pendingFitRef.current = false;
        cy.animate({ fit: { eles: cy.elements(), padding: 60 } }, { duration: 200 });
      } else {
        pendingFitRef.current = true; // 切模式 -> 重框
        runLayout(cy, layoutMode, true);
      }
      prevLayoutRef.current = layoutMode;
    } else if (structural) {
      // 增量（展开/折叠）：保位置，fcose randomize:false 就近收敛；结构变化后清旧模式缓存（节点集已变）
      const fresh = firstLayoutRef.current;
      firstLayoutRef.current = false;
      modePositionsRef.current.clear();
      runLayout(cy, layoutMode, fresh);
      prevLayoutRef.current = layoutMode;
    }
    onNodesRef.current?.(nodeDefs.map((n) => String(n.data.name)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeDefs, edgeDefs, layoutMode, runLayout]);

  const fitAll = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.animate({ fit: { eles: cy.elements(), padding: 60 } }, { duration: 300 });
  }, []);

  const centerOnFocus = useCallback(() => {
    const target = focusIds.length ? focusIds[focusIds.length - 1] : seeds[0] ?? null;
    if (target) requestCenter(target);
  }, [focusIds, seeds, requestCenter]);

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
        <div className="flex items-center gap-1">
          {(["force", "cluster", "hierarchy", "radial"] as const).map((m) => (
            <Button key={m} type="button" size="sm" variant={layoutMode === m ? "default" : "outline"} onClick={() => setLayoutMode(m)} className="h-7 px-2 text-xs">
              {m === "force" ? "力导向" : m === "cluster" ? "聚类" : m === "hierarchy" ? "分层" : "径向"}
            </Button>
          ))}
        </div>
        <Button type="button" size="sm" variant="outline" onClick={fitAll} className="h-7 gap-1 px-2 text-xs">
          <Crosshair className="h-3 w-3" /> 居中全部
        </Button>
        <Button type="button" size="sm" variant={focusIds.length ? "default" : "outline"} onClick={centerOnFocus} className="h-7 gap-1 px-2 text-xs">
          <Star className="h-3 w-3" /> 居中焦点{focusIds.length ? `(${focusIds.length})` : ""}
        </Button>
        {data?.truncated && <Badge variant="outline" className="text-amber-600">已截断</Badge>}
        <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
          <Info className="h-3 w-3" /> 单击看详情；Shift+单击展开/收起；Alt+单击设焦点；Ctrl+拖动=单节点；普通拖动=整图联动；悬停高亮邻域
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
      <div className="entity-graph-host relative flex-1 overflow-hidden rounded-md border bg-muted/20">
        <div ref={containerRef} className="cy-container absolute inset-0" />
        {isFetching && nodeDefs.length === 0 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">加载子图…</div>
        )}
        {!isFetching && nodeDefs.length === 0 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">无可见子图（检查权限或勾选种子实体）</div>
        )}
      </div>
      {selected && (
        <div className="rounded-md border bg-card p-3 text-sm">
          <div className="mb-1 flex items-center gap-2">
            <span className="font-medium">{selected.name}</span>
            {selected.type && <Badge variant="secondary">{selected.type}</Badge>}
            <Badge variant="outline">{selected.access_level}</Badge>
            {hasName(seeds, selected.name) && <Badge variant="default">已展开</Badge>}
            {hasName(focusIds, selected.name) && <Badge className="bg-amber-500">焦点</Badge>}
          </div>
          <p className="text-muted-foreground">{selected.description}</p>
        </div>
      )}
    </div>
  );
}
