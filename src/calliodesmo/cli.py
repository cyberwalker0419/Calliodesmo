"""Calliodesmo CLI（Typer）：db init / db seed / serve / ingest。"""

import asyncio
import json
import uuid

import typer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from calliodesmo import __version__
from calliodesmo.config import get_settings
from calliodesmo.db.base import Base
from calliodesmo.ecl.engine import build_default_indexing_engine

app = typer.Typer(help="Calliodesmo：三层知识图谱驱动的智能情报分析平台。")
db_app = typer.Typer(help="数据库管理命令。")
app.add_typer(db_app, name="db")

#: CLI ingest 使用的系统用户（个人库 owner；审计 user_id 留空表示系统动作）
SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"calliodesmo {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="显示版本号。"
    ),
) -> None:
    """Calliodesmo 命令行入口。"""


async def _create_all(database_url: str) -> None:
    import calliodesmo.models  # noqa: F401  注册全部 ORM 模型

    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


@db_app.command("init")
def db_init() -> None:
    """按 Base.metadata 建表（幂等；未来迁移到 Alembic）。"""
    settings = get_settings()
    asyncio.run(_create_all(settings.database_url))
    typer.echo("数据库表已创建。")


async def _seed(
    database_url: str, admin_username: str, admin_password: str | None
) -> tuple[int, bool]:
    import calliodesmo.models  # noqa: F401
    from calliodesmo.auth.models import ClearanceLevel, LibraryScope, User
    from calliodesmo.auth.service import assign_role, create_user, seed_default_roles

    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        roles = await seed_default_roles(session)
        admin_created = False
        if admin_password:
            existing = (
                await session.execute(select(User).where(User.username == admin_username))
            ).scalar_one_or_none()
            if existing is None:
                admin = await create_user(
                    session,
                    username=admin_username,
                    password=admin_password,
                    clearance=ClearanceLevel.SECRET,
                )
                await assign_role(session, user=admin, role_name="admin", scope=LibraryScope.TEAM)
                admin_created = True
        await session.commit()
    await engine.dispose()
    return len(roles), admin_created


@db_app.command("seed")
def db_seed() -> None:
    """写入内置角色/权限，并按 CALLIODESMO_ADMIN_* 创建初始管理员（幂等）。"""
    settings = get_settings()
    roles_created, admin_created = asyncio.run(
        _seed(settings.database_url, settings.admin_username, settings.admin_password)
    )
    status = "已创建" if admin_created else "已存在或未提供密码（跳过）"
    typer.echo(f"新建角色 {roles_created} 个；管理员{status}。")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="监听地址。"),
    port: int = typer.Option(8000, help="监听端口。"),
    reload: bool = typer.Option(False, "--reload", help="开发模式自动重载。"),
) -> None:
    """启动 API 服务（uvicorn，无需 Docker 的原生部署入口）。"""
    import uvicorn

    uvicorn.run("calliodesmo.api.app:app", host=host, port=port, reload=reload)


def _system_access():
    from calliodesmo.auth.context import AccessContext
    from calliodesmo.auth.models import ClearanceLevel, Permission

    return AccessContext(
        user_id=SYSTEM_USER_ID,
        username="system",
        clearance=ClearanceLevel.INTERNAL,
        permissions=frozenset({Permission.INGEST}),
    )


