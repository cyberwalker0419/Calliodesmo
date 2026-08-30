"""Calliodesmo CLI（Typer）：db init / db seed / serve / ingest / ask / analyze。"""

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
contributions_app = typer.Typer(help="贡献请求(MR)管理命令。")
app.add_typer(contributions_app, name="contributions")
templates_app = typer.Typer(help="抽取模板审核命令。")
app.add_typer(templates_app, name="templates")

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
    # P6 Task 11：create_all 不给既有表加列 / 改列型 -> 幂等补齐（jobs 补列 +
    # contributions 时间列型回填）；全新库直出完整结构，此路径纯 no-op。
    from calliodesmo.db.migrate import ensure_missing_columns

    await ensure_missing_columns(engine)
    await engine.dispose()


@db_app.command("init")
def db_init() -> None:
    """按 Base.metadata 建表 + 幂等补齐既有库结构（未来迁移到 Alembic）。"""
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
        # 内建系统账户：CLI/后台无 HTTP 上下文动作的 actor（SYSTEM_USER_ID）。
        # audit_logs.user_id 是 FK->users.id，PG 强制外键须有真实行
        # （sqlite 不查 FK 故此前未暴露）。
        sys_user = (
            await session.execute(select(User).where(User.id == SYSTEM_USER_ID))
        ).scalar_one_or_none()
        if sys_user is None:
            session.add(
                User(
                    id=SYSTEM_USER_ID,
                    username="__system__",
                    hashed_password="!",  # 不可登录占位（非 Argon2 哈希）
                    clearance=ClearanceLevel.PUBLIC,
                    is_active=False,
                )
            )
            await session.flush()
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
    # P4.5 Task 5：启动恢复——遗留 pending/running job（进程内 worker 已随重启丢失）
    # 置 failed，前端轮询即时得到终态而非永挂。清理失败不阻启动。
    from calliodesmo.ecl.job_worker import reset_stale_running_jobs

    reset_stale_running_jobs()
    # P7 T11：loop 走 uvicorn 平台默认（Windows Proactor 服务 asyncpg 主库；
    # agent PG checkpointer 在 Windows 开发态经 build_runtime_checkpointer 降级 InMemory）
    from calliodesmo.agent.checkpoint import serve_loop_kwargs

    uvicorn.run(
        "calliodesmo.api.app:app", host=host, port=port, reload=reload, **serve_loop_kwargs()
    )


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


# ---- P6 Task 24：analyze CLI（仿 ask；提交 + barrier 同步等待 + 打印报告摘要） ----

#: 终端摘要截断预算：单条文本上限与条目列表展示条数（可读性优先，全文看落库报告）
_ANALYZE_SUMMARY_MAX_CHARS = 100
_ANALYZE_SUMMARY_MAX_ITEMS = 3
_ANALYZE_SUMMARY_MAX_SCALARS = 5


def _analyze_truncate(value: object, limit: int = _ANALYZE_SUMMARY_MAX_CHARS) -> str:
    """展示文本截断：超长以省略号收尾（终端摘要用，不改动落库内容）。"""
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _format_report_payload(payload: dict) -> list[str]:
    """报告载荷 -> 终端摘要行（截断展示；条目列表只展示前若干条）。

    结构化映射（与 ``api/analysis.render_report_markdown`` 同纪律，不重写为自由文本）：
    标量直出；标量列表分号串接；条目列表前 ``_ANALYZE_SUMMARY_MAX_ITEMS`` 条展开；
    嵌套 dict 内联 JSON 截断。全文与完整证据见落库报告（导出经 API /analysis/reports）。
    """
    lines: list[str] = []
    for key, value in (payload or {}).items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: （空）")
            elif all(v is None or isinstance(v, (str, int, float, bool)) for v in value):
                shown = "；".join(
                    _analyze_truncate(v) for v in value[:_ANALYZE_SUMMARY_MAX_SCALARS]
                )
                more = (
                    f"（等 {len(value)} 条）" if len(value) > _ANALYZE_SUMMARY_MAX_SCALARS else ""
                )
                lines.append(f"{key}: {shown}{more}")
            else:
                lines.append(f"{key}（{len(value)} 条）:")
                for index, item in enumerate(value[:_ANALYZE_SUMMARY_MAX_ITEMS], 1):
                    if isinstance(item, dict):
                        fields = " | ".join(
                            f"{k}={_analyze_truncate(v, 40)}"
                            for k, v in item.items()
                            if v is None or isinstance(v, (str, int, float, bool))
                        )
                        lines.append(f"  {index}. {_analyze_truncate(fields) or '（无标量字段）'}")
                    else:
                        lines.append(
                            f"  {index}. {_analyze_truncate(json.dumps(item, ensure_ascii=False))}"
                        )
                if len(value) > _ANALYZE_SUMMARY_MAX_ITEMS:
                    lines.append(
                        f"  （余 {len(value) - _ANALYZE_SUMMARY_MAX_ITEMS} 条，见落库报告）"
                    )
        elif isinstance(value, dict):
            lines.append(f"{key}: {_analyze_truncate(json.dumps(value, ensure_ascii=False))}")
        else:
            lines.append(f"{key}: {_analyze_truncate(value)}")
    return lines or ["（空载荷）"]


