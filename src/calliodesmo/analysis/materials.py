"""材料采集器：全量拉取 + ``visible_to`` 红线 + ``doc_ids`` 成员筛选 + 双闸截断 + 图谱复用。

P6 Task 9。把「提交参数 → 可见材料 + 源文映射 + 可选图谱上下文」收敛为一个可单测
的采集器（``gather_materials``），worker（Task 13）负责调用，引擎（Task 10）只吃
已过滤材料——保引擎纯逻辑可测。

**两条安全红线**（测试先行，``tests/test_analysis_materials.py`` 锁定）：

- **红线一**：禁止凭客户端传入的 ``chunk_id`` / ``doc_id`` 直取材料（枚举越权面）。
  ``doc_ids`` 仅作成员筛选，每条记录仍过 ``visible_to`` 二次复核（提交后权限变化的
  二次把关）；不可见 / 不存在的 ID 静默剔除，不抛错、不泄漏存在性细节。
- **红线二**：材料获取不依赖内存态 ``sparse_index`` / BM25——跨进程为空
  （P4.5 遗留，``api/deps.py`` TODO 顺延 P9，2026-W49）；采集只走
  ``VectorStore.list_chunks``（真后端落 PG 亦可读）。

**留痕**：三 store list 方法（``list_chunks`` / ``list_entities`` / ``list_relations``）
无谓词下推（按 ``doc_ids`` 过滤），P6 以全量拉取 + ``visible_to`` 内存过滤 +
``analysis_max_chunks`` / ``analysis_max_input_chars`` 双闸截断兜底；大规模谓词下推
优化 → P9（2026-W49，与 ``api/deps.py`` ProfileCard/BM25 改 PG 同批）。

**图谱复用**：实体识别 / 关系映射类另读 ``graph_store`` 实体与关系（经
``visible_to``，只纳入与最终材料块相交者）作图谱上下文，由 ``fold_graph_context``
折入材料（序列化为追加伪块）后进引擎，LLM 只组织、不重新抽取。

``AnalysisMaterial`` 为引擎侧材料形态；``interfaces/analysis.py``（Task 10，
2026-W39）re-export 本 dataclass，不重复定义（与 ``schemas.AnalysisType`` 先例一致）。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace

from calliodesmo.analysis.prompts import (
    DEFAULT_MAX_CHUNKS,
    DEFAULT_MAX_INPUT_CHARS,
    _select_materials,
)
from calliodesmo.analysis.schemas import AnalysisType
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.interfaces.graph_store import EntityRecord, GraphStore, RelationRecord
from calliodesmo.interfaces.vector_store import ChunkRecord, VectorStore
from calliodesmo.stores.visibility import visible_to

#: 需图谱上下文的分析类型（实体识别 / 关系映射；经图谱复用，LLM 只组织不重新抽取）
GRAPH_CONTEXT_TYPES: frozenset[AnalysisType] = frozenset(
    {AnalysisType.ENTITY_RECOGNITION, AnalysisType.RELATION_MAPPING}
)

#: 图谱上下文伪材料块的 chunk_id（``fold_graph_context`` 折入标记）。关系映射等图谱
#: 复用类型把 ``gather_materials`` 采集的实体 / 关系序列化为一条追加的伪材料块，
#: 使模板渲染（``{materials}``）天然携带图谱数据——非真实落库块，仅提示词装配用。
GRAPH_CONTEXT_CHUNK_ID = "graph-context"


@dataclass(frozen=True)
class AnalysisMaterial:
    """分析材料：可见材料块 + 展示标签 + access 字段（密级继承计算的输入）。

    ``text`` 为实际进入提示词的文本（双闸截断后可能被裁剪）；``source_label`` 为
    文档标题 / 来源（展示用，取 metadata title -> source_path -> doc_id 回退）。
    """

    chunk_id: str
    doc_id: str
    source_label: str  # 文档标题/来源（展示用）
    text: str
    access_level: ClearanceLevel  # 继承自源材料（密级继承计算的输入）
    library_scope: LibraryScope
    owner_id: uuid.UUID | None


@dataclass(frozen=True)
class GatheredMaterials:
    """采集结果：排序截断后的材料 + 源文映射 + 可选图谱上下文 + 截断标记。

    - ``source_texts``：``chunk_id -> 源文`` 映射，供 ``evidence.verify_evidence``
      证据引文子串校验消费（与材料 ``text`` 一致，截断后同裁）；
    - ``entities`` / ``relations``：仅 ``GRAPH_CONTEXT_TYPES`` 类型非空（经
      ``visible_to`` 且与最终材料块相交）；
    - ``truncated``：任一闸（块数 / 字符）触发裁剪或丢弃时为 True（供告警展示）。
    """

    materials: tuple[AnalysisMaterial, ...]
    source_texts: dict[str, str]
    entities: tuple[EntityRecord, ...]
    relations: tuple[RelationRecord, ...]
    truncated: bool


def _source_label(record: ChunkRecord) -> str:
    """文档标题 / 来源（展示用）：metadata title -> source_path -> doc_id 回退。

    与 Task 14 ``GET /analysis/documents`` 的 label 约定一致（取 metadata 标题或
    回退 doc_id）；``source_path`` 为加载器落库的中间回退档。
    """
    meta = record.metadata or {}
    title = meta.get("title")
    if isinstance(title, str) and title.strip():
        return title
    source_path = meta.get("source_path")
    if isinstance(source_path, str) and source_path.strip():
        return source_path
    return record.doc_id


def _chunk_ordinal(chunk_id: str) -> tuple[int, int, str]:
    """块序排序键：``<doc>#<ordinal>`` 约定的序号按数值排（#2 先于 #10）。

    无法解析序号的块落 (1, 0, chunk_id) 档，排在可解析者之后、内部按字典序。
    """
    _, _, suffix = chunk_id.rpartition("#")
    if suffix.isdigit():
        return (0, int(suffix), chunk_id)
    return (1, 0, chunk_id)


async def gather_materials(
    *,
    vector_store: VectorStore,
    access: AccessContext,
    task_type: AnalysisType | str = AnalysisType.SUMMARY,
    doc_ids: Sequence[str] | None = None,
    graph_store: GraphStore | None = None,
    max_chunks: int | None = None,
    max_input_chars: int | None = None,
) -> GatheredMaterials:
    """采集可见分析材料（红线见模块 docstring；纯读不写、可单测）。

    流程：``list_chunks`` 全量拉取（store 侧 ``visible_to`` 过滤）→ ``visible_to``
    逐条二次复核 → ``doc_ids`` 成员筛选（仅筛选、不豁免可见性；不可见 / 不存在者
    静默剔除）→ 按文档序 / 块序排序 → 双闸截断 → ``AnalysisMaterial`` 列表；
    实体识别 / 关系映射类另读图谱上下文。

    参数:
        vector_store: 情景层向量库（``list_chunks`` 路径，不经内存态 BM25）。
        access: 提交者权限上下文（全程 ``visible_to`` 过滤依据）。
        task_type: 分析类型（接受枚举或字符串值，非法值抛 ``ValueError``）；
            ``GRAPH_CONTEXT_TYPES`` 类型附带图谱上下文。
        doc_ids: 成员筛选集合；``None`` 或空 = 全可见范围（API 默认空列表不变成
            零材料）。**仅作成员筛选，不豁免可见性校验（红线一）**。
        graph_store: 图库；``GRAPH_CONTEXT_TYPES`` 类型且传入时读图谱上下文，
            缺省时优雅降级为空（不阻塞材料采集）。
        max_chunks / max_input_chars: 双闸预算；``None`` = 用默认值（镜像
            ``config.py`` ``analysis_max_chunks`` / ``analysis_max_input_chars``，
            引擎 / worker 侧经 settings 显式传入）。

    返回:
        ``GatheredMaterials``；材料为空时返回空元组（由 worker 拦为
        「无可见材料」失败，Task 13），本函数不抛错。
    """
    t = AnalysisType(task_type)
    chunk_limit = DEFAULT_MAX_CHUNKS if max_chunks is None else max_chunks
    char_limit = DEFAULT_MAX_INPUT_CHARS if max_input_chars is None else max_input_chars

    # 1) 全量拉取 + visible_to 逐条二次复核（红线一：不凭客户端 ID 直取）
    chunks = [c for c in await vector_store.list_chunks(access=access) if visible_to(c, access)]

    # 2) doc_ids 成员筛选（仅筛选、不豁免；不可见 / 不存在者静默剔除，防枚举探测）
    wanted = set(doc_ids) if doc_ids else None
    if wanted is not None:
        chunks = [c for c in chunks if c.doc_id in wanted]

    # 3) 排序：文档序（提交序；未提交时 doc_id 字典序）/ 块序（# 后序号数值序）
    doc_order: dict[str, int] = {}
    if wanted is not None:
        for doc_id in doc_ids or ():
            if doc_id not in doc_order:
                doc_order[doc_id] = len(doc_order)
    else:
        for doc_id in sorted({c.doc_id for c in chunks}):
            doc_order[doc_id] = len(doc_order)
    chunks.sort(
        key=lambda c: (doc_order.get(c.doc_id, len(doc_order)), *_chunk_ordinal(c.chunk_id))
    )

    # 4) 装配材料（携带 access_level，密级继承计算的输入）
    materials = [
        AnalysisMaterial(
            chunk_id=c.chunk_id,
            doc_id=c.doc_id,
            source_label=_source_label(c),
            text=c.content,
            access_level=c.access_level,
            library_scope=c.library_scope,
            owner_id=c.owner_id,
        )
        for c in chunks
    ]

    # 5) 双闸截断（与渲染侧 prompts._select_materials 同一实现，口径恒一致；
    #    渲染侧预算为兜底，见 prompts.py 模块注记）
    original_texts = {m.chunk_id: m.text for m in materials}
    selected = dict(_select_materials(materials, chunk_limit, char_limit))
    kept = [replace(m, text=selected[m.chunk_id]) for m in materials if m.chunk_id in selected]
    truncated = len(kept) < len(materials) or any(
        m.text != original_texts[m.chunk_id] for m in kept
    )

    # 6) 图谱上下文（实体识别 / 关系映射；经 visible_to，只纳与最终材料块相交者）
    entities: tuple[EntityRecord, ...] = ()
    relations: tuple[RelationRecord, ...] = ()
    if t in GRAPH_CONTEXT_TYPES and graph_store is not None:
        material_chunk_ids = {m.chunk_id for m in kept}
        entities = tuple(
            sorted(
                (
                    e
                    for e in await graph_store.list_entities(access=access)
                    if visible_to(e, access)
                    and any(cid in material_chunk_ids for cid in e.source_chunk_ids)
                ),
                key=lambda e: e.name,
            )
        )
        relations = tuple(
            sorted(
                (
                    r
                    for r in await graph_store.list_relations(access=access)
                    if visible_to(r, access)
                    and any(cid in material_chunk_ids for cid in r.source_chunk_ids)
                ),
                key=lambda r: (r.source, r.target, r.type or ""),
            )
        )

    return GatheredMaterials(
        materials=tuple(kept),
        source_texts={m.chunk_id: m.text for m in kept},
        entities=entities,
        relations=relations,
        truncated=truncated,
    )


def format_graph_context(
    entities: Sequence[EntityRecord], relations: Sequence[RelationRecord]
) -> str:
    """把图谱实体 / 关系序列化为确定性文本块（字段内容原样复用，不重新抽取）。

    段落标记固定（``【图谱上下文 · 实体】`` / ``【图谱上下文 · 关系】``），空段不渲染；
    每条实体 / 关系以 ``- `` 起行，非空字段以「 | 」分隔（空类型 / 空描述不落空值段）。
    供 ``fold_graph_context`` 折入材料，关系映射等图谱复用类型的提示词装配消费。
    """
    lines: list[str] = []
    if entities:
        lines.append("【图谱上下文 · 实体】")
        for e in entities:
            parts = [f"实体：{e.name}"]
            if e.type:
                parts.append(f"类型：{e.type}")
            if e.description:
                parts.append(f"描述：{e.description}")
            lines.append("- " + " | ".join(parts))
    if relations:
        lines.append("【图谱上下文 · 关系】")
        for r in relations:
            parts = [f"关系：{r.source} -> {r.target}"]
            if r.type:
                parts.append(f"类型：{r.type}")
            if r.description:
                parts.append(f"描述：{r.description}")
            lines.append("- " + " | ".join(parts))
    return "\n".join(lines)


def fold_graph_context(gathered: GatheredMaterials) -> tuple[AnalysisMaterial, ...]:
    """图谱上下文折入材料：实体 / 关系序列化为追加伪材料块后返回（否则原样返回）。

    关系映射等图谱复用类型（``GRAPH_CONTEXT_TYPES``）经 ``gather_materials`` 采集
    图谱实体 / 关系后，由本函数折入材料末尾（``GRAPH_CONTEXT_CHUNK_ID`` 伪块），
    引擎（``analysis/engine.py``）经统一的 ``{materials}`` 渲染消费——**保引擎纯逻辑，
    不读 ``graph_store``**；LLM 只组织、不重新抽取。密级继承与块计数仍只认真材料块
    （``compute_report_access_level`` / ``source_chunk_count`` 消费 ``gathered.materials``，
    不含伪块）；伪块 ``access_level`` 取实体 / 关系各级最大值（保守方向，仅升不降）。
    """
    if not gathered.entities and not gathered.relations:
        return gathered.materials
    levels = [e.access_level for e in gathered.entities] + [
        r.access_level for r in gathered.relations
    ]
    pseudo = AnalysisMaterial(
        chunk_id=GRAPH_CONTEXT_CHUNK_ID,
        doc_id=GRAPH_CONTEXT_CHUNK_ID,
        source_label="图谱上下文",
        text=format_graph_context(gathered.entities, gathered.relations),
        access_level=max(levels) if levels else ClearanceLevel.INTERNAL,
        library_scope=LibraryScope.PERSONAL,
        owner_id=None,
    )
    return (*gathered.materials, pseudo)


__all__ = [
    "GRAPH_CONTEXT_CHUNK_ID",
    "GRAPH_CONTEXT_TYPES",
    "AnalysisMaterial",
    "GatheredMaterials",
    "fold_graph_context",
    "format_graph_context",
    "gather_materials",
]