def _dump_outputs(engine, stats, dump_json, dump_html):
    """导出抽取详情 JSON 与/或交互式关系图 HTML。"""
    from dataclasses import asdict

    from calliodesmo.ecl.graph_html import render_graph_html

    merged = engine.last_merged
    graph = engine.last_graph or {}
    nodes = graph.get("nodes", {})
    edges = graph.get("edges", [])
    aliases = graph.get("aliases", {})

    if dump_json:
        payload = {
            "stats": stats.as_dict(),
            "entities": [asdict(e) for e in (merged.entities if merged else [])],
            "relations": [asdict(r) for r in (merged.relations if merged else [])],
            "claims": [asdict(c) for c in (merged.claims if merged else [])],
            "covariates": [asdict(v) for v in (merged.covariates if merged else [])],
            "graph": {
                "nodes": [
                    {
                        "name": n.name,
                        "type": n.type,
                        "description": n.description,
                        "source_chunk_ids": n.source_chunk_ids,
                    }
                    for n in nodes.values()
                ],
                "edges": [
                    {
                        "source": e.source,
                        "target": e.target,
                        "type": e.type,
                        "description": e.description,
                    }
                    for e in edges
                ],
                "aliases": aliases,
            },
            "communities": [
                {
                    "community_id": c.community_id,
                    "level": c.level,
                    "title": c.title,
                    "summary": c.summary,
                    "member_entity_names": c.member_entity_names,
                }
                for c in engine.last_communities
            ],
        }
        with open(dump_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        typer.echo(f"抽取详情已导出：{dump_json}")

    if dump_html:
        render_graph_html(nodes, edges, dump_html)
        typer.echo(f"关系图已导出：{dump_html}（浏览器打开查看）")


async def _run_ingest(source: str, settings, engine_factory) -> object:
    engine = engine_factory(settings)
    access = _system_access()
    stats = await engine.ingest(source, access=access)

    # 审计：ingest 动作落 AuditLog
    import calliodesmo.models  # noqa: F401
    from calliodesmo.audit.service import record_audit

    db_engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await record_audit(
            session,
            user_id=None,
            action="ingest",
            resource_type="document",
            detail=stats.as_dict(),
            source="cli",
        )
        await session.commit()
    await db_engine.dispose()
    return stats, engine


@app.command()
def ingest(
    path: str = typer.Argument(..., help="文档路径（文件或目录），按后缀自动分发加载器。"),
    dump_json: str = typer.Option(
        None, "--dump-json", help="抽取详情（实体/关系/声明/社区）导出为 JSON 到该路径。"
    ),
    dump_html: str = typer.Option(
        None,
        "--dump-html",
        help="关系图导出为交互式 HTML（vis.js）到该路径，浏览器打开可看实体关系网络。",
    ),
) -> None:
    """端到端建图落个人库：Load -> Extract -> Cognify -> Load -> 文档社区派生。

    输出统计并记审计。LLM 经 CALLIODESMO_LLM_MODEL/CALLIODESMO_LLM_API_KEY 配置；
    缺 key 时给出指引。内存 stores 为 P1 默认（离线可测）。
    """
    settings = get_settings()
    try:
        stats, engine = asyncio.run(_run_ingest(path, settings, build_default_indexing_engine))
    except FileNotFoundError as exc:
        typer.echo(f"错误：{exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (ValueError, RuntimeError) as exc:
        # ValueError: loader 未注册（提示 extra）；RuntimeError: LLM 缺 key
        typer.echo(f"错误：{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"ingest 完成：文档 {stats.documents} / 块 {stats.chunks} / "
        f"实体 {stats.entities} / 关系 {stats.relations} / 社区 {stats.communities} / "
        f"档案卡 {stats.profile_cards}"
    )
    if dump_json or dump_html:
        _dump_outputs(engine, stats, dump_json, dump_html)


def _build_default_search_engine(settings):
    """构造默认搜索引擎（内存 stores + Hash 嵌入 + IdentityReranker + 桩 LLM）。"""
    from calliodesmo.providers.hash_embedding import HashEmbeddingProvider
    from calliodesmo.providers.in_memory_community_store import InMemoryCommunityStore
    from calliodesmo.providers.in_memory_graph_store import InMemoryGraphStore
    from calliodesmo.providers.in_memory_vector_store import InMemoryVectorStore
    from calliodesmo.providers.stub_llm import StubLLMProvider
    from calliodesmo.retrieval.answer_synthesizer import AnswerSynthesizer
    from calliodesmo.retrieval.global_search import GlobalSearchRetriever
    from calliodesmo.retrieval.hybrid_retriever import HybridRetriever
    from calliodesmo.retrieval.identity_reranker import IdentityReranker
    from calliodesmo.retrieval.in_memory_sparse_index import InMemoryBM25Index
    from calliodesmo.retrieval.local_search import LocalSearchRetriever
    from calliodesmo.retrieval.search_engine import DefaultSearchEngine
    from calliodesmo.retrieval.seed_extractor import SeedExtractor

    llm = StubLLMProvider(model="test/stub")
    emb = HashEmbeddingProvider(dimension=settings.embedding_dimension or 64)
    vs = InMemoryVectorStore()
    graph = InMemoryGraphStore()
    comm = InMemoryCommunityStore()
    bm = InMemoryBM25Index()
    seed = SeedExtractor(llm)
    native = HybridRetriever(vector_store=vs, embedding_provider=emb, sparse_index=bm)
    local = LocalSearchRetriever(
        seed_extractor=seed, graph_store=graph, vector_store=vs, hops=settings.local_search_hops
    )
    glob = GlobalSearchRetriever(
        community_store=comm,
        graph_store=graph,
        vector_store=vs,
        embedding_provider=emb,
        top_communities=settings.global_top_communities,
    )
    synth = AnswerSynthesizer(llm)
    return DefaultSearchEngine(
        native_retriever=native,
        local_retriever=local,
        global_retriever=glob,
        reranker=IdentityReranker(),
        synthesizer=synth,
    )


@app.command()
def ask(
    question: str = typer.Argument(..., help="问题文本。"),
    mode: str = typer.Option(
        "native_rag", "--mode", help="检索模式：native_rag / local / global。"
    ),
    top_k: int = typer.Option(10, "--top-k", help="返回候选数。"),
) -> None:
    """问答命令：构造默认引擎 -> 检索 -> 合成答案 -> 打印答案与来源。"""
    import asyncio

    from calliodesmo.interfaces.retriever import SearchMode

    settings = get_settings()
    try:
        mode_enum = SearchMode(mode)
    except ValueError:
        typer.echo(f"错误：未知检索模式 {mode}（可选 native_rag / local / global）", err=True)
        raise typer.Exit(code=1) from None

    engine = _build_default_search_engine(settings)
    access = _system_access()
    answer = asyncio.run(engine.query(question, mode=mode_enum, top_k=top_k, access=access))
    typer.echo(f"[模式] {answer.mode.value}")
    typer.echo(f"[答案] {answer.text}")
    if answer.source_chunk_ids:
        typer.echo(f"[来源] {', '.join(answer.source_chunk_ids)}")
    else:
        typer.echo("[来源] 无")
