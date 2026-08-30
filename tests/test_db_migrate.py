"""P6 Task 11：Job 表泛化扩列 + db/migrate.py 幂等补列 + JobOut 扩展。

覆盖（对齐计划 Task 11 Step 1）：

- Job ORM 携带 ``task_type``（默认 ``ingest``）+ ``task_payload`` JSON
  （写入前过 ``json_safe`` 往返）；
- ``ensure_missing_columns`` 补列工具——旧结构 ``jobs`` 表（缺 ``task_type`` / ``task_payload``）
  → 补齐 → 断言新列存在且可插默认值；全新库经 ``create_all`` 直出完整结构，补齐路径纯 no-op；
- **列型回填**（承接 Task 1 留痕）——旧型 ``contributions`` 时间列（TIMESTAMP WITHOUT TZ）
  → 补齐 → 断言 TIMESTAMPTZ，幂等（已是 timestamptz 跳过），存量时刻按 UTC 解释不漂移；
- ``GET /jobs/{id}`` 对 analyze 返回 ``task_type`` 与自 ``result`` 指针解析的 ``report_id``，
  对 ingest 恒 ``task_type="ingest"`` 且 ``report_id=null``（防透传破坏旧消费方）；
- ``JobOut`` 默认值保旧响应消费方不破坏（纯 pydantic，离线可测）；
- ``reset_stale_running_jobs()`` 按状态不分类型，analyze 任务同样被清。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from calliodesmo.api.schemas import JobOut
from calliodesmo.auth.models import ClearanceLevel
from calliodesmo.auth.security import create_access_token
from calliodesmo.auth.service import create_user
from calliodesmo.config import get_settings
from calliodesmo.db.migrate import ensure_missing_columns
from calliodesmo.db.models_job import Job, JobStatus
from calliodesmo.utils.json import json_safe

# 旧结构 jobs 表（P6 Task 11 扩列前形态：无 task_type / task_payload）
_LEGACY_JOBS_DDL = """
CREATE TABLE jobs (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    filename VARCHAR(512) NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    progress INTEGER NOT NULL DEFAULT 0,
    progress_stage VARCHAR(64),
    result JSON,
    error TEXT,
    created_at TIMESTAMP DEFAULT now(),
    started_at TIMESTAMP,
    finished_at TIMESTAMP
)
"""

# 旧结构 contributions 时间列（P6 Task 1 前形态：TIMESTAMP WITHOUT TZ）
_LEGACY_CONTRIBUTIONS_DDL = """
CREATE TABLE contributions (
    id UUID PRIMARY KEY,
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    reviewed_at TIMESTAMP,
    merged_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    version INTEGER NOT NULL DEFAULT 1
)
"""


@pytest.fixture
async def legacy_db():
    """一次性旧结构 schema：legacy jobs / contributions 表 + search_path 绑定 engine。

    建表用独立一次性 engine（search_path 仅本 schema）；teardown DROP CASCADE 清场。
    """
    settings = get_settings()
    schema = f"mig_test_{uuid.uuid4().hex[:10]}"
    setup = create_async_engine(settings.database_url, pool_pre_ping=True)
    async with setup.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.execute(text(f'SET search_path TO "{schema}"'))
        await conn.execute(text(_LEGACY_JOBS_DDL))
        await conn.execute(text(_LEGACY_CONTRIBUTIONS_DDL))
    await setup.dispose()
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        yield engine, schema
    finally:
        await engine.dispose()
        cleanup = create_async_engine(settings.database_url, pool_pre_ping=True)
        try:
            async with cleanup.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            await cleanup.dispose()


# ---------- Job ORM 扩列 ----------


async def test_job_task_type_defaults_to_ingest(session):
    """ingest 链路零回归：不写 task_type 时默认 ``ingest``，task_payload 为空。"""
    job = Job(user_id=uuid.uuid4(), filename="a.md")
    session.add(job)
    await session.flush()
    assert job.task_type == "ingest"
    assert job.task_payload is None


async def test_job_task_payload_json_safe_roundtrip(session):
    """analyze 任务 task_payload 写入（过 json_safe）-> commit -> 读回一致。"""
    spec_like = {
        "task_type": "qa",
        "doc_ids": ["doc#1", "doc#2"],
        "question": "OpenAI 是什么？",
        "uid": uuid.uuid4(),  # json_safe -> str
        "submitted_at": datetime(2026, 8, 29, 12, 0, tzinfo=UTC),  # json_safe -> isoformat
    }
    job = Job(
        user_id=uuid.uuid4(),
        task_type="analyze",
        status=JobStatus.PENDING,
        task_payload=json_safe(spec_like),
    )
    session.add(job)
    await session.flush()  # id 为 Python 侧 default，flush 后才可取
    job_id = job.id
    await session.commit()
    session.expire_all()
    fetched = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()
    assert fetched.task_type == "analyze"
    assert fetched.task_payload["task_type"] == "qa"
    assert fetched.task_payload["doc_ids"] == ["doc#1", "doc#2"]
    assert fetched.task_payload["uid"] == str(spec_like["uid"])
    assert fetched.task_payload["submitted_at"] == spec_like["submitted_at"].isoformat()


# ---------- ensure_missing_columns：jobs 补列 ----------


async def _column_info(engine, schema: str, table: str) -> dict[str, dict]:
    """读 information_schema 列信息（表落指定 schema）。"""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable, column_default, "
                    "character_maximum_length "
                    "FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = :t"
                ),
                {"s": schema, "t": table},
            )
        ).fetchall()
    return {
        r[0]: {"data_type": r[1], "is_nullable": r[2], "default": r[3], "max_len": r[4]}
        for r in rows
    }


async def test_ensure_missing_columns_backfills_jobs(legacy_db):
    """旧结构 jobs 表 -> 补 task_type / task_payload -> 断言列形 + 存量行回填默认值。"""
    engine, schema = legacy_db
    # 存量行（扩列前写入）
    legacy_job_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO jobs (id, user_id, filename) VALUES (:i, :u, 'old.md')"),
            {"i": legacy_job_id, "u": uuid.uuid4()},
        )

    await ensure_missing_columns(engine)

    cols = await _column_info(engine, schema, "jobs")
    assert "task_type" in cols, "task_type 未补齐"
    assert cols["task_type"]["data_type"] == "character varying"
    assert cols["task_type"]["max_len"] == 16
    assert cols["task_type"]["is_nullable"] == "NO"
    assert "ingest" in (cols["task_type"]["default"] or "")
    assert "task_payload" in cols, "task_payload 未补齐"
    assert cols["task_payload"]["data_type"] == "json"
    assert cols["task_payload"]["is_nullable"] == "YES"

    # 存量行回填 server_default；新插入行同样取默认
    async with engine.begin() as conn:
        legacy_type = (
            await conn.execute(
                text("SELECT task_type FROM jobs WHERE id = :i"), {"i": legacy_job_id}
            )
        ).scalar_one()
        assert legacy_type == "ingest"
        new_id = uuid.uuid4()
        await conn.execute(
            text("INSERT INTO jobs (id, user_id, filename) VALUES (:i, :u, 'new.md')"),
            {"i": new_id, "u": uuid.uuid4()},
        )
        new_type = (
            await conn.execute(text("SELECT task_type FROM jobs WHERE id = :i"), {"i": new_id})
        ).scalar_one()
        assert new_type == "ingest"
        # task_type 索引随补齐建立（与 create_all 的 index=True 同名）
        index_names = {
            r[0]
            for r in (
                await conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = :s AND tablename = 'jobs'"
                    ),
                    {"s": schema},
                )
            ).fetchall()
        }
        assert "ix_jobs_task_type" in index_names


async def test_ensure_missing_columns_idempotent_on_legacy(legacy_db):
    """旧结构连跑两次：二次为纯 no-op，不报错、结构不变。"""
    engine, schema = legacy_db
    await ensure_missing_columns(engine)
    before = await _column_info(engine, schema, "jobs")
    await ensure_missing_columns(engine)  # 二次幂等
    after = await _column_info(engine, schema, "jobs")
    assert before == after


async def test_ensure_missing_columns_noop_on_fresh_db(_pg_engine):
    """全新库（create_all 直出完整结构）走补齐路径为纯 no-op，新列齐备。"""
    await ensure_missing_columns(_pg_engine)
    async with _pg_engine.connect() as conn:
        names = {
            r[0]
            for r in (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'calliodesmo_test' AND table_name = 'jobs'"
                    )
                )
            ).fetchall()
        }
    assert {"task_type", "task_payload"} <= names


# ---------- ensure_missing_columns：contributions 列型回填（承接 Task 1 留痕） ----------


async def test_contribution_time_columns_backfilled_to_timestamptz(legacy_db):
    """旧型 TIMESTAMP WITHOUT TZ 时间列 -> 回填 TIMESTAMPTZ（幂等 + 存量时刻不漂移）。"""
    engine, schema = legacy_db
    cid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO contributions (id, reviewed_at, merged_at) "
                "VALUES (:i, '2026-08-01 04:00:00', '2026-08-01 05:30:00')"
            ),
            {"i": cid},
        )

    await ensure_missing_columns(engine)

    cols = await _column_info(engine, schema, "contributions")
    for name in ("reviewed_at", "merged_at", "created_at", "updated_at"):
        assert cols[name]["data_type"] == "timestamp with time zone", (
            f"{name} 未回填 TIMESTAMPTZ：{cols[name]}"
        )

    # 存量时刻按 UTC 解释，回填后读回 aware 且时刻一致
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT reviewed_at, merged_at FROM contributions WHERE id = :i"),
                {"i": cid},
            )
        ).one()
    assert row[0] == datetime(2026, 8, 1, 4, 0, tzinfo=UTC)
    assert row[1] == datetime(2026, 8, 1, 5, 30, tzinfo=UTC)

    # 幂等：已是 timestamptz 跳过，重跑不报错
    await ensure_missing_columns(engine)
    cols_after = await _column_info(engine, schema, "contributions")
    assert cols == cols_after


# ---------- JobOut 兼容扩展（纯 pydantic，离线可测） ----------


def test_job_out_defaults_keep_legacy_consumers():
    """旧形状响应（无 task_type / report_id）经默认值补齐，旧消费方（useIngest.ts）不破坏。"""
    data = {
        "id": uuid.uuid4(),
        "filename": "a.md",
        "status": "succeeded",
        "progress": 100,
        "progress_stage": "done",
        "result": {"chunks": 3},
        "error": None,
        "created_at": datetime(2026, 8, 29, 12, 0),
        "started_at": None,
        "finished_at": None,
    }
    out = JobOut.model_validate(data)
    assert out.task_type == "ingest"
    assert out.report_id is None


# ---------- GET /jobs/{id} 透传 task_type / report_id ----------


async def _user_token(session, username: str) -> tuple[uuid.UUID, str]:
    """建最小用户 + token（GET /jobs/{id} 仅校验属主，无需角色权限）。"""
    user = await create_user(
        session, username=username, password="pw-123456", clearance=ClearanceLevel.INTERNAL
    )
    await session.commit()
    settings = get_settings()
    token = create_access_token(
        subject=str(user.id),
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expires_minutes=60,
    )
    return user.id, token


async def test_get_job_analyze_returns_task_type_and_report_id(session, client):
    """analyze 任务：task_type 透传 + report_id 自 result 最小指针解析。"""
    user_id, token = await _user_token(session, "job-analyze")
    report_id = uuid.uuid4()
    job = Job(
        user_id=user_id,
        task_type="analyze",
        status=JobStatus.SUCCEEDED,
        progress=100,
        progress_stage="done",
        result={"report_id": str(report_id), "status": "ok"},
    )
    session.add(job)
    await session.commit()
    resp = await client.get(f"/jobs/{job.id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["task_type"] == "analyze"
    assert body["report_id"] == str(report_id)
    assert body["status"] == "succeeded"


async def test_get_job_ingest_keeps_legacy_shape(session, client):
    """ingest 任务：恒 task_type="ingest" 且 report_id=null（防透传破坏旧消费方）。"""
    user_id, token = await _user_token(session, "job-ingest")
    job = Job(
        user_id=user_id,
        filename="a.md",
        status=JobStatus.SUCCEEDED,
        progress=100,
        progress_stage="done",
        result={"chunks": 2, "entities": 1},
    )
    session.add(job)
    await session.commit()
    resp = await client.get(f"/jobs/{job.id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["task_type"] == "ingest"
    assert body["report_id"] is None
    # 旧字段不动
    assert body["result"]["chunks"] == 2


# ---------- reset_stale_running_jobs：按状态不分类型 ----------


async def test_reset_stale_running_jobs_cleans_analyze(session, monkeypatch):
    """重启清残留按状态机生效：analyze running / ingest pending 均置 failed，终态不动。"""
    import sqlalchemy.ext.asyncio as sa_async

    real_create = sa_async.create_async_engine

    def patched_create_async_engine(url, **kwargs):
        # 路由到测试 schema（与 session 夹具同一库表）
        kwargs.setdefault("connect_args", {})["server_settings"] = {
            "search_path": "calliodesmo_test,public"
        }
        return real_create(url, **kwargs)

    monkeypatch.setattr(sa_async, "create_async_engine", patched_create_async_engine)

    uid = uuid.uuid4()
    running_analyze = Job(
        user_id=uid,
        task_type="analyze",
        status=JobStatus.RUNNING,
        progress=60,
        progress_stage="llm",
    )
    pending_ingest = Job(user_id=uid, filename="a.md", status=JobStatus.PENDING)
    done_analyze = Job(
        user_id=uid,
        task_type="analyze",
        status=JobStatus.SUCCEEDED,
        progress=100,
        result={"report_id": str(uuid.uuid4()), "status": "ok"},
    )
    session.add_all([running_analyze, pending_ingest, done_analyze])
    await session.commit()
    rid, iid, did = running_analyze.id, pending_ingest.id, done_analyze.id

    # 函数内部 asyncio.run 不能在运行中的事件循环里直调 -> 丢线程跑
    from calliodesmo.ecl.job_worker import reset_stale_running_jobs

    await asyncio.to_thread(reset_stale_running_jobs)

    session.expire_all()
    fetched = {
        j.id: j
        for j in (await session.execute(select(Job).where(Job.id.in_([rid, iid, did])))).scalars()
    }
    assert fetched[rid].status is JobStatus.FAILED
    assert fetched[rid].error, "analyze running 清理后须有可读 error"
    assert fetched[iid].status is JobStatus.FAILED
    assert fetched[did].status is JobStatus.SUCCEEDED  # 终态不动
