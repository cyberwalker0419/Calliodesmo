"""P9 Task 8：检索规模压测（离线确定性基线 + 可选真后端 / OSINT 语料）。

产出 ``docs/verification/p9-loadtest.json``：并发阶梯 1 / 5 / 20 下的 p50 / p95 / p99 /
吞吐，以及**越权泄漏计数**（按一票否决：泄漏 > 0 即整轮判失败）。

口径与边界：

- 默认全离线（Hash 嵌入 + StubLLM + 合成语料）：量的是**检索与编排路径**的规模行为，
  不含 LLM 时延，因此数字可重复、可回归对比；真模型的端到端体验归 ``--real`` 质量轨。
- ``--backend postgres`` 用真 pgvector 走同一条检索链，给出「换后端换实现」的规模对照
  （稀疏路仍是进程内 BM25——PG 化属 P9 移交项，见 ``api/deps.py`` TODO 2026-W52）。
- ``--osint-corpus <路径>`` 读真实数据集（如 CISA KEV JSON）抽样成语料文档，只读取内容、
  不入库不改结构；数据集本身在 ``data/`` 下（不追踪），故本脚本对缺失文件直接跳过并说明。
- 语料参数（``--docs`` / ``--requests``）会显著影响数字，全部落进证据 JSON，
  换机器 / 换参数对比前先对齐口径。

用法::

    uv run python scripts/loadtest_p9.py                      # 离线合成语料基线
    uv run python scripts/loadtest_p9.py --backend postgres   # 真 pgvector 对照
    uv run python scripts/loadtest_p9.py --docs 400 --requests 400
    uv run python scripts/loadtest_p9.py --osint-corpus "D:/path/cisa-kev.json" --osint-docs 200
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.config import Settings
from calliodesmo.eval.loadtest import bench
from calliodesmo.interfaces.retriever import SearchMode
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
from calliodesmo.retrieval.factory import build_default_search_engine
from calliodesmo.retrieval.in_memory_sparse_index import InMemoryBM25Index

ROOT = Path(__file__).resolve().parents[1]
OUT_FILE = ROOT / "docs" / "verification" / "p9-loadtest.json"
CONCURRENCY_LADDER = (1, 5, 20)

#: 合成语料的共享词与差异词（保证 BM25 / 向量都有活干，且查询可命中）
_SHARED_TERMS = ("威胁组织", "供应链", "基础设施", "报价", "永磁材料", "零日漏洞")

ADMIN = AccessContext(
    user_id=None,
    username="loadtest-admin",
    clearance=ClearanceLevel.SECRET,
    permissions=frozenset(p.value for p in Permission),
    library_scopes=frozenset(s.value for s in LibraryScope),
)
#: 越权探针视角：PUBLIC 密级，语料里所有 confidential 块都不该出现在结果里
PROBE = AccessContext(
    user_id=None,
    username="loadtest-probe",
    clearance=ClearanceLevel.PUBLIC,
    permissions=frozenset(p.value for p in Permission),
    library_scopes=frozenset(s.value for s in LibraryScope),
)


def offline_settings(dimension: int = 64) -> Settings:
    """离线确定性配置（与 eval_p5 的桩口径一致）。"""
    return Settings(
        llm_model="test/stub-loadtest",
        embedding_provider="hash",
        embedding_dimension=dimension,
        reranker_provider="none",
        hybrid_enabled=True,
        sparse_enabled=True,
        vector_store_backend="memory",
        graph_store_backend="memory",
        community_store_backend="memory",
        _env_file=None,
    )


def synth_corpus(docs: int) -> list[dict]:
    """合成语料：每文档一块，密级交替（一半 PUBLIC、一半 CONFIDENTIAL）。"""
    corpus = []
    for index in range(docs):
        term = _SHARED_TERMS[index % len(_SHARED_TERMS)]
        level = ClearanceLevel.PUBLIC if index % 2 == 0 else ClearanceLevel.CONFIDENTIAL
        content = (
            f"# 压测文档 {index:04d}\n\n"
            f"压测实体-{index:04d} 与{term}相关，编号 {index:04d}。"
            f"该条目记录{term}的观测结果，涉及基础设施与人员动向，"
            f"补充说明 {index % 97} 号关联线索（同一实体在 {index:04d} 号文档出现）。\n"
        )
        corpus.append(
            {
                "chunk_id": f"load-{index:04d}.md#0",
                "doc_id": f"load-{index:04d}.md",
                "content": content,
                "access_level": level,
                "query": f"压测实体-{index:04d} 的编号是什么？",
            }
        )
    return corpus


def osint_corpus(path: Path, docs: int) -> tuple[list[dict], str]:
    """真实数据集抽样（默认按 CISA KEV JSON 形态）：只读取，不改原文件。

    返回 ``(语料, 说明)``；结构不符或文件缺失时返回空语料并给出可读说明。
    """
    if not path.is_file():
        return [], f"数据集不存在，跳过：{path}"
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("vulnerabilities") if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not items:
        return [], "数据集结构不是期望的条目列表，跳过"
    corpus: list[dict] = []
    for offset, item in enumerate(items[:docs]):
        if not isinstance(item, dict):
            continue
        cve_id = str(item.get("cveID") or item.get("id") or f"item-{offset}")
        name = str(item.get("vendorProject") or "") + " " + str(item.get("product") or "")
        date = str(item.get("dateAdded") or "")
        urls = item.get("knownRansomwareCampaignUse") or ""
        content = (
            f"# {cve_id}\n\n已知被利用漏洞 {cve_id}：{name.strip()}。"
            f"收录日期 {date}。勒索软件关联：{urls or '未标注'}。"
            f"该条目用于检索规模压测，编号 {offset:04d}。\n"
        )
        level = ClearanceLevel.PUBLIC if offset % 2 == 0 else ClearanceLevel.CONFIDENTIAL
        corpus.append(
            {
                "chunk_id": f"osint-{offset:04d}.md#0",
                "doc_id": f"osint-{offset:04d}.md",
                "content": content,
                "access_level": level,
                "query": f"{cve_id} 的收录日期与厂商产品是什么？",
            }
        )
    return corpus, f"抽样 {len(corpus)} 条：{path.name}"


#: 压测专用 schema：与 dev 的 public、测试的 calliodesmo_test 都隔离，跑完 DROP
LOADTEST_SCHEMA = "calliodesmo_loadtest"


async def make_isolated_pg_engine():
    """建独立 schema 并 create_all（pgvector 类型经 public 解析）。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
    from calliodesmo.config import get_settings
    from calliodesmo.db.base import Base

    engine = create_async_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": f"{LOADTEST_SCHEMA},public"}},
    )
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{LOADTEST_SCHEMA}"'))
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def drop_isolated_pg_engine(engine) -> None:
    """清理压测 schema（CASCADE 删表），随后释放连接池。"""
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{LOADTEST_SCHEMA}" CASCADE'))
    await engine.dispose()


