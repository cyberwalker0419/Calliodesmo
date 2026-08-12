"""全链路仿真测试（full-chain simulation）—— HTTP 驱动的多用户协作贯通。

本脚本在**隔离 PG schema + 真后端 stores（pgvector / Neo4j / 远端 BGE-M3 嵌入） +
确定性 StubLLM 抽取**基线上，经 ASGI 客户端按真实用户路径驱动整条链路，逐请求
录制 transcript（method/path/status/timing/body 摘要）到 data/sim/ 产物。

仿真剧本（六幕）：
  A. 认证：健康检查 -> 错误密码 401 -> 正确登录 -> /auth/me 身份
  B. 摄入：POST /ingest（ECL: load->chunk->extract->cognify->community->落 PG+Neo4j）
  C. 问答：/query 三模式（native_rag / local / global）检索->重排->合成
  D. 协作推送：/collab create->diff->submit->approve->merge（跨 store PG+Neo4j 双写）
  E. 持久化重启：reset_app_stores（模拟进程重启）-> 项目库数据仍可读 + 命中检索
  F. 权限隔离：analyst-B 看不到 analyst-A 个人库；analyst-A 无 approve 权限 -> 403；
     伪造 token -> 401

确定性取舍：LLM 用 StubLLM（test/stub）保证可复现；嵌入用远端真 BGE-M3（pgvector
真向量检索）；stores 全真后端。这是对"全链路 plumbing"的端到端硬证明，LLM 文本质量
属 P2 评估 harness 范畴，不在本仿真目标内。

用法：uv run python scripts/full_chain_simulation.py
产物：data/sim/fullchain-transcript.json + data/sim/fullchain-transcript.log
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

# ---------- 1. 环境覆盖（必须在 import calliodesmo 之前） ----------
_SIM_SECRET = "fullchain-sim-secret-0123456789abcdef"
os.environ["CALLIODESMO_JWT_SECRET_KEY"] = _SIM_SECRET
# 真后端路由：三主 store 走 PG / Neo4j
os.environ["CALLIODESMO_VECTOR_STORE_BACKEND"] = "postgres"
os.environ["CALLIODESMO_GRAPH_STORE_BACKEND"] = "neo4j"
os.environ["CALLIODESMO_COMMUNITY_STORE_BACKEND"] = "postgres"
# 确定性抽取（真 LLM 文本质量不在本仿真目标内）
os.environ["CALLIODESMO_LLM_MODEL"] = "test/stub"
# 嵌入保持远端真 BGE-M3（.env 已配 192.168.50.97:8082）

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.api.app import create_app
from calliodesmo.api.deps import reset_app_stores
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.auth.service import (
    add_project_member,
    assign_role,
    create_project,
    create_team,
    create_user,
    seed_default_roles,
)
from calliodesmo.config import get_settings
from calliodesmo.db import session as dbsess
from calliodesmo.db.base import Base
from calliodesmo.db.session import get_session

get_settings.cache_clear()
settings = get_settings()

SCHEMA = f"fullchain_sim_{uuid.uuid4().hex[:10]}"
ARTIFACT_DIR = Path("data/sim")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = ARTIFACT_DIR / "fullchain-transcript.log"
JSON_PATH = ARTIFACT_DIR / "fullchain-transcript.json"

# 仿真语料（中英双语，含明确实体/关系供抽取）
DOC_MD = """# Calliodesmo 平台概述

Calliodesmo 是一个三层知识图谱情报分析平台，由 Anthropic 研发的 Claude 模型驱动。

平台把原始文档加工成三层结构：情景层、语义层与社区摘要层。情景层基于 PostgreSQL
与 pgvector 存储文本块向量；语义层用 Neo4j 维护实体关系图；摘要层在 Postgres 中
保存社区摘要。

