"""Calliodesmo CLI（Typer）：db init / db seed / serve / ingest。"""

import asyncio
import json
import uuid

import typer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from calliodesmo import __version__
from calliodesmo.config import get_settings
from calliodesmo.db.base import Base
from calliodesmo.ecl.engine import build_default_indexing_engine

app = typer.Typer(help="Calliodesmo：三层知识图谱驱动的智能情报分析平台。")
db_app = typer.Typer(help="数据库管理命令。")
app.add_typer(db_app, name="db")
users_app = typer.Typer(help="用户管理命令。")
app.add_typer(users_app, name="users")
teams_app = typer.Typer(help="团队管理命令。")
app.add_typer(teams_app, name="teams")

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
    seed_demo: bool = typer.Option(
        False, "--seed-demo", help="启动前注入 data/demo/ 演示数据（serve 进程内自灌）。"
    ),
) -> None:
    """启动 API 服务（uvicorn，无需 Docker 的原生部署入口）。

    --seed-demo：serve 进程内对 data/demo/ 跑 ECL 注入内存 stores 单例
    （内存模式 CLI ingest 跨进程不可见，演示数据统一走此路径）；产物落盘缓存，
    二次启动命中缓存直接加载、跳过 LLM。
    """
    import uvicorn

    if seed_demo:
        _seed_demo_for_serve()
    uvicorn.run("calliodesmo.api.app:app", host=host, port=port, reload=reload)


def _seed_demo_for_serve() -> None:
    """serve --seed-demo：确保演示团队 + 管理员成员，然后注入演示数据到 stores 单例。"""
    from calliodesmo.api.deps import get_app_stores

    settings = get_settings()
    report = asyncio.run(_seed_demo_async(settings))
    stores = get_app_stores()
    typer.echo(
        f"演示数据已注入（{report.source}）：文档 {report.documents} / 块 {report.chunks} / "
        f"档案卡 {len(stores.profile_card_store)} / 社区 {len(stores.community_store)}"
    )


async def _seed_demo_async(settings):
    from pathlib import Path

    import calliodesmo.models  # noqa: F401
    from calliodesmo.api.deps import get_app_stores
    from calliodesmo.auth.context import AccessContext
    from calliodesmo.auth.models import ClearanceLevel, Permission, Team, User
    from calliodesmo.auth.service import add_team_member, create_team
    from calliodesmo.ecl.demo_seed import seed_demo_stores

    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        admin = (
            await session.execute(select(User).where(User.username == settings.admin_username))
        ).scalar_one_or_none()
        if admin is None:
            typer.echo(f"错误：管理员 {settings.admin_username} 不存在（先运行 db seed）", err=True)
            raise typer.Exit(code=1)
        demo_team = (
            await session.execute(
                select(Team).options(selectinload(Team.members)).where(Team.name == "演示团队")
            )
        ).scalar_one_or_none()
        if demo_team is None:
            demo_team = await create_team(
                session, name="演示团队", description="serve --seed-demo 演示团队"
            )
            await session.flush()
            await session.refresh(demo_team, ["members"])
        if not any(m.user_id == admin.id for m in demo_team.members):
            await add_team_member(session, user=admin, team=demo_team, role_in_team="manager")
        await session.commit()
        team_id = demo_team.id
        admin_id = admin.id
    await engine.dispose()

    access = AccessContext(
        user_id=admin_id,
        username=settings.admin_username,
        clearance=ClearanceLevel.SECRET,
        permissions=frozenset(set(Permission)),
        team_ids=frozenset({team_id}),
    )
    return await seed_demo_stores(
        get_app_stores(),
        settings,
        demo_dir=Path(settings.demo_dir),
        cache_file=Path(settings.demo_cache_file),
        access=access,
    )


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


# ---- P3 用户/团队管理命令 ----


async def _with_session(fn):
    """开异步会话执行 fn(session)，返回其结果。"""
    import calliodesmo.models  # noqa: F401

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        result = await fn(session)
        await session.commit()
    await engine.dispose()
    return result


@users_app.command("list")
def users_list() -> None:
    """列出全部用户（含 clearance / 激活状态）。"""
    from calliodesmo.auth.service import list_users

    users = asyncio.run(_with_session(list_users))
    for u in users:
        state = "激活" if u.is_active else "已停用"
        typer.echo(f"{u.username}\t{u.clearance.name}\t{state}")


@users_app.command("create")
def users_create(
    username: str = typer.Argument(..., help="用户名。"),
    password: str = typer.Option(..., "--password", help="初始密码。"),
    clearance: str = typer.Option(
        "INTERNAL", "--clearance", help="访问等级（PUBLIC/INTERNAL/CONFIDENTIAL/SECRET）。"
    ),
) -> None:
    """创建用户（幂等：用户名已存在则报错退出）。"""
    from calliodesmo.auth.models import ClearanceLevel
    from calliodesmo.auth.service import create_user, get_user_by_username

    try:
        level = ClearanceLevel[clearance.upper()]
    except KeyError:
        typer.echo(f"错误：未知 clearance {clearance}", err=True)
        raise typer.Exit(code=1) from None

    async def _op(session):
        if await get_user_by_username(session, username) is not None:
            return None
        return await create_user(session, username=username, password=password, clearance=level)

    user = asyncio.run(_with_session(_op))
    if user is None:
        typer.echo(f"错误：用户名 {username} 已存在", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"用户 {username} 已创建（clearance={level.name}）。")


@users_app.command("deactivate")
def users_deactivate(username: str = typer.Argument(..., help="用户名。")) -> None:
    """停用用户（软删除：is_active=False，保留审计可追溯）。"""
    from calliodesmo.auth.service import deactivate_user, get_user_by_username

    async def _op(session):
        user = await get_user_by_username(session, username)
        if user is None:
            return None
        return await deactivate_user(session, user_id=user.id)

    user = asyncio.run(_with_session(_op))
    if user is None:
        typer.echo(f"错误：用户 {username} 不存在", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"用户 {username} 已停用。")


@teams_app.command("create")
def teams_create(
    name: str = typer.Argument(..., help="团队名。"),
    description: str = typer.Option("", "--description", help="团队描述。"),
) -> None:
    """创建团队。"""
    from calliodesmo.auth.service import create_team

    team = asyncio.run(_with_session(lambda s: create_team(s, name=name, description=description)))
    typer.echo(f"团队 {team.name} 已创建。")


@teams_app.command("add-member")
def teams_add_member(
    team_name: str = typer.Argument(..., help="团队名。"),
    username: str = typer.Argument(..., help="用户名。"),
    role_in_team: str = typer.Option(
        "member", "--role", help="组内角色（member/manager/reviewer）。"
    ),
) -> None:
    """把用户加入团队。"""
    from sqlalchemy import select as _select

    from calliodesmo.auth.models import Team
    from calliodesmo.auth.service import add_team_member, get_user_by_username

    async def _op(session):
        team = (
            await session.execute(_select(Team).where(Team.name == team_name))
        ).scalar_one_or_none()
        user = await get_user_by_username(session, username)
        if team is None or user is None:
            return None
        return await add_team_member(session, user=user, team=team, role_in_team=role_in_team)

    member = asyncio.run(_with_session(_op))
    if member is None:
        typer.echo(f"错误：团队 {team_name} 或用户 {username} 不存在", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"用户 {username} 已加入团队 {team_name}（{role_in_team}）。")