async def build_engine(
    settings: Settings, corpus: list[dict], *, backend: str, pg_engine=None
) -> tuple[object, set[str]]:
    """按后端装配检索引擎，返回 (engine, confidential 块 ID 集)。

    ``backend=postgres`` 必须传 ``pg_engine``（指向独立 schema 的 engine）——绝不往
    dev 的 public 库里灌压测语料。
    """
    if backend == "postgres":
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from calliodesmo.providers.pg_community_store import PgCommunityStore
        from calliodesmo.providers.pg_vector_store import PgVectorStore

        if pg_engine is None:
            raise ValueError("backend=postgres 需要 pg_engine（指向独立压测 schema）")
        factory = async_sessionmaker(pg_engine, expire_on_commit=False)
        vector_store: object = PgVectorStore(factory)
        community_store: object = PgCommunityStore(factory)
    else:
        vector_store = InMemoryVectorStore()
        community_store = InMemoryCommunityStore()

    provider = _embedding_provider(settings)
    texts = [entry["content"] for entry in corpus]
    vectors = (await provider.embed(texts)).vectors if texts else []
    records = [
        ChunkRecord(
            chunk_id=entry["chunk_id"],
            doc_id=entry["doc_id"],
            content=entry["content"],
            vector=list(vectors[i]) if i < len(vectors) else [],
            metadata={"doc_id": entry["doc_id"]},
            access_level=entry["access_level"],
            library_scope=LibraryScope.PERSONAL,
            owner_id=None,  # 系统语料（与 CLI ingest 同口径，visible_to 对 None 恒命中）
        )
        for i, entry in enumerate(corpus)
    ]
    await vector_store.upsert_chunks(records)  # type: ignore[attr-defined]
    sparse = InMemoryBM25Index()
    await sparse.index(records)
    engine = build_default_search_engine(
        settings,
        vector_store=vector_store,
        graph_store=InMemoryGraphStore(),
        community_store=community_store,
        sparse_index=sparse,
    )
    confidential = {
        entry["chunk_id"]
        for entry in corpus
        if entry["access_level"] is ClearanceLevel.CONFIDENTIAL
    }
    return engine, confidential


def _embedding_provider(settings: Settings):
    from calliodesmo.providers.hash_embedding import HashEmbeddingProvider

    return HashEmbeddingProvider(dimension=settings.embedding_dimension)