async def _run_analyze(
    settings,
    task_type,
    doc_ids: list[str],
    question: str,
    instruction: str,
    top_k: int,
) -> dict:
    """提交 analyze job 并同步等待完成：管理员校验 -> 提交 -> worker -> 读报告摘要。

    提交者为管理员（``settings.admin_username``，须先 ``db seed``）——worker 自库重建
    其上下文二次把关（``get_access_context``），材料全程经 ``visible_to``（红线，见
    ``analysis/materials.py``）。执行链复用既有组件：``build_analysis_engine`` +
    ``run_analysis_job`` + barrier 同步等待（与 ``tests/test_analysis_job_worker``
    同范式；worker 吞全部异常落终态，barrier 必置位，等待有界）。
    """
    import calliodesmo.models  # noqa: F401
    from calliodesmo.analysis.factory import build_analysis_engine
    from calliodesmo.analysis.job_worker import run_analysis_job
    from calliodesmo.analysis.report_store import AnalysisReportStore
    from calliodesmo.analysis.schemas import AnalysisType
    from calliodesmo.api.deps import get_app_stores
    from calliodesmo.audit.service import record_audit
    from calliodesmo.auth.models import Permission, User
    from calliodesmo.auth.service import get_access_context
    from calliodesmo.db.models_job import Job, JobStatus
    from calliodesmo.stores.visibility import visible_to
    from calliodesmo.utils.json import json_safe

    db_engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    try:
        # 1) 提交者 = 管理员：须存在且激活，并持 analyze 权限（缺则可读失败）
        async with factory() as session:
            admin = (
                await session.execute(select(User).where(User.username == settings.admin_username))
            ).scalar_one_or_none()
        if admin is None or not admin.is_active:
            raise RuntimeError(
                f"管理员 {settings.admin_username} 不存在或已停用（先运行 `calliodesmo db seed`）"
            )
        async with factory() as session:
            access = await get_access_context(session, admin.id)
        if access is None or not access.has_permission(Permission.ANALYZE):
            raise RuntimeError(
                f"管理员 {settings.admin_username} 缺少 analyze 权限（检查角色种子与授权）"
            )

        stores = get_app_stores()
        # 2) doc_ids 可见性预检（仿 API 提交侧 400 契约：仅成员筛选，不豁免可见性）
        if doc_ids:
            chunks = await stores.vector_store.list_chunks(access=access)
            visible_docs = {c.doc_id for c in chunks if visible_to(c, access)}
            if any(doc_id not in visible_docs for doc_id in doc_ids):
                raise ValueError("doc_ids 含不可见文档，请核对选择范围")

        # 3) 引擎请求边界构建（同 ingest / API 惯例）：QA 才注入 SearchEngine
        #    （经共享 stores 单例装配，仿 api/deps.get_search_engine；非 QA 不拉嵌入依赖）
        search_engine = None
        if task_type is AnalysisType.QA:
            from calliodesmo.retrieval.factory import build_default_search_engine, build_reranker

            search_engine = build_default_search_engine(
                settings,
                vector_store=stores.vector_store,
                graph_store=stores.graph_store,
                community_store=stores.community_store,
                sparse_index=stores.sparse_index,
                reranker=build_reranker(settings),
            )
        engine = build_analysis_engine(settings, search_engine=search_engine)

        # 4) 提交：建 job 行（pending）+ 审计受理（先落库后调度，同 API 提交侧）
        payload = json_safe(
            {
                "task_type": task_type.value,
                "doc_ids": list(doc_ids),
                "question": question,
                "custom_instruction": instruction if task_type is AnalysisType.CUSTOM else "",
                "custom_schema": None,  # CLI 最小集不暴露用户 schema（留痕见计划 Task 24）
                "top_k": top_k,
            }
        )
        async with factory() as session:
            job = Job(user_id=admin.id, task_type="analyze", task_payload=payload)
            session.add(job)
            await session.flush()
            await record_audit(
                session,
                user_id=admin.id,
                action="analyze_submit",
                resource_type="job",
                resource_id=str(job.id),
                detail={"task_type": task_type.value, "doc_ids_count": len(doc_ids)},
                source="cli",
            )
            await session.commit()
            job_id = job.id

        # 5) barrier 同步等待（测试同范式）：完成（含失败）后 barrier 置位
        barrier = asyncio.Event()
        worker = asyncio.create_task(
            run_analysis_job(job_id, engine=engine, session_factory=factory, barrier=barrier)
        )
        await barrier.wait()
        await worker  # worker 内部吞全部异常落终态，此处仅确认协程收敛

        # 6) 读终态 -> 报告摘要（报告固定 personal / owner=提交者，管理员读自身报告）
        async with factory() as session:
            job_row = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()
            result: dict = {
                "job_id": str(job_id),
                "status": job_row.status.value,
                "error": job_row.error,
                "report": None,
            }
            if job_row.status is JobStatus.SUCCEEDED and job_row.result:
                report_id = uuid.UUID(str(job_row.result["report_id"]))
                report = await AnalysisReportStore().get(session, report_id, access=access)
                if report is None:
                    raise RuntimeError(f"报告 {report_id} 不存在或不可见（管理员上下文异常）")
                envelope = report.payload or {}
                result["report"] = {
                    "id": str(report.id),
                    "task_type": report.task_type,
                    "status": report.status,
                    "subject_label": report.subject_label,
                    "model": report.model,
                    "source_doc_ids": list(report.source_doc_ids or []),
                    "source_chunk_count": report.source_chunk_count,
                    "warnings": list(envelope.get("warnings") or []),
                    "payload": envelope.get("payload")
                    if isinstance(envelope.get("payload"), dict)
                    else {},
                }
        return result
    finally:
        await db_engine.dispose()


