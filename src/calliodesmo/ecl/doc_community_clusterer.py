"""DocCommunityClusterer：独立文档嵌入聚类（选项 B，不依赖实体图）。

按 doc_id 聚合 chunk 取代表 -> ``EmbeddingProvider`` 嵌入 -> 阈值连通分量聚类
（相似度 >= 阈值连边 -> 连通分量即社区）-> 文档社区（``docc-`` 前缀，level=2）。

与实体社区（``comm-``，level=0）及选项 A 文档社区（``doc-``，level=1）id 空间隔离
（A1 修订：避免与选项 A ``doc-`` 撞 id）。v1 最简：连通分量聚类，不做层次/调参。

已知限制（B5）：连通分量有 chaining effect（A-B、B-C 过阈值 -> A/B/C 同簇但 A-C 可能不相似）
且无噪声点处理；簇内最低相似度写入 metadata 作质量信号；v2 可升级层次聚类/HDBSCAN。
"""

from __future__ import annotations

import math
from typing import Any

from calliodesmo.auth.context import AccessContext
from calliodesmo.ecl.cognify import _data_access_fields
from calliodesmo.interfaces.community_store import CommunityStore


class DocCommunityClusterer:
    def __init__(
        self,
        embedding_provider,
        community_store: CommunityStore | None = None,
        *,
        threshold: float = 0.7,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.community_store = community_store
        self.threshold = threshold

    async def derive(self, chunks: list, *, access: AccessContext) -> list:
        """对文档嵌入聚类，产出文档社区 CommunityRecord（docc- 前缀，level=2）。"""
        from calliodesmo.interfaces.community_store import CommunityRecord

        # 按 doc_id 聚合：取首 chunk content 作代表
        doc_repr: dict[str, str] = {}
        doc_access: dict[str, dict[str, Any]] = {}
        for c in chunks:
            if c.doc_id not in doc_repr:
                doc_repr[c.doc_id] = c.content
                doc_access[c.doc_id] = _access_from_chunk(c)
        doc_ids = sorted(doc_repr)
        if len(doc_ids) < 2:
            return []  # 单文档/无文档不聚类
        # 嵌入代表文本
        texts = [doc_repr[did] for did in doc_ids]
        emb = await self.embedding_provider.embed(texts)
        vectors = emb.vectors
        # 阈值连通分量聚类
        clusters = self._cluster(doc_ids, vectors)
        fields_default = _data_access_fields(access)
        records = []
        for idx, members in enumerate(clusters):
            access_fields = (
                doc_access.get(members[0], fields_default) if members else fields_default
            )
            min_sim = _min_intra_similarity(members, doc_ids, vectors)
            records.append(
                CommunityRecord(
                    community_id=f"docc-{idx}",
                    level=2,
                    title=(
                        members[0]
                        if len(members) == 1
                        else f"文档聚类 {idx}（{len(members)} 文档）"
                    ),
                    summary="；".join(members),
                    member_entity_names=list(members),
                    metadata={
                        "source": "doc_clustering",
                        "size": len(members),
                        "doc_ids": list(members),
                        "min_intra_similarity": min_sim,
                    },
                    **access_fields,
                )
            )
        if self.community_store is not None:
            await self.community_store.upsert_communities(records)
        return records

    def _cluster(self, doc_ids: list[str], vectors: list[list[float]]) -> list[list[str]]:
        """阈值连通分量：相似度 >= threshold 连边，连通分量即社区（DFS）。"""
        n = len(doc_ids)
        if n == 0:
            return []
        adj: list[set[int]] = [set() for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                if _cosine(vectors[i], vectors[j]) >= self.threshold:
                    adj[i].add(j)
                    adj[j].add(i)
        visited = [False] * n
        clusters: list[list[str]] = []
        for start in range(n):
            if visited[start]:
                continue
            stack = [start]
            comp: list[int] = []
            while stack:
                k = stack.pop()
                if visited[k]:
                    continue
                visited[k] = True
                comp.append(k)
                stack.extend(adj[k])
            comp.sort()
            clusters.append([doc_ids[i] for i in comp])
        clusters.sort(key=lambda c: c[0])  # 确定性排序
        return clusters


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _min_intra_similarity(
    members: list[str], doc_ids: list[str], vectors: list[list[float]]
) -> float | None:
    """簇内最低相似度（质量信号，B5）。单成员/无向量返回 None。"""
    if len(members) < 2:
        return None
    idx = {did: i for i, did in enumerate(doc_ids)}
    sims = []
    member_idx = [idx[m] for m in members if m in idx]
    for i in range(len(member_idx)):
        for j in range(i + 1, len(member_idx)):
            sims.append(_cosine(vectors[member_idx[i]], vectors[member_idx[j]]))
    return min(sims) if sims else None


def _access_from_chunk(chunk) -> dict[str, Any]:
    return {
        "access_level": chunk.access_level,
        "library_scope": chunk.library_scope,
        "owner_id": chunk.owner_id,
        "project_id": chunk.project_id,
        "team_id": chunk.team_id,
    }
