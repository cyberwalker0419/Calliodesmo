"""Calliodesmo CLI（Typer）：db init / db seed / serve / ingest。"""

import asyncio
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
    return stats


@app.command()
def ingest(
    path: str = typer.Argument(..., help="文档路径（文件或目录），按后缀自动分发加载器。"),
) -> None:
    """端到端建图落个人库：Load -> Extract -> Cognify -> Load -> 文档社区派生。

    输出统计并记审计。LLM 经 CALLIODESMO_LLM_MODEL/CALLIODESMO_LLM_API_KEY 配置；
    缺 key 时给出指引。内存 stores 为 P1 默认（离线可测）。
    """
    settings = get_settings()
    try:
        stats = asyncio.run(_run_ingest(path, settings, build_default_indexing_engine))
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