def _queries(corpus: list[dict], count: int) -> list[str]:
    """压测查询：轮转语料自带的问题句（每条语料建库时就带上自己的问题）。

    查询必须来自语料本身——否则合成问题打到真实数据集上会「零命中」，
    测到的只是空转，规模数字好看但无意义。
    """
    if not corpus:
        return ["压测实体-0000 的编号是什么？"] * count
    return [
        corpus[index % len(corpus)].get("query", f"压测条目 {index % len(corpus)}")
        for index in range(count)
    ]


async def run(
    *, docs: int, requests: int, backend: str, corpus_note: str, corpus: list[dict]
) -> dict:
    settings = offline_settings(dimension=1024 if backend == "postgres" else 64)
    pg_engine = await make_isolated_pg_engine() if backend == "postgres" else None
    try:
        engine, confidential = await build_engine(
            settings, corpus, backend=backend, pg_engine=pg_engine
        )
        return await _run_levels(engine, confidential, corpus, docs, requests, backend, corpus_note)
    finally:
        if pg_engine is not None:
            await drop_isolated_pg_engine(pg_engine)


async def _run_levels(
    engine,
    confidential: set[str],
    corpus: list[dict],
    docs: int,
    requests: int,
    backend: str,
    corpus_note: str,
) -> dict:
    queries = _queries(corpus, requests)

    levels: dict[str, dict] = {}
    for concurrency in CONCURRENCY_LADDER:
        # 每级固定请求数（requests < 并发度时高并发级只是有空位，不影响时延口径）
        per_level = requests
        counted = {"with_hits": 0}

        async def worker(index: int, counted_local: dict = counted) -> bool:
            # 规模轨固定走 native 混合检索路（local / global 依赖图与社区摘要，
            # 压测语料不建图，用它们只会测到空返回）
            answer = await engine.query(  # type: ignore[attr-defined]
                queries[index % len(queries)],
                mode=SearchMode.NATIVE_RAG,
                top_k=5,
                access=PROBE,
            )
            hits = {str(chunk.get("chunk_id")) for chunk in answer.context_chunks}
            if hits:
                counted_local["with_hits"] += 1
            # 越权泄漏：PUBLIC 视角看到了 confidential 块
            return bool(hits & confidential)

        result = await bench(worker, total=per_level, concurrency=concurrency)
        summary = result.summary()
        # 有效性对照：命中数 = 0 的压测数字没有意义（时延只反映空转）
        summary["with_hits"] = counted["with_hits"]
        levels[str(concurrency)] = summary

    return {
        "phase": "P9",
        "track": "loadtest",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "backend": backend,
            "embedding": "hash(确定性，不含真模型时延)",
            "llm": "stub",
        },
        "corpus": {
            "documents": len(corpus) or docs,
            "chunks": len(corpus) or docs,
            "confidential_chunks": len(confidential),
            "note": corpus_note,
        },
        "requests_per_level": requests,
        "top_k": 5,
        "mode": "native_rag",
        "levels": levels,
        "leaks_total": sum(level["leaks"] for level in levels.values()),
        "failed_total": sum(level["failed"] for level in levels.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="P9 检索规模压测")
    parser.add_argument("--docs", type=int, default=200, help="合成语料文档数（默认 200）")
    parser.add_argument("--requests", type=int, default=120, help="每并发级的请求数（默认 120）")
    parser.add_argument(
        "--backend", choices=("memory", "postgres"), default="memory", help="向量后端"
    )
    parser.add_argument(
        "--osint-corpus", type=Path, default=None, help="真实数据集 JSON 路径（抽样用，只读）"
    )
    parser.add_argument("--osint-docs", type=int, default=200, help="真实数据集抽样条数")
    parser.add_argument("--out", type=Path, default=OUT_FILE)
    args = parser.parse_args()

    if args.osint_corpus is not None:
        corpus, note = osint_corpus(args.osint_corpus, args.osint_docs)
        if not corpus:
            print(f"警告：{note}；回退合成语料", file=sys.stderr)
            corpus, note = synth_corpus(args.docs), "合成语料（回退）"
    else:
        corpus, note = synth_corpus(args.docs), "合成语料（确定性）"

    report = asyncio.run(
        run(
            docs=args.docs,
            requests=args.requests,
            backend=args.backend,
            corpus_note=note,
            corpus=corpus,
        )
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = " | ".join(
        f"c{level}: p95={data['p95']}ms rps={data['throughput_rps']}"
        for level, data in report["levels"].items()
    )
    print(f"corpus={report['corpus']['documents']} leaks={report['leaks_total']} -> {args.out}")
    print(summary)
    return 1 if report["leaks_total"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