@app.command()
def analyze(
    task_type: str = typer.Option(
        ...,
        "--task-type",
        help="分析类型：summary / key_information / timeline / entity_recognition / "
        "relation_mapping / tasks / concepts / qa / custom。",
    ),
    doc_ids: str = typer.Option(
        "", "--doc-ids", help="文档成员筛选（逗号分隔；空 = 全可见范围）。"
    ),
    question: str = typer.Option("", "--question", help="问题文本（qa 类必填）。"),
    instruction: str = typer.Option("", "--instruction", help="自定义分析指令（custom 类必填）。"),
    top_k: int = typer.Option(10, "--top-k", help="qa 类检索候选数。"),
) -> None:
    """LLM 分析命令：以管理员提交 analyze job -> 同步等待完成 -> 打印报告摘要。

    材料全经可见性过滤；ok / partial 报告落 analysis_reports（历史 / 导出经 API
    /analysis/reports），完全失败不落空报告并以非零退出码给出可读原因。
    离线冒烟：CALLIODESMO_LLM_MODEL=test/stub（桩输出仅验证管线，不代表分析质量）。
    """
    from calliodesmo.analysis.schemas import AnalysisType

    try:
        t = AnalysisType(task_type)
    except ValueError:
        options = " / ".join(member.value for member in AnalysisType)
        typer.echo(f"错误：未注册的分析类型 {task_type}（可选 {options}）", err=True)
        raise typer.Exit(code=1) from None
    if t is AnalysisType.QA and not question.strip():
        typer.echo("错误：qa 分析需要 --question（不得为空）", err=True)
        raise typer.Exit(code=1)
    if t is AnalysisType.CUSTOM and not instruction.strip():
        typer.echo("错误：custom 分析需要 --instruction（不得为空）", err=True)
        raise typer.Exit(code=1)

    settings = get_settings()
    ids = [d.strip() for d in doc_ids.split(",") if d.strip()]
    try:
        result = asyncio.run(_run_analyze(settings, t, ids, question, instruction, top_k))
    except (ValueError, RuntimeError) as exc:
        typer.echo(f"错误：{exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"[任务] {result['job_id']}")
    if result["status"] != "succeeded" or result["report"] is None:
        typer.echo(f"分析失败：{result['error'] or '无可读原因'}", err=True)
        raise typer.Exit(code=1)
    report = result["report"]
    typer.echo(f"[报告] id={report['id']} type={report['task_type']} status={report['status']}")
    typer.echo(f"[对象] {report['subject_label']}")
    typer.echo(f"[模型] {report['model']}")
    if report["source_doc_ids"]:
        docs_text = ", ".join(report["source_doc_ids"])
        typer.echo(f"[材料] {report['source_chunk_count']} 块 / 源文档：{docs_text}")
    for warning in report["warnings"]:
        typer.echo(f"[告警] {warning}")
    typer.echo("[内容]")
    for line in _format_report_payload(report["payload"]):
        typer.echo(f"  {line}")
    typer.echo(f"[报告已落库] analysis_reports id={report['id']}（完全失败的分析不落空报告）")


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


# ---- P4 贡献请求(MR) 命令 ----


@contributions_app.command("list")
def contributions_list() -> None:
    """列出全部贡献请求（管理员视角，不过滤）。"""
    import calliodesmo.models  # noqa: F401
    from calliodesmo.collab.models import Contribution

    async def _op(session):
        result = await session.execute(select(Contribution).order_by(Contribution.created_at))
        return result.scalars().all()

    items = asyncio.run(_with_session(_op))
    if not items:
        typer.echo("（无贡献请求）")
        return
    for c in items:
        typer.echo(
            f"{c.id}\t{c.status.value}\t{c.title}\t{c.source_scope.value}->{c.target_scope.value}"
        )


@contributions_app.command("show")
def contributions_show(contribution_id: str = typer.Argument(..., help="贡献 id。")) -> None:
    """查看贡献详情。"""
    import calliodesmo.models  # noqa: F401
    from calliodesmo.collab.models import Contribution

    async def _op(session):
        return await session.get(Contribution, uuid.UUID(contribution_id))

    c = asyncio.run(_with_session(_op))
    if c is None:
        typer.echo(f"错误：贡献 {contribution_id} 不存在", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"id: {c.id}")
    typer.echo(f"status: {c.status.value}")
    typer.echo(f"title: {c.title}")
    typer.echo(f"scope: {c.source_scope.value} -> {c.target_scope.value}")
    typer.echo(f"doc_ids: {c.doc_ids}")
    typer.echo(f"assignee: {c.assignee_id}")
    typer.echo(f"version: {c.version}")


def _collab_op(fn):
    """跑贡献状态机操作，捕获 ContributionError/ValueError 返回异常对象。"""
    result = asyncio.run(_with_session(fn))
    return result


@contributions_app.command("submit")
def contributions_submit(contribution_id: str = typer.Argument(..., help="贡献 id。")) -> None:
    """提交贡献（draft -> submitted）。"""
    from calliodesmo.collab.service import ContributionError, ContributionService

    svc = ContributionService()
    cid = uuid.UUID(contribution_id)

    async def _op(session):
        try:
            return await svc.submit(session, cid, user_id=SYSTEM_USER_ID, source="cli")
        except (ContributionError, ValueError) as exc:
            return exc

    result = _collab_op(_op)
    if isinstance(result, Exception):
        typer.echo(f"错误：{result}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"贡献 {contribution_id} 已提交（assignee={result.assignee_id}）。")


@contributions_app.command("approve")
def contributions_approve(contribution_id: str = typer.Argument(..., help="贡献 id。")) -> None:
    """审核通过贡献（submitted -> approved）。"""
    from calliodesmo.collab.service import ContributionError, ContributionService

    svc = ContributionService()
    cid = uuid.UUID(contribution_id)

    async def _op(session):
        try:
            return await svc.approve(session, cid, user_id=SYSTEM_USER_ID, source="cli")
        except (ContributionError, ValueError) as exc:
            return exc

    result = _collab_op(_op)
    if isinstance(result, Exception):
        typer.echo(f"错误：{result}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"贡献 {contribution_id} 已审核通过。")


@contributions_app.command("merge")
def contributions_merge(contribution_id: str = typer.Argument(..., help="贡献 id。")) -> None:
    """合并贡献（approved -> merged）。

    注意：跨进程内存 stores 为空，实际合并需在 serve 进程内（stores 有数据时）；
    CLI merge 主要用于状态收尾与流程演示。
    """
    from calliodesmo.api.deps import get_app_stores
    from calliodesmo.auth.context import AccessContext
    from calliodesmo.auth.models import ClearanceLevel, Permission
    from calliodesmo.auth.service import get_access_context
    from calliodesmo.collab.merge import MergeService
    from calliodesmo.collab.models import Contribution
    from calliodesmo.collab.service import ContributionError

    merge_svc = MergeService()
    cid = uuid.UUID(contribution_id)

    async def _op(session):
        c = await session.get(Contribution, cid)
        if c is None:
            return None
        source_access = await get_access_context(session, c.source_user_id)
        if source_access is None:
            return None
        target_access = AccessContext(
            user_id=SYSTEM_USER_ID,
            username="system",
            clearance=ClearanceLevel.SECRET,
            permissions=frozenset({Permission.APPROVE}),
            project_ids=frozenset({c.target_project_id}) if c.target_project_id else frozenset(),
            team_ids=frozenset({c.target_team_id}) if c.target_team_id else frozenset(),
        )
        try:
            return await merge_svc.merge(
                session,
                cid,
                stores=get_app_stores(),
                source_access=source_access,
                target_access=target_access,
                source="cli",
            )
        except ContributionError as exc:
            return exc

    result = _collab_op(_op)
    if result is None:
        typer.echo(f"错误：贡献 {contribution_id} 或源用户不存在", err=True)
        raise typer.Exit(code=1)
    if isinstance(result, Exception):
        typer.echo(f"错误：{result}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"贡献 {contribution_id} 已合并。")


# ---- P4 抽取模板审核命令 ----


@templates_app.command("list-types")
def templates_list_types() -> None:
    """列出发现类型候选（跨进程内存 stores 为空，需 serve 进程内有数据）。"""
    from calliodesmo.api.deps import get_app_stores
    from calliodesmo.auth.context import AccessContext
    from calliodesmo.auth.models import ClearanceLevel, Permission
    from calliodesmo.collab.template_review import collect_discovered_types

    access = AccessContext(
        user_id=SYSTEM_USER_ID,
        username="system",
        clearance=ClearanceLevel.SECRET,
        permissions=frozenset({Permission.APPROVE}),
    )
    items = asyncio.run(collect_discovered_types(get_app_stores(), access=access))
    if not items:
        typer.echo("（无发现类型候选）")
        return
    for it in items:
        typer.echo(f"{it['type']}\t{it['count']}\t{it['status']}")


@templates_app.command("approve-type")
def templates_approve_type(
    team: str = typer.Option(..., "--team", help="团队 id。"),
    entity_type: str = typer.Option(..., "--type", help="批准的实体类型。"),
) -> None:
    """批准发现类型沉淀进团队模板 YAML（幂等）。"""
    from calliodesmo.ecl.extraction_template import ExtractionTemplateRegistry

    settings = get_settings()
    registry = ExtractionTemplateRegistry.from_yaml(settings.extraction_template_file)
    try:
        registry.sediment(team, [entity_type], path=settings.extraction_template_file)
    except RuntimeError as exc:
        typer.echo(f"错误：{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"类型 {entity_type} 已沉淀进团队 {team} 模板。")
