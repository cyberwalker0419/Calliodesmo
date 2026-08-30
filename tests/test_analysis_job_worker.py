"""Worker 分析执行路径测试（P6 Task 13）：状态机 / 进度分段 / 报告落库 / 终态审计。

走真实 PG（``session`` 夹具，专用 schema ``calliodesmo_test`` 每测 TRUNCATE）：
job / 报告 / 审计行走测试 schema——注入的 ``session_factory`` 由 ``_pg_engine`` 构造
（与 ``run_ingest_job`` 经 ``dependency_overrides[get_job_session_factory]`` 的同机制）；
材料走 ``get_app_stores()`` 内存向量库单例（``.env`` 未设 backend，默认 memory；worker
与端点同进程共享该单例，与 ``test_ingest_job_api.py`` 惯例一致）。``barrier`` 同步等待。

覆盖（对齐计划 Task 13 Step 1）：

- 状态机 pending -> succeeded / failed（终态经 barrier 等待后直查）；
- 进度分段 gather 10 -> prompt 25 -> llm 60 -> verify 80 -> persist 95 -> done 100
  （带 ``progress_stage``）；
- 成功路径：报告落库（密级继承 ``max(材料各级, INTERNAL)``、scope=personal、owner=提交者、
  信封带 ``generated_at``）+ ``Job.result={report_id, status}`` + 终态审计 ``analyze``
  （``resource_type="analysis_report"`` + report_id，detail 含 status/model/prompt_version）；
- partial 路径：证据失配超阈值 -> 报告如实落库（status=partial）+ job succeeded；
- 失败路径：``Job.error`` 可读 + 审计 failed（``resource_type="job"`` + error）+ 不落空报告；
- 空材料 -> failed("无可见材料")。

桩对生成质量零区分度：本文件只承诺状态机 / 契约 / 审计结构，不承诺分析质量。
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import calliodesmo.models  # noqa: F401  注册全部 ORM 模型
from calliodesmo.analysis.engine import DefaultAnalysisEngine
from calliodesmo.analysis.job_worker import run_analysis_job
from calliodesmo.api.deps import get_app_stores, reset_app_stores
from calliodesmo.audit.models import AuditLog
from calliodesmo.auth.models import (
    ClearanceLevel,
    LibraryScope,
    Permission,
    Role,
    RolePermission,
)
from calliodesmo.auth.service import assign_role, create_user, seed_default_roles
from calliodesmo.config import Settings, get_settings
from calliodesmo.db.models_analysis import AnalysisReportORM
from calliodesmo.db.models_job import Job, JobStatus
from calliodesmo.interfaces.analysis import AnalysisEngine
from calliodesmo.interfaces.graph_store import EntityRecord, RelationRecord
from calliodesmo.interfaces.llm import LLMProvider, LLMResponse
from calliodesmo.interfaces.vector_store import ChunkRecord
from calliodesmo.providers.stub_llm import StubLLMProvider

_DIM = get_settings().embedding_dimension


def _v() -> list[float]:
    """构造 _DIM 维向量（首位填 1，其余 0；内存库不校验维度，仅保形态）。"""
    vec = [0.0] * _DIM
    vec[0] = 1.0
    return vec


def _offline_settings(**overrides) -> Settings:
    """离线 settings：test/stub LLM + hash 嵌入（零网络零重依赖）。"""
    return Settings(
        llm_model="test/stub",
        analysis_model="",
        llm_api_key="",
        llm_api_base="",
        embedding_provider="hash",
    ).model_copy(update=overrides)


def _chunk(
    chunk_id: str,
    owner,
    *,
    doc_id: str,
    content: str,
    access_level=ClearanceLevel.INTERNAL,
    metadata=None,
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id=doc_id,
        content=content,
        vector=_v(),
        metadata=metadata if metadata is not None else {},
        access_level=access_level,
        library_scope=LibraryScope.PERSONAL,
        owner_id=owner,
        project_id=None,
        team_id=None,
    )


async def _seed_actor(session: AsyncSession, username: str, *, clearance=ClearanceLevel.SECRET):
    """建带 analyze 权限的 personal 角色用户（仿 test_ingest_job_api._seed_actor）。"""
    await seed_default_roles(session)
    role = Role(name=f"role-{username}", description="test")
    session.add(role)
    await session.flush()
    session.add(RolePermission(role_id=role.id, permission=Permission.ANALYZE))
    user = await create_user(session, username=username, password="pw-123456", clearance=clearance)
    await assign_role(session, user=user, role_name=f"role-{username}", scope=LibraryScope.PERSONAL)
    await session.commit()
    return user


def _job_factory(session: AsyncSession) -> async_sessionmaker:
    """注入式 worker 会话工厂：测试 schema 的 engine（与端点依赖覆盖同机制）。"""
    return async_sessionmaker(session.bind, expire_on_commit=False)  # type: ignore[arg-type]


def _engine(settings: Settings | None = None) -> DefaultAnalysisEngine:
    return DefaultAnalysisEngine(llm=StubLLMProvider(), settings=settings or _offline_settings())


async def _create_job(session: AsyncSession, user_id, payload: dict) -> Job:
    """建 analyze job 行（pending + task_payload，写入侧端点留 Task 14）。"""
    job = Job(user_id=user_id, task_type="analyze", task_payload=payload)
    session.add(job)
    await session.commit()
    return job


async def _run_worker(job_id: uuid.UUID, engine: AnalysisEngine, factory) -> None:
    """独立任务跑 worker，barrier 同步等待（仿 test_ingest_job_api 机制）。"""
    barrier = asyncio.Event()
    task = asyncio.create_task(
        run_analysis_job(job_id, engine=engine, session_factory=factory, barrier=barrier)
    )
    await asyncio.wait_for(barrier.wait(), timeout=60)
    await task  # worker 内部吞全部异常，此处仅确认协程收敛


async def _job_row(factory, job_id: uuid.UUID) -> Job:
    """以全新会话读 job 行（空 identity map，避免陈旧对象）。"""
    async with factory() as s:
        return (await s.execute(select(Job).where(Job.id == job_id))).scalar_one()


async def _report_rows(factory) -> list[AnalysisReportORM]:
    async with factory() as s:
        return list((await s.execute(select(AnalysisReportORM))).scalars().all())


async def _audit_rows(factory) -> list[AuditLog]:
    async with factory() as s:
        return list(
            (await s.execute(select(AuditLog).where(AuditLog.action == "analyze"))).scalars().all()
        )


@pytest.fixture(autouse=True)
def _fresh_stores():
    """每用例重置 AppStores 单例（内存向量库隔离）。"""
    reset_app_stores()
    yield
    reset_app_stores()


class _ScriptedLLM(LLMProvider):
    """脚本化假 provider：按调用次序返回预设原文（末条重复）。"""

    def __init__(self, outputs: list[str], model: str = "test/scripted"):
        self.outputs = list(outputs)
        self.model = model
        self.calls = 0

    async def complete(self, messages, *, temperature=0.2, max_tokens=None):
        self.calls += 1
        content = self.outputs[min(self.calls - 1, len(self.outputs) - 1)]
        return LLMResponse(
            content=content,
            model=self.model,
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        )


class _RecordingLLM(LLMProvider):
    """记录每次调用消息的 provider：返回固定合法 JSON（断言图谱上下文入提示词用）。"""

    def __init__(self, content: str, model: str = "test/recording"):
        self.content = content
        self.model = model
        self.calls: list[list] = []

    async def complete(self, messages, *, temperature=0.2, max_tokens=None):
        self.calls.append(list(messages))
        return LLMResponse(
            content=self.content,
            model=self.model,
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        )


class _BoomEngine(AnalysisEngine):
    """执行即抛错的坏引擎（失败路径用）。"""

    async def run(self, spec, materials, access):
        raise RuntimeError("引擎炸了（测试注入）")


# ---------------------------------------------------------------------------
# 成功路径：报告落库（密级继承 / personal / owner / 信封）+ result 指针 + 终态审计
# ---------------------------------------------------------------------------


async def test_success_path_persists_report_with_audit(session):
    """成功路径：succeeded + 报告落库（密级继承正确）+ result 指针 + 审计 analyze。"""
    user = await _seed_actor(session, "analyst-ok")
    # 他人块（可见性二次把关：不得进入材料 / 报告）
    other = await create_user(session, username="other", password="pw-123456")
    await session.commit()
    await get_app_stores().vector_store.upsert_chunks(
        [
            _chunk(
                "alpha.md#0",
                user.id,
                doc_id="alpha.md",
                content="阿尔法文档第一块。",
                metadata={"title": "Alpha 文档"},
            ),
            _chunk(
                "alpha.md#1",
                user.id,
                doc_id="alpha.md",
                content="阿尔法文档第二块。",
                metadata={"title": "Alpha 文档"},
            ),
            _chunk(
                "beta.md#0",
                user.id,
                doc_id="beta.md",
                content="贝塔文档高密块。",
                access_level=ClearanceLevel.SECRET,
                metadata={"title": "Beta 文档"},
            ),
            _chunk("gamma.md#0", other.id, doc_id="gamma.md", content="他人块。", metadata={}),
        ]
    )
    job = await _create_job(session, user.id, {"task_type": "summary", "doc_ids": []})
    factory = _job_factory(session)

    await _run_worker(job.id, _engine(), factory)

    # 状态机终态 + 进度 done 100 + result 最小指针
    row = await _job_row(factory, job.id)
    assert row.status == JobStatus.SUCCEEDED
    assert row.progress == 100
    assert row.progress_stage == "done"
    assert row.started_at is not None
    assert row.finished_at is not None
    assert row.error is None
    assert row.result is not None
    report_id = uuid.UUID(str(row.result["report_id"]))
    assert row.result["status"] == "ok"

    # 报告落库：密级继承 / scope=personal / owner=提交者
    async with factory() as s:
        report = (
            await s.execute(select(AnalysisReportORM).where(AnalysisReportORM.id == report_id))
        ).scalar_one()
    assert report.status == "ok"
    assert report.task_type == "summary"
    assert report.job_id == job.id
    assert report.user_id == user.id
    assert report.owner_id == user.id  # owner = 提交者（决策 4）
    assert report.library_scope == LibraryScope.PERSONAL
    assert report.project_id is None and report.team_id is None
    # 密级继承：max(材料各级, INTERNAL)，含 SECRET 块 -> SECRET
    assert report.access_level == ClearanceLevel.SECRET
    assert report.source_doc_ids == ["alpha.md", "beta.md"]
    assert report.source_chunk_count == 3
    assert report.model == "test/stub"
    assert report.prompt_version == "summary.v1"
    assert report.subject_label == "Alpha 文档、Beta 文档"

    # 信封装配：完整信封落 payload（含 generated_at），详情出参直接取信封
    envelope = report.payload
    assert envelope["task_type"] == "summary"
    assert envelope["status"] == "ok"
    assert envelope["generated_at"]  # json_safe 清洗后的 ISO 字符串
    assert envelope["model"] == "test/stub"
    assert envelope["prompt_version"] == "summary.v1"
    assert set(envelope["source_chunk_ids"]) == {"alpha.md#0", "alpha.md#1", "beta.md#0"}
    assert "gamma.md#0" not in envelope["source_chunk_ids"]  # 二次把关：他人块不入材料
    assert envelope["payload"]["summary"]  # SummaryReport 载荷落位

    # 终态审计：analyze + analysis_report + report_id，detail 含 status/model/prompt_version
    audits = await _audit_rows(factory)
    assert len(audits) == 1
    entry = audits[0]
    assert entry.action == "analyze"
    assert entry.resource_type == "analysis_report"
    assert entry.resource_id == str(report_id)
    assert entry.user_id == user.id
    assert entry.detail["status"] == "ok"
    assert entry.detail["model"] == "test/stub"
    assert entry.detail["prompt_version"] == "summary.v1"


async def test_doc_ids_membership_filter_from_task_payload(session):
    """task_payload.doc_ids 仅成员筛选：报告源文档与材料块仅含提交范围。"""
    user = await _seed_actor(session, "analyst-scope")
    await get_app_stores().vector_store.upsert_chunks(
        [
            _chunk("alpha.md#0", user.id, doc_id="alpha.md", content="甲。", metadata={}),
            _chunk("beta.md#0", user.id, doc_id="beta.md", content="乙。", metadata={}),
        ]
    )
    job = await _create_job(session, user.id, {"task_type": "summary", "doc_ids": ["alpha.md"]})
    factory = _job_factory(session)

    await _run_worker(job.id, _engine(), factory)

    row = await _job_row(factory, job.id)
    assert row.status == JobStatus.SUCCEEDED
    reports = await _report_rows(factory)
    assert len(reports) == 1
    assert reports[0].source_doc_ids == ["alpha.md"]
    assert reports[0].payload["source_chunk_ids"] == ["alpha.md#0"]


# ---------------------------------------------------------------------------
# 图谱复用：关系映射经图谱上下文折入材料后进引擎（Task 21，LLM 只组织不重新抽取）
# ---------------------------------------------------------------------------


async def test_relation_mapping_graph_context_folded_into_prompt(session):
    """关系映射图谱复用路径：图谱实体 / 关系折入材料 -> 进提示词 -> 报告落库。"""
    from calliodesmo.analysis.materials import GRAPH_CONTEXT_CHUNK_ID

    user = await _seed_actor(session, "analyst-relmap")
    await get_app_stores().vector_store.upsert_chunks(
        [
            _chunk(
                "alpha.md#0",
                user.id,
                doc_id="alpha.md",
                content="阿尔法文档第一块。",
                metadata={"title": "Alpha 文档"},
            )
        ]
    )
    # 图谱数据：可见且源块与材料块相交（采集器经 visible_to + 相交纳入图谱上下文）
    await get_app_stores().graph_store.upsert_graph(
        [
            EntityRecord(
                name="立项委员会",
                type="org",
                description="项目立项机构",
                source_chunk_ids=["alpha.md#0"],
                library_scope=LibraryScope.PERSONAL,
                owner_id=user.id,
            )
        ],
        [
            RelationRecord(
                source="立项委员会",
                target="合作机构",
                type="cooperate",
                description="联合研发",
                source_chunk_ids=["alpha.md#0"],
                library_scope=LibraryScope.PERSONAL,
                owner_id=user.id,
            )
        ],
    )
    valid = json.dumps(
        {
            "items": [
                {
                    "head": "立项委员会",
                    "tail": "合作机构",
                    "type": "cooperate",
                    "description": "图谱数据组织而来",
                    "confidence": 1.0,
                }
            ]
        },
        ensure_ascii=False,
    )
    llm = _RecordingLLM(valid)
    job = await _create_job(session, user.id, {"task_type": "relation_mapping", "doc_ids": []})
    factory = _job_factory(session)

    await _run_worker(job.id, DefaultAnalysisEngine(llm=llm, settings=_offline_settings()), factory)

    row = await _job_row(factory, job.id)
    assert row.status == JobStatus.SUCCEEDED
    # 图谱上下文进入提示词：user 消息含实体 / 关系数据（worker 折入材料后经引擎渲染）
    assert llm.calls, "引擎应至少调用一次 LLM"
    user_text = "\n".join(m.content for messages in llm.calls for m in messages if m.role == "user")
    assert "立项委员会" in user_text and "合作机构" in user_text
    assert "图谱上下文" in user_text
    # 报告落库：关系映射载荷 + 图谱伪块落 source_chunk_ids（真实块计数不受伪块影响）
    reports = await _report_rows(factory)
    assert len(reports) == 1
    report = reports[0]
    assert report.task_type == "relation_mapping"
    assert report.status == "ok"
    assert report.source_chunk_count == 1  # 仅真实材料块
    assert set(report.payload["source_chunk_ids"]) == {"alpha.md#0", GRAPH_CONTEXT_CHUNK_ID}
    assert report.payload["payload"]["items"][0]["head"] == "立项委员会"


# ---------------------------------------------------------------------------
# 进度分段：gather 10 -> prompt 25 -> llm 60 -> verify 80 -> persist 95 -> done 100
# ---------------------------------------------------------------------------


async def test_progress_stages_sequence(session, monkeypatch):
    """进度分段（带 progress_stage）：五段近似推进 + 终态 done 100。"""
    import calliodesmo.analysis.job_worker as worker_mod

    user = await _seed_actor(session, "analyst-stages")
    await get_app_stores().vector_store.upsert_chunks(
        [_chunk("a.md#0", user.id, doc_id="a.md", content="材料一。", metadata={})]
    )
    job = await _create_job(session, user.id, {"task_type": "summary", "doc_ids": []})
    factory = _job_factory(session)

    observed: list[tuple[str, int]] = []
    orig = worker_mod._update_job

    async def spy(sess, job_id, status, *, stage, progress):
        observed.append((stage, progress))
        await orig(sess, job_id, status, stage=stage, progress=progress)

    monkeypatch.setattr(worker_mod, "_update_job", spy)
    await _run_worker(job.id, _engine(), factory)

    assert observed == [
        ("gather", 10),
        ("prompt", 25),
        ("llm", 60),
        ("verify", 80),
        ("persist", 95),
    ]
    row = await _job_row(factory, job.id)
    assert row.progress_stage == "done"
    assert row.progress == 100


# ---------------------------------------------------------------------------
# partial 路径：证据失配超阈值 -> 报告如实落库 + job succeeded
# ---------------------------------------------------------------------------


async def test_partial_path_persists_report_and_job_succeeds(session):
    """partial 路径：报告落库（status=partial + warnings 可读）且 job succeeded。"""
    user = await _seed_actor(session, "analyst-partial")
    await get_app_stores().vector_store.upsert_chunks(
        [_chunk("doc.md#0", user.id, doc_id="doc.md", content="合同于二月签署。", metadata={})]
    )
    # 两条证据引文均非源文子串 -> 失配占比 100% > 30% -> verify_evidence 降 partial
    failing = json.dumps(
        {
            "summary": "桩摘要",
            "key_points": [],
            "confidence": 1.0,
            "evidence": [
                {"chunk_id": "doc.md#0", "quote": "源文中不存在的引文一", "confidence": 1.0},
                {"chunk_id": "doc.md#0", "quote": "源文中不存在的引文二", "confidence": 1.0},
            ],
        },
        ensure_ascii=False,
    )
    engine = DefaultAnalysisEngine(llm=_ScriptedLLM([failing]), settings=_offline_settings())
    job = await _create_job(session, user.id, {"task_type": "summary", "doc_ids": []})
    factory = _job_factory(session)

    await _run_worker(job.id, engine, factory)

    row = await _job_row(factory, job.id)
    assert row.status == JobStatus.SUCCEEDED
    assert row.result is not None
    assert row.result["status"] == "partial"
    reports = await _report_rows(factory)
    assert len(reports) == 1
    assert reports[0].status == "partial"
    assert reports[0].payload["status"] == "partial"
    assert reports[0].payload["warnings"]  # 证据失配告警可读
    audits = await _audit_rows(factory)
    assert len(audits) == 1
    assert audits[0].detail["status"] == "partial"


# ---------------------------------------------------------------------------
# 失败路径：Job.error 可读 + 审计 failed + 不落空报告
# ---------------------------------------------------------------------------


async def test_engine_exception_marks_failed_without_report(session):
    """引擎执行抛错 -> job failed + error 可读 + 审计 failed + 不落空报告。"""
    user = await _seed_actor(session, "analyst-boom")
    await get_app_stores().vector_store.upsert_chunks(
        [_chunk("a.md#0", user.id, doc_id="a.md", content="材料。", metadata={})]
    )
    job = await _create_job(session, user.id, {"task_type": "summary", "doc_ids": []})
    factory = _job_factory(session)

    await _run_worker(job.id, _BoomEngine(), factory)

    row = await _job_row(factory, job.id)
    assert row.status == JobStatus.FAILED
    assert "引擎炸了" in (row.error or "")
    assert await _report_rows(factory) == []  # 不落空报告
    audits = await _audit_rows(factory)
    assert len(audits) == 1
    assert audits[0].resource_type == "job"
    assert audits[0].resource_id == str(job.id)
    assert audits[0].detail["status"] == "failed"
    assert "引擎炸了" in audits[0].detail["error"]


async def test_engine_failed_status_marks_job_failed(session):
    """引擎返回 failed（解析预算耗尽）-> job failed + error 可读 + 不落报告。"""
    user = await _seed_actor(session, "analyst-parsefail")
    await get_app_stores().vector_store.upsert_chunks(
        [_chunk("a.md#0", user.id, doc_id="a.md", content="材料。", metadata={})]
    )
    engine = DefaultAnalysisEngine(
        llm=_ScriptedLLM(["完全不是 JSON 的散文输出"]),
        settings=_offline_settings(analysis_parse_retries=0),
    )
    job = await _create_job(session, user.id, {"task_type": "summary", "doc_ids": []})
    factory = _job_factory(session)

    await _run_worker(job.id, engine, factory)

    row = await _job_row(factory, job.id)
    assert row.status == JobStatus.FAILED
    assert "分析失败" in (row.error or "")
    assert await _report_rows(factory) == []
    audits = await _audit_rows(factory)
    assert len(audits) == 1
    assert audits[0].resource_type == "job"
    assert "分析失败" in audits[0].detail["error"]


async def test_empty_materials_marks_failed(session):
    """空材料 -> failed("无可见材料")：不落报告 + 审计 failed。"""
    user = await _seed_actor(session, "analyst-empty")
    job = await _create_job(session, user.id, {"task_type": "summary", "doc_ids": []})
    factory = _job_factory(session)

    await _run_worker(job.id, _engine(), factory)

    row = await _job_row(factory, job.id)
    assert row.status == JobStatus.FAILED
    assert "无可见材料" in (row.error or "")
    assert await _report_rows(factory) == []
    audits = await _audit_rows(factory)
    assert len(audits) == 1
    assert audits[0].resource_type == "job"
    assert "无可见材料" in audits[0].detail["error"]
