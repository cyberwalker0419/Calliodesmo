"""P5 检索质量 golden 回归：baseline vs multi_query/contextual/crag/selfcheck（P5 Task 6/7）。

在内存 stores 上灌入 data/demo 语料，对 config/golden_qa.yaml 逐配置跑 EvalHarness，
输出控制台对比表 + 落盘 docs/verification/p5-regression.json。

默认**全离线确定性**（StubLLM + Hash 嵌入，零网络、可复现），与 CI 同纪律；
设 --real 才按 .env 接真实模型（本地有 LLM/嵌入服务时用）。

用法：
    uv run python scripts/eval_p5.py --dump-golden   # 只灌库并打印 chunk 骨架（建 golden 用）
    uv run python scripts/eval_p5.py                 # 跑全配置回归并落盘（离线桩）
    uv run python scripts/eval_p5.py --real          # 接真实模型（需本机可达 LLM/嵌入）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.config import Settings, get_settings
from calliodesmo.ecl.engine import build_default_indexing_engine
from calliodesmo.eval.golden import load_golden
from calliodesmo.eval.harness import EvalHarness
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
from calliodesmo.retrieval.factory import build_default_search_engine, build_llm_provider
from calliodesmo.retrieval.in_memory_sparse_index import InMemoryBM25Index

DEMO_DIR = "data/demo"
GOLDEN_FILE = "config/golden_qa.yaml"
OUT_FILE = Path("docs/verification/p5-regression.json")
USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

ACCESS = AccessContext(
    # CLI ingest 写 demo 的记录 owner_id 为 None（系统语义）；评估视角 user_id=None，
    # 使 visible_to 对 PERSONAL 记录恒命中（None == None），等价「本人个人库全可见」。
    user_id=None,
    username="admin",
    clearance=ClearanceLevel.SECRET,
    permissions=frozenset(p.value for p in Permission),
    library_scopes=frozenset(s.value for s in LibraryScope),
)

CONFIGS = ["baseline", "multi_query", "contextual", "crag", "selfcheck", "all"]


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


def build_engine(label: str, stores: dict, real: bool):
    flags = {
        "multi_query_enabled": False,
        "contextual_retrieval_enabled": False,
        "crag_enabled": False,
        "selfcheck_enabled": False,
    }
    if label == "multi_query":
        flags["multi_query_enabled"] = True
    elif label == "contextual":
        flags["contextual_retrieval_enabled"] = True
    elif label == "crag":
        flags["crag_enabled"] = True
    elif label == "selfcheck":
        flags["selfcheck_enabled"] = True
    elif label == "all":
        flags = {k: True for k in flags}
    cfg = eval_settings(real).model_copy(update=flags)
    return build_default_search_engine(
        cfg,
        vector_store=stores["vector_store"],
        graph_store=stores["graph_store"],
        community_store=stores["community_store"],
        sparse_index=InMemoryBM25Index(),
    )


async def run_one(label: str, stores: dict, judge, real: bool):
    engine = build_engine(label, stores, real)
    harness = EvalHarness(engine, judge)
    cases = load_golden(GOLDEN_FILE)
    report = await harness.run(cases, access=ACCESS)
    return report


def fmt_score(v: float) -> str:
    return f"{v:.4f}"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump-golden", action="store_true")
    parser.add_argument("--real", action="store_true", help="按 .env 接真实模型（默认离线桩）")
    parser.add_argument("--configs", default=",".join(CONFIGS), help="逗号分隔的配置子集")
    args = parser.parse_args()

    mode = "real(.env)" if args.real else "offline-stub(hash+StubLLM)"
    print(f"[mode] {mode}")
    print("[ingest] 内存 stores 灌入 data/demo ...")
    stores, mapping, stats = await ingest_demo(args.real)
    print("[ingest] stats:", stats)

    if args.dump_golden:
        print("---CHUNK SKELETON---")
        for cid, (doc, snip) in mapping.items():
            print(cid, "|", doc, "|", snip)
        return

    cases = load_golden(GOLDEN_FILE)
    print("[golden]", len(cases), "cases from", GOLDEN_FILE)
    if not cases:
        msg = "NO golden cases: 先 --dump-golden 建 chunk 骨架，再补 config/golden_qa.yaml"
        raise SystemExit(msg)

    if args.real:
        judge = build_llm_provider(get_settings())
    else:
        from calliodesmo.providers.stub_llm import StubLLMProvider

        judge = StubLLMProvider(model="test/judge")

    selected = [c.strip() for c in args.configs.split(",") if c.strip()]
    reports = {}
    for label in selected:
        print(f"[run] {label} ...")
        report = await run_one(label, stores, judge, args.real)
        reports[label] = {
            "total": report.total,
            "mean_context_recall": report.mean_context_recall,
            "mean_faithfulness": report.mean_faithfulness,
            "mean_answer_relevance": report.mean_answer_relevance,
            "cases": [
                {
                    "question": c.question,
                    "context_recall": c.context_recall,
                    "faithfulness": c.faithfulness,
                    "answer_relevance": c.answer_relevance,
                    "answer_text": c.answer_text,
                    "source_chunk_ids": c.source_chunk_ids,
                }
                for c in report.cases
            ],
        }

    def _write_out() -> None:
        OUT_FILE.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")

    await asyncio.to_thread(_write_out)
    print("[saved]", OUT_FILE)

    header = f"{'config':<12}{'ctx_recall':>11}{'faithful':>11}{'relevance':>11}"
    print(header)
    for label, r in reports.items():
        print(
            f"{label:<12}{fmt_score(r['mean_context_recall']):>11}"
            f"{fmt_score(r['mean_faithfulness']):>11}{fmt_score(r['mean_answer_relevance']):>11}"
        )


if __name__ == "__main__":
    asyncio.run(main())
