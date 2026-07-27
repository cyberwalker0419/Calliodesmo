"""RRF 倒数秩融合：按各路 rank 累加 1/(k+rank)，同 chunk_id 跨路合并。

经典 RRF 公式：score = sum(1/(k + rank_i))，k=60。
融合基于秩而非原始分数（各路分数量纲不同），更稳健。
"""

from __future__ import annotations

from calliodesmo.interfaces.retriever import Candidate


def rrf(
    candidates_by_lane: dict[str, list[Candidate]], *, k: int = 60, top_k: int
) -> list[Candidate]:
    """倒数秩融合：按各路 rank 累加 1/(k+rank)，同 chunk_id 跨路合并。

    输入：lane -> 已赋 rank（1-based）的候选列表。
    输出：按融合分降序、top_k 截断；平局按 chunk_id 确定性排序。
    """
    # chunk_id -> (fusion_score, first_candidate, source_set)
    merged: dict[str, dict] = {}
    for lane, candidates in candidates_by_lane.items():
        for c in candidates:
            if c.chunk_id not in merged:
                merged[c.chunk_id] = {
                    "score": 0.0,
                    "candidate": c,
                    "sources": [],
                }
            entry = merged[c.chunk_id]
            rank = c.rank if c.rank is not None else 1
            entry["score"] += 1.0 / (k + rank)
            entry["sources"].append(lane)
            # 保留首次出现的候选作为基座（content/doc_id/metadata 来源）
            # 但更新 source 为所有命中的 lane

    result: list[Candidate] = []
    for chunk_id, entry in merged.items():
        base = entry["candidate"]
        result.append(
            Candidate(
                chunk_id=chunk_id,
                doc_id=base.doc_id,
                content=base.content,
                score=round(entry["score"], 6),
                metadata=dict(base.metadata),
                source="+".join(sorted(set(entry["sources"]))),
            )
        )

    # 融合分降序，平局按 chunk_id 升序（确定性）
    result.sort(key=lambda c: (-c.score, c.chunk_id))
    result = result[:top_k]
    for i, c in enumerate(result, 1):
        c.rank = i
    return result
