"""实体对齐：embedding 三段式相似度判定 + 推送重叠候选对收集（P4.5 Task 6）。

v1 实现约束（与本项目对齐）：
- **直接消费嵌入 provider 已有向量**（``scores`` 多目标成对算 cosine），不走
  ``embedding.embed`` 接口再算一遍——与别名嵌入服务（``remote_embedding``）在线一致；
  离线 hash 桩亦一致。
- 阈值经 config（``alignment_auto_merge_threshold`` / ``alignment_review_threshold``）
  可调，默认 0.95 / 0.85；type blocking（``type`` 精确一致候选、类型不同降级 new）。
- 决策四态：``auto_merged``（>=0.95）/ ``review_pending``（0.85-0.95，进复核队列）/
  ``new``（<0.85 新节点）/ ``type_blocked``（type 不同降级）。
- **未接入 org 的向量集中物化**：候选对向量由合并方（MergeService，纯函数）在内存
  预取，本模块只算相似度；候选对的 ``pair_id`` 稳定（缩小 scope 时合并入库仍幂等）。
- BGE-M3 模式同构：description+名称逐条嵌入（与 chunk 同维度），阈值同为余弦相似度。
"""

from __future__ import annotations

from dataclasses import dataclass

from calliodesmo.interfaces.graph_store import EntityRecord

AUTO_MERGE_THRESHOLD: float = 0.95
REVIEW_THRESHOLD: float = 0.85


def _cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度（向量已归一化则等价于点积；未归一化亦正确）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5 or 1.0
    norm_b = sum(y * y for y in b) ** 0.5 or 1.0
    return dot / (norm_a * norm_b)


@dataclass
class AlignmentResult:
    """单对对齐判定结果。"""

    score: float
    decision: str  # auto_merged | review_pending | new | type_blocked
    type_blocked: bool = False


async def score_alignment(
    source: EntityRecord,
    target: EntityRecord,
    *,
    vectors: dict[str, list[float]],
    auto_merge_threshold: float = AUTO_MERGE_THRESHOLD,
    review_threshold: float = REVIEW_THRESHOLD,
) -> AlignmentResult:
    """单对实体对齐判定：name+description 向量余弦 + type blocking 阈值路由。

    - source/target ``type`` 不同 -> type_blocked（decision=new，v1 不合并）
    - 同 type：score >= auto_merge 自动合并；review ~ auto_merge 进复核；
      其余新节点。向量以实体 name 为键传入（调用方已物化）。
    """
    if (source.type or "") != (target.type or ""):
        return AlignmentResult(score=0.0, decision="new", type_blocked=True)
    sv = vectors.get(source.name)
    tv = vectors.get(target.name)
    score = _cosine(sv or [], tv or []) if (sv and tv) else 0.0
    if score >= auto_merge_threshold:
        decision = "auto_merged"
    elif score >= review_threshold:
        decision = "review_pending"
    else:
        decision = "new"
    return AlignmentResult(score=score, decision=decision, type_blocked=False)


@dataclass
class AlignmentPair:
    """待审对齐候选对（供人工复核）。"""

    pair_id: str
    source_name: str
    target_name: str
    score: float
    type: str | None = None
    source_type: str | None = None
    target_type: str | None = None
    source_description: str = ""
    target_description: str = ""


@dataclass
class TypeBlockedPair:
    """type blocking 拦截对（同名不同类型，v1 不合并）。"""

    source_name: str
    target_name: str
    source_type: str | None = None
    target_type: str | None = None


def _pair_id(source_name: str, target_name: str) -> str:
    """稳定 pair_id（不依赖随机数，review 幂等与去重可用）。"""
    import hashlib

    return hashlib.sha1(f"{source_name}|{target_name}".encode()).hexdigest()[:16]


async def compute_overlap_embedding(
    source_entities: list[EntityRecord],
    target_entities: list[EntityRecord],
    *,
    vectors: dict[str, list[float]],
    auto_merge_threshold: float = AUTO_MERGE_THRESHOLD,
    review_threshold: float = REVIEW_THRESHOLD,
) -> tuple[list[AlignmentPair], list[TypeBlockedPair]]:
    """推送重叠候选对收集：源实体 vs 目标实体逐对按 type blocking + 三段式判定。

    - 同名同 type 且相似 >= review -> 候选对（含 score/source/target 描述）
    - 同名不同类型 -> ``type_blocked`` 列表（v1 不合并，冲突留痕）
    - 其余（低相似 / 同 type 但距新）不收集——``merge_entities`` 仍按 name 精确合并
      （store name 唯一），对齐是重叠优化而非新合并路径。
    """
    pairs: list[AlignmentPair] = []
    type_blocked: list[TypeBlockedPair] = []
    for src in source_entities:
        for tgt in target_entities:
            if (src.name == tgt.name) and (src.type or "") != (tgt.type or ""):
                type_blocked.append(
                    TypeBlockedPair(
                        source_name=src.name,
                        target_name=tgt.name,
                        source_type=src.type,
                        target_type=tgt.type,
                    )
                )
                continue
            if (src.type or "") != (tgt.type or ""):
                continue
            sv = vectors.get(src.name)
            tv = vectors.get(tgt.name)
            if not sv or not tv:
                continue
            score = _cosine(sv, tv)
            if score >= review_threshold:
                pairs.append(
                    AlignmentPair(
                        pair_id=_pair_id(src.name, tgt.name),
                        source_name=src.name,
                        target_name=tgt.name,
                        score=round(score, 4),
                        type=src.type,
                        source_type=src.type,
                        target_type=tgt.type,
                        source_description=src.description,
                        target_description=tgt.description,
                    )
                )
    return pairs, type_blocked
