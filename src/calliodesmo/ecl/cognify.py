"""Cognify：建图 -> 实体消解 -> 社区检测 -> LLM 社区摘要。

- ``EntityRelationGraphBuilder``：实体->节点、关系->边，过滤自环/重复边
- ``NameEntityResolver``（一等公民）：名归一化 + 显式别名表合并 + 跨 chunk 描述汇总；
  合并时 ``template_conforming`` 取并集（任一 conforming 则合并后 conforming）
- ``LLMAliasResolver``（可选）：LLM 判别名/指代合并，未启用回退纯名归一化
- ``ConnectedComponentsDetector``（默认，零重依赖、确定性、按 name 排序可复现）
- ``NetworkxCommunityDetector``（extra graph-analytics）：缺依赖友好报错
- ``LLMCommunitySummarizer``：社区成员实体名+描述喂 LLM 生成 title+summary
- ``CognifyPipeline``：串联 build -> resolve -> detect -> summarize

图结构：``{"nodes": dict[str, GraphNode], "edges": list[GraphEdge]}``。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.interfaces.cognify import (
    Community,
    CommunityDetector,
    CommunitySummarizer,
    EntityResolver,
    GraphBuilder,
)
from calliodesmo.interfaces.extractor import ExtractionResult
from calliodesmo.interfaces.llm import LLMMessage, LLMProvider


@dataclass
class GraphNode:
    name: str
    type: str | None = None
    description: str = ""
    source_chunk_ids: list[str] = field(default_factory=list)
    template_conforming: bool = False


@dataclass
class GraphEdge:
    source: str
    target: str
    type: str | None = None
    description: str = ""
    source_chunk_ids: list[str] = field(default_factory=list)


def _data_access_fields(access: AccessContext) -> dict[str, Any]:
    """从 ingest AccessContext 派生数据的 access 字段（个人库默认）。"""
    team_id = next(iter(access.team_ids), None)
    project_id = next(iter(access.project_ids), None)
    if access.team_ids:
        scope = LibraryScope.TEAM
    elif access.project_ids:
        scope = LibraryScope.PROJECT
    else:
        scope = LibraryScope.PERSONAL
    return {
        "access_level": ClearanceLevel.INTERNAL,
        "library_scope": scope,
        "owner_id": access.user_id,
        "project_id": project_id,
        "team_id": team_id,
    }


# ============ 建图 ============


class EntityRelationGraphBuilder(GraphBuilder):
    def build(self, result: ExtractionResult) -> dict:
        nodes: dict[str, GraphNode] = {}
        for e in result.entities:
            if e.name not in nodes:
                nodes[e.name] = GraphNode(
                    name=e.name,
                    type=e.type,
                    description=e.description,
                    source_chunk_ids=list(e.source_chunk_ids),
                    template_conforming=e.template_conforming,
                )
            else:
                # 同名实体首次出现已建节点；合并 source_chunk_ids 与 conforming
                n = nodes[e.name]
                n.source_chunk_ids = list({*n.source_chunk_ids, *e.source_chunk_ids})
                n.template_conforming = n.template_conforming or e.template_conforming
        edges: list[GraphEdge] = []
        seen: set[tuple[str, str, str | None]] = set()
        for r in result.relations:
            if r.source == r.target:
                continue  # 过滤自环
            key = (r.source, r.target, r.type)
            if key in seen:
                continue  # 过滤重复边
            seen.add(key)
            edges.append(
                GraphEdge(
                    source=r.source,
                    target=r.target,
                    type=r.type,
                    description=r.description,
                    source_chunk_ids=list(r.source_chunk_ids),
                )
            )
        return {"nodes": nodes, "edges": edges}


# ============ 实体消解 ============


def _normalize(name: str) -> str:
    """名归一化：大小写/空白/尾部标点。"""
    s = name.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = s.rstrip(".,;:!?·、，。；：！？")
    return s.strip()


class NameEntityResolver(EntityResolver):
    def __init__(self, aliases: dict[str, list[str]] | None = None) -> None:
        # 别名表：canonical -> [alias,...]，构建反向映射 alias_normalized -> canonical_normalized
        self._alias_map: dict[str, str] = {}
        if aliases:
            for canonical, alist in aliases.items():
                c = _normalize(canonical)
                self._alias_map[c] = c
                for a in alist:
                    self._alias_map[_normalize(a)] = c

    def _canonical(self, name: str) -> str:
        norm = _normalize(name)
        return self._alias_map.get(norm, norm)

    def resolve(self, graph: dict) -> dict:
        nodes: dict[str, GraphNode] = graph["nodes"]
        edges: list[GraphEdge] = graph["edges"]

        merged: dict[str, GraphNode] = {}
        name_to_canonical: dict[str, str] = {}
        aliases: dict[str, list[str]] = {}
        for name, node in nodes.items():
            canon = self._canonical(name)
            name_to_canonical[name] = canon
            aliases.setdefault(canon, []).append(name)
            if canon in merged:
                tgt = merged[canon]
                tgt.source_chunk_ids = list({*tgt.source_chunk_ids, *node.source_chunk_ids})
                tgt.template_conforming = tgt.template_conforming or node.template_conforming
                # 描述汇总：去重保序拼接
                if node.description and node.description not in tgt.description:
                    tgt.description = (tgt.description + "\n" + node.description).strip()
                if tgt.type is None and node.type is not None:
                    tgt.type = node.type
            else:
                merged[canon] = GraphNode(
                    name=canon,
                    type=node.type,
                    description=node.description,
                    source_chunk_ids=list(node.source_chunk_ids),
                    template_conforming=node.template_conforming,
                )

        # 边重映射到 canonical，过滤消解后自环/重复
        new_edges: list[GraphEdge] = []
        seen: set[tuple[str, str, str | None]] = set()
        for e in edges:
            src = name_to_canonical.get(e.source, self._canonical(e.source))
            tgt = name_to_canonical.get(e.target, self._canonical(e.target))
            if src == tgt:
                continue
            key = (src, tgt, e.type)
            if key in seen:
                continue
            seen.add(key)
            new_edges.append(
                GraphEdge(
                    source=src,
                    target=tgt,
                    type=e.type,
                    description=e.description,
                    source_chunk_ids=list(e.source_chunk_ids),
                )
            )
        return {"nodes": merged, "edges": new_edges, "aliases": aliases}


class LLMAliasResolver(EntityResolver):
    """可选：LLM 判别名/指代合并；未启用（无 LLM）时回退纯名归一化。"""

    def __init__(self, llm: LLMProvider, fallback: NameEntityResolver | None = None) -> None:
        self.llm = llm
        self.fallback = fallback or NameEntityResolver()

    async def resolve_async(self, graph: dict) -> dict:
        names = sorted(graph["nodes"])
        if len(names) < 2:
            return self.fallback.resolve(graph)
        system = (
            "你是实体消解引擎。给定实体名列表，输出别名/指代合并映射 JSON："
            '{"groups":[["canonical","alias1","alias2"],...]}。仅合并确属同一实体者。'
        )
        user = "实体列表：\n" + "\n".join(names)
        resp = await self.llm.complete([LLMMessage("system", system), LLMMessage("user", user)])
        aliases: dict[str, list[str]] = {}
        try:
            data = json.loads(resp.content)
            for group in data.get("groups", []):
                if len(group) >= 2:
                    aliases[group[0]] = list(group[1:])
        except (json.JSONDecodeError, AttributeError):
            pass
        resolver = NameEntityResolver(aliases) if aliases else self.fallback
        return resolver.resolve(graph)

    def resolve(self, graph: dict) -> dict:
        # 同步接口回退到纯名归一化（LLM 路径走 resolve_async）
        return self.fallback.resolve(graph)


# ============ 社区检测 ============


class ConnectedComponentsDetector(CommunityDetector):
    """零重依赖、确定性：连通分量，按 name 排序可复现。"""

    def detect(self, graph: dict, *, access: AccessContext) -> list[Community]:
        nodes: dict[str, GraphNode] = graph["nodes"]
        edges: list[GraphEdge] = graph["edges"]
        adj: dict[str, set[str]] = {n: set() for n in nodes}
        for e in edges:
            if e.source in adj and e.target in adj:
                adj[e.source].add(e.target)
                adj[e.target].add(e.source)

        visited: set[str] = set()
        components: list[list[str]] = []
        for start in sorted(nodes):
            if start in visited:
                continue
            stack = [start]
            comp: list[str] = []
            while stack:
                n = stack.pop()
                if n in visited:
                    continue
                visited.add(n)
                comp.append(n)
                stack.extend(sorted(adj[n]))
            components.append(sorted(comp))

        components.sort(key=lambda c: c[0])  # 确定性排序
        fields = _data_access_fields(access)
        communities: list[Community] = []
        for idx, comp in enumerate(components):
            communities.append(
                Community(
                    community_id=f"comm-{idx}",
                    level=0,
                    title=comp[0] if len(comp) == 1 else f"{comp[0]} 等 {len(comp)} 实体",
                    summary="",
                    member_entity_names=comp,
                    metadata={"size": len(comp)},
                    **fields,
                )
            )
        return communities


class NetworkxCommunityDetector(CommunityDetector):
    """可选（extra graph-analytics）：缺依赖友好报错。"""

    def detect(self, graph: dict, *, access: AccessContext) -> list[Community]:
        try:
            import networkx as nx
        except ImportError as exc:
            raise RuntimeError("社区检测需 networkx：uv sync --extra graph-analytics") from exc
        import networkx as nx

        nodes: dict[str, GraphNode] = graph["nodes"]
        g = nx.Graph()
        for name in nodes:
            g.add_node(name)
        for e in graph["edges"]:
            if e.source in nodes and e.target in nodes:
                g.add_edge(e.source, e.target)
        fields = _data_access_fields(access)
        communities: list[Community] = []
        for idx, comp in enumerate(sorted(nx.connected_components(g), key=lambda c: sorted(c)[0])):
            members = sorted(comp)
            communities.append(
                Community(
                    community_id=f"comm-{idx}",
                    level=0,
                    title=members[0]
                    if len(members) == 1
                    else f"{members[0]} 等 {len(members)} 实体",
                    summary="",
                    member_entity_names=members,
                    metadata={"size": len(members)},
                    **fields,
                )
            )
        return communities


# ============ 社区摘要 ============


class LLMCommunitySummarizer(CommunitySummarizer):
    def __init__(self, llm: LLMProvider, *, temperature: float = 0.2) -> None:
        self.llm = llm
        self.temperature = temperature

    async def summarize(self, communities: list[Community], graph: dict) -> list[Community]:
        nodes: dict[str, GraphNode] = graph["nodes"]
        for comm in communities:
            members = [nodes[n] for n in comm.member_entity_names if n in nodes]
            if not members:
                comm.title = comm.title or "空社区"
                comm.summary = "（无成员实体）"
                continue
            listing = "\n".join(
                f"- {m.name}（{m.type or '未知'}）: {m.description}" for m in members
            )
            messages = [
                LLMMessage(
                    "system",
                    "你是社区摘要引擎。为给定实体集合生成简短 title 与 summary。"
                    '严格只输出 JSON：{"title":"...","summary":"..."}',
                ),
                LLMMessage("user", f"社区成员：\n{listing}"),
            ]
            resp = await self.llm.complete(messages, temperature=self.temperature)
            title, summary = self._parse(resp.content)
            comm.title = title or comm.title
            comm.summary = summary or ""
        return communities

    @staticmethod
    def _parse(content: str) -> tuple[str, str]:
        try:
            data = json.loads(content.strip().strip("`"))
            if isinstance(data, dict):
                return str(data.get("title", "")), str(data.get("summary", ""))
        except (json.JSONDecodeError, AttributeError):
            pass
        return "", ""


# ============ 串联管线 ============


class CognifyPipeline:
    """build -> resolve -> detect -> summarize。"""

    def __init__(
        self,
        *,
        builder: GraphBuilder | None = None,
        resolver: EntityResolver | None = None,
        detector: CommunityDetector | None = None,
        summarizer: CommunitySummarizer | None = None,
    ) -> None:
        self.builder = builder or EntityRelationGraphBuilder()
        self.resolver = resolver or NameEntityResolver()
        self.detector = detector or ConnectedComponentsDetector()
        self.summarizer = summarizer

    async def run(
        self, result: ExtractionResult, *, access: AccessContext
    ) -> tuple[list[Community], dict]:
        graph = self.builder.build(result)
        graph = self.resolver.resolve(graph)
        communities = self.detector.detect(graph, access=access)
        if self.summarizer is not None:
            communities = await self.summarizer.summarize(communities, graph)
        return communities, graph