Claude 是 Anthropic 开发的大语言模型。Calliodesmo 使用 Claude 进行实体抽取、社区
摘要与最终答案合成。GPT-4 是 OpenAI 开发的竞品模型，用于对比评估。
"""


# ---------- 2. 录制器 ----------
class Recorder:
    def __init__(self) -> None:
        self.records: list[dict] = []
        self._t0 = time.perf_counter()

    def log(self, kind: str, **fields) -> None:
        rec = {"t": round(time.perf_counter() - self._t0, 3), "kind": kind, **fields}
        self.records.append(rec)
        line = self._format(rec)
        print(line, flush=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    @staticmethod
    def _format(rec: dict) -> str:
        t = rec.get("t")
        kind = rec.get("kind")
        if kind == "req":
            body = rec.get("body")
            return (
                f"[{t:>7.2f}s] REQ  {rec['method']:6s} {rec['path']}"
                f" -> {rec['status']} ({rec['ms']:.0f}ms)" + (f" :: {body}" if body else "")
            )
        if kind == "section":
            return f"\n=== [{t:>7.2f}s] >>> {rec['title']} ==="
        return f"[{t:>7.2f}s] {kind}: {rec.get('msg', '')}"


R = Recorder()


def _truncate(s: str, n: int = 160) -> str:
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


# ---------- 3. 隔离 schema 引擎 ----------
async def setup_schema() -> async_sessionmaker:
    """创建隔离 schema 并 create_all；返回绑定 search_path 的 DML 会话工厂。"""
    setup_eng = create_async_engine(settings.database_url, pool_pre_ping=True)
    async with setup_eng.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
        await conn.execute(text(f'SET search_path TO "{SCHEMA}"'))
        await conn.run_sync(Base.metadata.create_all)
    await setup_eng.dispose()
    dml = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": f"{SCHEMA},public"}},
    )
    return async_sessionmaker(dml, expire_on_commit=False)


async def drop_schema() -> None:
    eng = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with eng.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
    finally:
        await eng.dispose()


# ---------- 4. Neo4j 清图 ----------
async def clear_neo4j() -> None:
    from neo4j import AsyncGraphDatabase

    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        await driver.verify_connectivity()
        async with driver.session() as s:
            await s.run("MATCH (n) DETACH DELETE n")
    finally:
        await driver.close()


# ---------- 5. 种子：角色 + 三用户 + 团队/项目 + 成员关系 ----------
async def seed_world(factory: async_sessionmaker) -> dict:
    async with factory() as s:
        await seed_default_roles(s)
        # analyst-A：个人库主角
        a = await create_user(
            s, username="aaron", password="aaron-pw", clearance=ClearanceLevel.SECRET
        )
        await assign_role(s, user=a, role_name="analyst", scope=LibraryScope.PERSONAL)
        # analyst-B：隔离对照（看不到 A 的数据）
        b = await create_user(
            s, username="blake", password="blake-pw", clearance=ClearanceLevel.SECRET
        )
        await assign_role(s, user=b, role_name="analyst", scope=LibraryScope.PERSONAL)
        # reviewer：审核 + 项目成员（合并目标库可见）
        rev = await create_user(
            s, username="rita", password="rita-pw", clearance=ClearanceLevel.SECRET
        )
        await assign_role(s, user=rev, role_name="reviewer", scope=LibraryScope.PROJECT)
        team = await create_team(s, name="intel-team")
        project = await create_project(s, name="intel-project", team=team)
        await add_project_member(
            s, user=rev, project=project, role_name="reviewer", role_in_project="curator"
        )
        await s.commit()
        return {"aaron": a.id, "blake": b.id, "rita": rev.id, "project": project.id}


# ---------- 6. HTTP 调用 helper（带录制） ----------
async def call(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    token: str | None = None,
    json_body: dict | None = None,
    data: dict | None = None,
    files: dict | None = None,
    headers: dict | None = None,
    expect: int | None = None,
) -> httpx.Response:
    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    t0 = time.perf_counter()
    resp = await client.request(method, path, json=json_body, data=data, files=files, headers=h)
    ms = (time.perf_counter() - t0) * 1000
    snippet = ""
    try:
        body = resp.json()
        snippet = _truncate(json.dumps(body, ensure_ascii=False))
    except Exception:
        snippet = _truncate(resp.text)
    R.log(
        "req",
        method=method,
        path=path,
        status=resp.status_code,
        ms=ms,
        body=snippet,
    )
    if expect is not None and resp.status_code != expect:
        R.log("warn", msg=f"预期 {expect} 实得 {resp.status_code} @ {method} {path}")
    return resp


# ---------- 7. 主仿真 ----------
async def main() -> int:
    R.log("section", title="幕 0：环境就绪（隔离 schema + Neo4j 清图 + 种子）")
    factory = await setup_schema()
    await clear_neo4j()
    # 让 AppStores 动态 import 的 SessionLocal 指向隔离工厂
    dbsess.SessionLocal = factory
    ids = await seed_world(factory)
    R.log(
        "info",
        msg=(
            f"schema={SCHEMA}  aaron={ids['aaron']}  rita={ids['rita']}  "
            f"project={ids['project']}  llm=test/stub  embedding=remote(bge-m3)"
        ),
    )

    # 构 app，覆盖 get_session（请求级会话走隔离工厂）
    app = create_app()

    async def _override_session():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override_session
    reset_app_stores()  # 确保真后端 stores 在隔离工厂上重建

    transport = httpx.ASGITransport(app=app)
    failures: list[str] = []

    async with httpx.AsyncClient(transport=transport, base_url="http://sim") as client:
        # ---- 幕 A：认证 ----
        R.log("section", title="幕 A：认证（健康 / 错误密码 401 / 正确登录 / 身份）")
        await call(client, "GET", "/healthz", expect=200)

        r = await call(
            client,
            "POST",
            "/auth/token",
            data={"username": "aaron", "password": "WRONG"},
            expect=401,
        )
        if r.status_code != 401:
            failures.append("A: 错误密码未返回 401")

        r = await call(
            client,
            "POST",
            "/auth/token",
            data={"username": "aaron", "password": "aaron-pw"},
            expect=200,
        )
        token_a = r.json().get("access_token") if r.status_code == 200 else None
        if not token_a:
            failures.append("A: aaron 登录未拿到 token")
            return _finish(failures)

        await call(client, "GET", "/auth/me", token=token_a, expect=200)

        # ---- 幕 B：摄入（ECL 全链路 -> PG+Neo4j） ----
        R.log(
            "section",
            title="幕 B：摄入 /ingest（load->chunk->extract->cognify->community->落三层库）",
        )
        r = await call(
            client,
            "POST",
            "/ingest",
            token=token_a,
            files={"file": ("calliodesmo.md", DOC_MD.encode("utf-8"), "text/markdown")},
            expect=201,
        )
        stats = r.json() if r.status_code == 201 else {}
        R.log("info", msg=f"ingest 统计: {json.dumps(stats, ensure_ascii=False)}")

        # 直接查隔离 PG 取 doc_id（脚本拥有 engine，做校验用）
        async with factory() as s:
            doc_ids = [
                row[0]
                for row in (
                    await s.execute(text('SELECT DISTINCT doc_id FROM "chunks" ORDER BY 1'))
                ).fetchall()
            ]
            n_chunks = (await s.execute(text('SELECT COUNT(*) FROM "chunks"'))).scalar()
            # PG 镜像实体（Neo4j 权威，PG 为超集镜像）
            n_pg_ents = (await s.execute(text('SELECT COUNT(*) FROM "entities"'))).scalar()
            n_pg_rels = (await s.execute(text('SELECT COUNT(*) FROM "relations"'))).scalar()
            n_comms = (await s.execute(text('SELECT COUNT(*) FROM "communities"'))).scalar()
        R.log(
            "info",
            msg=(
                f"PG 直查: doc_ids={doc_ids}  chunks={n_chunks}  "
                f"pg_entities={n_pg_ents}  pg_relations={n_pg_rels}  communities={n_comms}"
            ),
        )
        if not doc_ids:
            failures.append("B: ingest 后无 doc_id（抽取/落库失败）")
            return _finish(failures)

        await call(client, "GET", "/library/communities", token=token_a, expect=200)

        # ---- 幕 C：问答三模式 ----
        R.log("section", title="幕 C：问答 /query（native_rag / local / global）")
        question = "Calliodesmo 用了哪些模型与存储技术？"
        for mode in ("native_rag", "local", "global"):
            r = await call(
                client,
                "POST",
                "/query",
                token=token_a,
                json_body={"question": question, "mode": mode, "top_k": 5},
            )
            if r.status_code == 200:
                body = r.json()
                R.log(
                    "info",
                    msg=(
                        f"[{mode}] sources={len(body.get('source_chunk_ids') or [])}  "
                        f"answer={_truncate(body.get('answer') or '', 120)}"
                    ),
                )

        # ---- 幕 D：协作推送（P4 全链路） ----
        R.log(
            "section",
            title="幕 D：协作推送 /collab（create->diff->submit->approve->merge）",
        )
        r = await call(
            client,
            "POST",
            "/collab",
            token=token_a,
            json_body={
                "source_scope": "personal",
                "target_scope": "project",
                "target_project_id": str(ids["project"]),
                "title": "Calliodesmo 概述文档",
                "doc_ids": doc_ids,
            },
            expect=201,
        )
        if r.status_code != 201:
            failures.append("D: 创建贡献失败")
            return _finish(failures)
        cid = r.json()["id"]

        await call(client, "GET", f"/collab/{cid}/diff", token=token_a)
        await call(client, "POST", f"/collab/{cid}/submit", token=token_a, expect=200)

        # reviewer 登录
        r = await call(
            client,
            "POST",
            "/auth/token",
            data={"username": "rita", "password": "rita-pw"},
            expect=200,
        )
        token_r = r.json().get("access_token") if r.status_code == 200 else None

        await call(client, "POST", f"/collab/{cid}/approve", token=token_r, expect=200)

        # 权限隔离：analyst-A 无 approve 权限 -> 403
        r = await call(client, "POST", f"/collab/{cid}/approve", token=token_a, expect=403)
        if r.status_code != 403:
            failures.append("F: analyst-A 审核未返回 403")

        r = await call(client, "POST", f"/collab/{cid}/merge", token=token_r, expect=200)
        merged = r.status_code == 200
        if not merged:
            failures.append("D: merge 未成功")

        # ---- 幕 E：持久化重启（reset_app_stores -> 全新 stores 实例读同一 PG/Neo4j） ----
        R.log(
            "section",
            title="幕 E：持久化重启（reset_app_stores 模拟进程退出 -> 项目库仍可读）",
        )
        reset_app_stores()
        if merged:
            r = await call(
                client,
                "GET",
                "/library/communities?scope=project",
                token=token_r,
                expect=200,
            )
            n_proj_comm = len(r.json()) if r.status_code == 200 else -1
            R.log("info", msg=f"重启后 reviewer 可见项目社区数: {n_proj_comm}")
            if n_proj_comm <= 0:
                failures.append("E: 重启后项目社区不可见（持久化失败）")

            r = await call(
                client,
                "POST",
                "/query",
                token=token_r,
                json_body={
                    "question": "Claude 是什么？",
                    "mode": "native_rag",
                    "top_k": 5,
                },
                expect=200,
            )
            if r.status_code == 200:
                R.log(
                    "info",
                    msg=(f"重启后项目库检索 sources={len(r.json().get('source_chunk_ids') or [])}"),
                )

        # ---- 幕 F：权限隔离 ----
        R.log(
            "section",
            title="幕 F：权限隔离（B 看不到 A 个人库 / 伪造 token 401）",
        )
        r = await call(
            client,
            "POST",
            "/auth/token",
            data={"username": "blake", "password": "blake-pw"},
            expect=200,
        )
        token_b = r.json().get("access_token") if r.status_code == 200 else None
        if token_b:
            r = await call(client, "GET", "/library/communities", token=token_b, expect=200)
            n_b_comm = len(r.json())
            R.log(
                "info",
                msg=f"analyst-B 可见社区数（应为 0，看不到 A 的个人库）: {n_b_comm}",
            )
            if n_b_comm != 0:
                failures.append(f"F: analyst-B 看到非预期社区 {n_b_comm} 条（隔离失败）")

        await call(client, "GET", "/auth/me", token="not.a.real.token", expect=401)
        await call(client, "GET", "/auth/me", expect=401)

    return _finish(failures)


def _finish(failures: list[str]) -> int:
    R.log("section", title="仿真结束，汇总")
    summary = {
        "schema": SCHEMA,
        "total_steps": sum(1 for r in R.records if r.get("kind") == "req"),
        "failures": failures,
        "artifacts": {
            "log": str(LOG_PATH),
            "json": str(JSON_PATH),
        },
    }
    R.log("result", msg=json.dumps(summary, ensure_ascii=False))
    JSON_PATH.write_text(json.dumps(R.records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n产物:\n  {LOG_PATH}\n  {JSON_PATH}")
    print(f"结论: {'全链路通过' if not failures else f'{len(failures)} 项失败'}")
    for f in failures:
        print(f"  - FAIL: {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    finally:
        # 幕外清理：drop schema + 清 Neo4j（不残留）
        try:
            asyncio.run(drop_schema())
        except Exception as exc:
            print(f"[teardown] drop schema 失败: {exc}", file=sys.stderr)
        try:
            asyncio.run(clear_neo4j())
        except Exception as exc:
            print(f"[teardown] clear neo4j 失败: {exc}", file=sys.stderr)
    sys.exit(code)
