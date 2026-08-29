"""P6 分析质量 golden 回归：九类分析引擎 × 字段/元组级 F1 × G-Eval judge（P6 Task 17）。

在内存 stores 上灌入 data/demo 语料，对 config/golden_analysis.yaml 逐例跑
``AnalysisEvalHarness``（采集 → 引擎 → 确定性指标 + judge），输出控制台明细表 +
落盘 docs/verification/p6-regression.json（与 p5-regression.json 同级）。

默认**全离线确定性**（StubLLM + Hash 嵌入，零网络、可复现），与 CI 同纪律；
设 --real 才按 .env 接真实模型（本地有 LLM/嵌入服务时用）。

**离线证据≠质量证据**：桩对生成质量零区分度（固定分析输出 + 固定 judge 分），
离线基线只承诺结构 / 契约（状态机 / 报告 schema / 指标管线连通），不得表述为
「分析质量好」；质量证据仅由 ``--real`` 承担（用户本机，锚点 2026-W45，与
``scripts/eval_p5.py --real`` 同批；延误顺延 2026-W46）。

用法：
    uv run python scripts/eval_p6.py --dump-golden   # 只灌库并打印 chunk 骨架（建 golden 用）
    uv run python scripts/eval_p6.py                 # 跑分析回归并落盘（离线桩）
    uv run python scripts/eval_p6.py --real          # 接真实模型（缺 key 友好报错）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from calliodesmo.analysis.factory import build_analysis_engine
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.config import Settings, get_settings
from calliodesmo.ecl.engine import build_default_indexing_engine
from calliodesmo.eval.golden_analysis import load_golden_analysis
from calliodesmo.eval.harness import AnalysisEvalHarness
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
from calliodesmo.retrieval.factory import build_default_search_engine, build_llm_provider
from calliodesmo.retrieval.in_memory_sparse_index import InMemoryBM25Index

DEMO_DIR = "data/demo"
GOLDEN_FILE = "config/golden_analysis.yaml"
OUT_FILE = Path("docs/verification/p6-regression.json")
USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

#: 离线证据警示语（随控制台与证据文件一并留痕；口径见模块 docstring 与计划「验收口径」）
OFFLINE_DISCLAIMER = (
    "离线证据≠质量证据：桩对生成质量零区分度（固定分析输出 + 固定 judge 分），"
    "本基线只承诺结构 / 契约；质量证据由 eval_p6.py --real 承担（锚点 2026-W45，用户本机）。"
)
REAL_DISCLAIMER = (
    "质量证据运行（真实模型）：字段 / 元组级 P-R-F1 与 G-Eval judge 为质量参考分；"
    "结论入验证报告须与离线结构证据（p6-regression.json）并列。"
)

#: 与 scripts/eval_p5.py 同口径：CLI ingest 写 demo 的记录 owner_id 为 None（系统语义）；
#: 评估视角 user_id=None，使 visible_to 对 PERSONAL 记录恒命中（None == None）。
ACCESS = AccessContext(
    user_id=None,
    username="admin",
    clearance=ClearanceLevel.SECRET,
    permissions=frozenset(p.value for p in Permission),
    library_scopes=frozenset(s.value for s in LibraryScope),
)


def eval_settings(real: bool) -> Settings:
    """评估 settings：默认离线桩（确定性），--real 走 .env 真实模型。"""
    if real:
        return get_settings()
    return Settings(
        llm_model="test/stub-eval",
        embedding_provider="hash",
        embedding_dimension=64,
        reranker_provider="none",
        chunk_summary_enabled=False,
        _env_file=None,
    )


def make_stores() -> dict:
    return {
        "vector_store": InMemoryVectorStore(),
        "graph_store": InMemoryGraphStore(),
        "community_store": InMemoryCommunityStore(),
    }


async def ingest_demo(real: bool):
    """灌库，返回 (stores, {chunk_id: (doc_id, snippet)})。"""
    stores = make_stores()
    engine = build_default_indexing_engine(eval_settings(real), **stores)
    stats = await engine.ingest(DEMO_DIR, access=ACCESS)
    chunks = await stores["vector_store"].list_chunks(access=ACCESS)
    mapping = {}
    for c in sorted(chunks, key=lambda x: x.chunk_id):
        mapping[c.chunk_id] = (c.doc_id, c.content[:70].replace(chr(10), " "))
    return stores, mapping, stats


def build_engines(stores: dict, real: bool):
    """装配分析引擎（QA 类 SearchEngine 构造注入）与 judge。

    --real 缺 API key 时 ``build_llm_provider`` 抛 ``RuntimeError``（带配置指引），
    调用侧转友好报错（见 ``main``）。
    """
    cfg = eval_settings(real)
    search_engine = build_default_search_engine(
        cfg,
        vector_store=stores["vector_store"],
        graph_store=stores["graph_store"],
        community_store=stores["community_store"],
        sparse_index=InMemoryBM25Index(),
    )
    engine = build_analysis_engine(cfg, search_engine=search_engine)
    if real:
        judge = build_llm_provider(get_settings())
    else:
        from calliodesmo.providers.stub_llm import StubLLMProvider

        judge = StubLLMProvider(model="test/judge")
    return engine, judge


def fmt_score(v) -> str:
    return "-" if v is None else f"{v:.4f}"


def _friendly_exit(exc: RuntimeError) -> None:
    """--real 缺 key / 配置不全的友好报错（离线桩路径不触发）。"""
    print(f"[real] 启动失败：{exc}")
    print("[real] 请检查 .env 的 CALLIODESMO_LLM_MODEL / CALLIODESMO_LLM_API_KEY 等配置后重试。")
    raise SystemExit(1) from exc


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump-golden", action="store_true")
    parser.add_argument("--real", action="store_true", help="按 .env 接真实模型（默认离线桩）")
    args = parser.parse_args()

    mode = "real(.env)" if args.real else "offline-stub(hash+StubLLM)"
    print(f"[mode] {mode}")
    print("[ingest] 内存 stores 灌入 data/demo ...")
    try:
        stores, mapping, stats = await ingest_demo(args.real)
    except RuntimeError as exc:
        # --real 灌库同样经 LLM/嵌入 provider，缺 key 在此即友好报错
        _friendly_exit(exc)
    print("[ingest] stats:", stats)

    if args.dump_golden:
        print("---CHUNK SKELETON---")
        for cid, (doc, snip) in mapping.items():
            print(cid, "|", doc, "|", snip)
        return

    cases = load_golden_analysis(GOLDEN_FILE)
    print("[golden]", len(cases), "cases from", GOLDEN_FILE)
    if not cases:
        msg = "NO golden cases: 先 --dump-golden 建 chunk 骨架，再补 config/golden_analysis.yaml"
        raise SystemExit(msg)

    try:
        engine, judge = build_engines(stores, args.real)
    except RuntimeError as exc:
        _friendly_exit(exc)

    harness = AnalysisEvalHarness(
        engine,
        judge,
        vector_store=stores["vector_store"],
        graph_store=stores["graph_store"],
    )
    print("[run] 分析回归 ...")
    report = await harness.run(cases, access=ACCESS)

    disclaimer = REAL_DISCLAIMER if args.real else OFFLINE_DISCLAIMER
    out = {
        "mode": mode,
        "generated_at": datetime.now(UTC).isoformat(),
        "disclaimer": disclaimer,
        "golden_file": GOLDEN_FILE,
        **report.to_dict(),
    }

    def _write_out() -> None:
        OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    await asyncio.to_thread(_write_out)
    print("[saved]", OUT_FILE)

    header = (
        f"{'case_id':<32}{'task_type':<20}{'status':<10}"
        f"{'field_f1':>10}{'tuple_f1':>10}{'judge':>8}"
    )
    print(header)
    for c in report.cases:
        judge_overall = c.judge_scores.overall if c.judge_scores else None
        print(
            f"{c.case_id:<32}{c.task_type:<20}{c.status:<10}"
            f"{fmt_score(c.field_scores.f1 if c.field_scores else None):>10}"
            f"{fmt_score(c.tuple_scores.f1 if c.tuple_scores else None):>10}"
            f"{fmt_score(judge_overall):>8}"
        )
    print(
        f"{'MEAN':<32}{'':<20}{'':<10}"
        f"{fmt_score(report.mean_field_f1):>10}"
        f"{fmt_score(report.mean_tuple_f1):>10}"
        f"{fmt_score(report.mean_judge_overall):>8}"
    )
    # 显式警示行：离线证据≠质量证据（口径留痕，随每次运行打印）
    print(f"[!] {disclaimer}")


if __name__ == "__main__":
    asyncio.run(main())
