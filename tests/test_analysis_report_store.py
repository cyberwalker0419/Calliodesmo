"""报告持久化测试（P6 Task 12）：AnalysisReportORM + AnalysisReportStore + 密级继承落库。

走真实 PG（``session`` 夹具，专用 schema ``calliodesmo_test`` 每测 TRUNCATE），覆盖
（对齐计划 Task 12 Step 1）：

- ``import calliodesmo.models`` 覆盖新表（漏注册即红——测试直接导入 ``db/models_analysis``
  亦会注册进 ``Base.metadata``，故另断言 ``calliodesmo.models`` 模块导出与 ``__all__``）；
- ORM 建表 + 三维权限五字段默认值（library_scope=personal / access_level 下限 internal /
  project_id / team_id 可空为 None）+ 复合索引 ``ix_analysis_reports_owner_created`` 存在；
- ``visible_to`` 谓词联动——三维权限五字段齐备，``AccessOwned`` Protocol 鸭子类型直接生效：
  personal 报告他人不可见（即便高密级）；低 clearance 看不到高密报告（本人亦不可见）；
- ``json_safe`` 写入往返——payload 含 UUID / datetime / Enum，落库前清洗为 JSON 可序列化；
- ReportStore ``create`` / ``get`` / ``list_visible``：create 固定 scope=personal +
  owner=提交者（决策 4），落库口径仅 ok / partial 落行（failed 拒绝，完全失败走 job failed，
  Task 13 消费）；get 不可见返回 None（API 层转 404 不泄漏存在性）；list_visible 三维过滤
  + limit/offset 分页（items + total）+ created_at 降序。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, select

import calliodesmo.models  # 注册全部 ORM 模型（漏注册本测试即红）
from calliodesmo.analysis.report_store import AnalysisReportStore
from calliodesmo.analysis.schemas import AnalysisType
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.db.base import Base
from calliodesmo.db.models_analysis import AnalysisReportORM
from calliodesmo.stores.visibility import visible_to

_store = AnalysisReportStore()


def _ctx(user_id, *, clearance: ClearanceLevel = ClearanceLevel.SECRET) -> AccessContext:
    return AccessContext(
        user_id=user_id,
        username="u",
        clearance=clearance,
        permissions=frozenset(),
        project_ids=frozenset(),
        team_ids=frozenset(),
    )


async def _create_report(
    session,
    *,
    user_id,
    task_type: AnalysisType = AnalysisType.SUMMARY,
    status: str = "ok",
    access_level: ClearanceLevel = ClearanceLevel.INTERNAL,
    subject_label: str = "文档A 摘要",
    payload: dict | None = None,
    source_doc_ids: list[str] | None = None,
    source_chunk_count: int = 3,
    model: str = "test/stub",
    prompt_version: str = "summary.v1",
    usage: dict[str, int] | None = None,
    job_id: uuid.UUID | None = None,
) -> AnalysisReportORM:
    """ReportStore.create 便捷包装（默认值覆盖多数用例）。"""
    return await _store.create(
        session,
        job_id=job_id,
        user_id=user_id,
        task_type=task_type,
        status=status,
        subject_label=subject_label,
        payload=payload if payload is not None else {"summary": "s", "key_points": []},
        source_doc_ids=source_doc_ids if source_doc_ids is not None else ["doc-1"],
        source_chunk_count=source_chunk_count,
        access_level=access_level,
        model=model,
        prompt_version=prompt_version,
        usage=usage if usage is not None else {"prompt_tokens": 10, "completion_tokens": 5},
    )


# ---------- models.py 集中注册（漏注册即红） ----------


def test_models_registration_covers_analysis_reports() -> None:
    """``calliodesmo.models`` 无条件导出 AnalysisReportORM 且表进 Base.metadata。"""
    assert hasattr(calliodesmo.models, "AnalysisReportORM")
    assert calliodesmo.models.AnalysisReportORM is AnalysisReportORM
    assert "AnalysisReportORM" in calliodesmo.models.__all__
    assert "analysis_reports" in Base.metadata.tables


def test_composite_index_owner_created_exists() -> None:
    """复合索引 ix_analysis_reports_owner_created(owner_id, created_at)（历史列表主查询）。"""
    table = Base.metadata.tables["analysis_reports"]
    names = {idx.name for idx in table.indexes}
    assert "ix_analysis_reports_owner_created" in names
    idx = next(i for i in table.indexes if i.name == "ix_analysis_reports_owner_created")
    assert [c.name for c in idx.columns] == ["owner_id", "created_at"]


# ---------- ORM 建表 + 五字段默认值 ----------


async def test_orm_defaults_five_access_fields(session) -> None:
    """直接经 ORM 建行验证默认值：scope 恒 personal、access_level 下限 internal、
    project_id / team_id 可空为 None（personal 报告不进项目 / 团队库）。"""
    user_id = uuid.uuid4()
    report = AnalysisReportORM(
        user_id=user_id,
        owner_id=user_id,
        task_type="summary",
        status="ok",
        subject_label="t",
        payload={"summary": "s"},
        source_doc_ids=["doc-1"],
        source_chunk_count=1,
        model="test/stub",
        prompt_version="summary.v1",
        usage_={"prompt_tokens": 1},
    )
    session.add(report)
    await session.flush()

    assert report.id is not None
    assert report.library_scope == LibraryScope.PERSONAL
    assert report.access_level == ClearanceLevel.INTERNAL
    assert report.project_id is None
    assert report.team_id is None
    assert report.job_id is None
    assert report.created_at is not None

    # 五字段齐备 -> visible_to 的 AccessOwned Protocol 鸭子类型直接生效
    assert visible_to(report, _ctx(user_id)) is True
    assert visible_to(report, _ctx(uuid.uuid4())) is False


# ---------- json_safe 写入往返 ----------


async def test_create_json_safe_roundtrip(session) -> None:
    """payload / usage 写入前必过 json_safe：UUID / datetime / Enum 清洗为 JSON 可序列化。"""
    user_id = uuid.uuid4()
    when = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
    rid = uuid.uuid4()
    report = await _create_report(
        session,
        user_id=user_id,
        payload={
            "ref_id": rid,
            "generated": when,
            "scope": LibraryScope.PERSONAL,
            "nested": {"ids": [rid], "at": when},
        },
        usage={"prompt_tokens": 3, "completion_tokens": 2},
    )
    await session.commit()

    got = (
        await session.execute(select(AnalysisReportORM).where(AnalysisReportORM.id == report.id))
    ).scalar_one()
    assert got.payload["ref_id"] == str(rid)
    assert got.payload["generated"] == when.isoformat()
    assert got.payload["scope"] == LibraryScope.PERSONAL.value
    assert got.payload["nested"]["ids"] == [str(rid)]
    assert got.payload["nested"]["at"] == when.isoformat()
    assert got.usage_ == {"prompt_tokens": 3, "completion_tokens": 2}
    assert got.source_doc_ids == ["doc-1"]


# ---------- 落库口径：仅 ok / partial 落行 ----------


@pytest.mark.parametrize("status", ["ok", "partial"])
async def test_create_accepts_ok_and_partial(session, status: str) -> None:
    user_id = uuid.uuid4()
    report = await _create_report(session, user_id=user_id, status=status)
    assert report.status == status


async def test_create_rejects_failed_status(session) -> None:
    """完全失败不落空报告（走 job failed + error，Task 13 消费；见计划「报告落库口径」）。"""
    with pytest.raises(ValueError, match="failed"):
        await _create_report(session, user_id=uuid.uuid4(), status="failed")


async def test_create_rejects_unknown_status_and_task_type(session) -> None:
    user_id = uuid.uuid4()
    with pytest.raises(ValueError, match="status"):
        await _create_report(session, user_id=user_id, status="weird")
    with pytest.raises(ValueError, match="task_type"):
        await _store.create(
            session,
            job_id=None,
            user_id=user_id,
            task_type="not_a_type",
            status="ok",
            subject_label="t",
            payload={},
            source_doc_ids=[],
            source_chunk_count=0,
            access_level=ClearanceLevel.INTERNAL,
            model="m",
            prompt_version="p",
            usage={},
        )


# ---------- create 固定 personal scope + owner=提交者（决策 4） ----------


async def test_create_fixed_personal_scope_and_owner(session) -> None:
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    report = await _create_report(
        session, user_id=user_id, job_id=job_id, access_level=ClearanceLevel.SECRET
    )
    assert report.library_scope == LibraryScope.PERSONAL
    assert report.owner_id == user_id
    assert report.user_id == user_id
    assert report.project_id is None
    assert report.team_id is None
    assert report.job_id == job_id
    assert report.access_level == ClearanceLevel.SECRET  # 密级继承由调用方（worker）算得传入


# ---------- visible_to 联动：personal 他人不可见 + 低 clearance 看不到高密 ----------


async def test_visibility_personal_invisible_to_others(session) -> None:
    owner = uuid.uuid4()
    other = uuid.uuid4()
    report = await _create_report(session, user_id=owner)

    assert visible_to(report, _ctx(owner, clearance=ClearanceLevel.INTERNAL)) is True
    # 他人即便高密级也看不到 personal 报告
    assert visible_to(report, _ctx(other, clearance=ClearanceLevel.SECRET)) is False


async def test_visibility_low_clearance_cannot_see_high_report(session) -> None:
    owner = uuid.uuid4()
    report = await _create_report(session, user_id=owner, access_level=ClearanceLevel.SECRET)

    # 本人低 clearance 同样不可见（密级不洗白，决策 4）
    assert visible_to(report, _ctx(owner, clearance=ClearanceLevel.INTERNAL)) is False
    assert visible_to(report, _ctx(owner, clearance=ClearanceLevel.SECRET)) is True


# ---------- get：可见返回行，不可见返回 None（不泄漏存在性） ----------


async def test_get_visibility(session) -> None:
    owner = uuid.uuid4()
    other = uuid.uuid4()
    report = await _create_report(session, user_id=owner, access_level=ClearanceLevel.CONFIDENTIAL)

    got = await _store.get(session, report.id, access=_ctx(owner, clearance=ClearanceLevel.SECRET))
    assert got is not None and got.id == report.id

    # 他人 -> None；本人低 clearance -> None；不存在 id -> None
    assert await _store.get(session, report.id, access=_ctx(other)) is None
    assert (
        await _store.get(session, report.id, access=_ctx(owner, clearance=ClearanceLevel.INTERNAL))
        is None
    )
    assert await _store.get(session, uuid.uuid4(), access=_ctx(owner)) is None


# ---------- list_visible：三维过滤 + 分页 ----------


async def test_list_visible_three_dim_filter(session) -> None:
    owner = uuid.uuid4()
    other = uuid.uuid4()
    # 本人可见 3 条（internal / confidential / secret 各一）
    await _create_report(session, user_id=owner, access_level=ClearanceLevel.INTERNAL)
    await _create_report(session, user_id=owner, access_level=ClearanceLevel.CONFIDENTIAL)
    await _create_report(session, user_id=owner, access_level=ClearanceLevel.SECRET)
    # 本人低密报告 1 条（低 clearance 上下文才可见）
    await _create_report(session, user_id=owner, access_level=ClearanceLevel.PUBLIC)
    # 他人报告 2 条（personal scope 不可见）
    await _create_report(session, user_id=other, access_level=ClearanceLevel.INTERNAL)
    await _create_report(session, user_id=other, access_level=ClearanceLevel.PUBLIC)

    items, total = await _store.list_visible(session, access=_ctx(owner))
    assert total == 4  # 他人 2 条被 scope 滤掉
    assert {r.owner_id for r in items} == {owner}

    # 低 clearance：仅 PUBLIC + INTERNAL 可见（clearance 维度过滤）
    items_low, total_low = await _store.list_visible(
        session, access=_ctx(owner, clearance=ClearanceLevel.INTERNAL)
    )
    assert total_low == 2
    assert all(r.access_level <= ClearanceLevel.INTERNAL for r in items_low)

    # 第三用户：什么都看不见
    items_none, total_none = await _store.list_visible(session, access=_ctx(uuid.uuid4()))
    assert items_none == [] and total_none == 0


async def test_list_visible_pagination(session) -> None:
    owner = uuid.uuid4()
    for i in range(5):
        await _create_report(session, user_id=owner, subject_label=f"报告-{i}")
        await session.commit()  # 逐条提交拉开 created_at，保证排序可断言

    page1, total1 = await _store.list_visible(session, access=_ctx(owner), limit=2, offset=0)
    page2, total2 = await _store.list_visible(session, access=_ctx(owner), limit=2, offset=2)
    page3, total3 = await _store.list_visible(session, access=_ctx(owner), limit=2, offset=4)

    assert total1 == total2 == total3 == 5
    assert [len(page1), len(page2), len(page3)] == [2, 2, 1]
    # 页间无重叠、无遗漏
    all_ids = [r.id for r in page1 + page2 + page3]
    assert len(set(all_ids)) == 5
    # created_at 降序（历史列表主查询，复合索引 ix_analysis_reports_owner_created）
    stamps = [r.created_at for r in page1 + page2 + page3]
    assert stamps == sorted(stamps, reverse=True)

    # offset 越界 -> 空页 + total 不变
    empty, total_empty = await _store.list_visible(session, access=_ctx(owner), limit=2, offset=99)
    assert empty == [] and total_empty == 5


async def test_list_visible_rejects_bad_pagination(session) -> None:
    with pytest.raises(ValueError):
        await _store.list_visible(session, access=_ctx(uuid.uuid4()), limit=0)
    with pytest.raises(ValueError):
        await _store.list_visible(session, access=_ctx(uuid.uuid4()), limit=10, offset=-1)


# ---------- 表结构经真 PG inspect 核对（建表落地证据） ----------


async def test_table_columns_in_pg(_pg_engine) -> None:
    """真 PG 建表后列齐全（含 usage_ 列名与五字段），核对计划表结构。"""

    def _columns(sync_conn) -> set[str]:
        return {c["name"] for c in inspect(sync_conn).get_columns("analysis_reports")}

    async with _pg_engine.connect() as conn:
        cols = await conn.run_sync(_columns)
    expected = {
        "id",
        "job_id",
        "user_id",
        "task_type",
        "status",
        "subject_label",
        "payload",
        "source_doc_ids",
        "source_chunk_count",
        "access_level",
        "library_scope",
        "owner_id",
        "project_id",
        "team_id",
        "model",
        "prompt_version",
        "usage_",
        "created_at",
    }
    assert expected <= cols
