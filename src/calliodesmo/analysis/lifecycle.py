"""P8 Task 6：报告生命周期（append-only 版本 / 软删除 / 复核状态机）。

设计（P8 关键决策 7）：
- **版本快照 append-only**：创建即写 v1；编辑 / 重分析 / 回滚各追加新版本，
  旧版本行不可变。回滚采用 append 式（同 P4 社区版本先例）——不以旧行覆盖，
  而是追加一个内容等于目标版本的新行；
- **软删除可恢复**：``deleted_at`` 置位后列表不可见、详情 404，恢复后可见；
  不硬删（审计链完整）；
- **复核状态机**：``draft → pending → approved / rejected``（拒绝可重提交），
  非法流转抛 ``ReviewTransitionError``（API 409）；复核需 ``APPROVE`` 权限；
- **并发**：报告行 ``lock_version`` 为 SQLAlchemy 乐观锁列，版本链写入经
  ``expected_lock_version`` 预检 + DB 唯一约束兜底；
- **权限**：版本 / 删除 / 恢复 / 提交复核限 owner；越权与不存在同一 404 语义；
- **审计**：每个动作 ``record_audit``（只记版本号 / 状态，不记报告原文）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from calliodesmo.analysis.report_store import AnalysisReportStore, build_snapshot
from calliodesmo.audit.service import record_audit
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope, Permission
from calliodesmo.db.models_analysis import AnalysisReportORM, AnalysisReportVersionORM
from calliodesmo.stores.visibility import visible_to

__all__ = [
    "ConcurrencyConflict",
    "ReportLifecycleError",
    "ReportNotFoundError",
    "ReviewTransitionError",
    "approve",
    "create_version",
    "list_versions",
    "reject",
    "restore",
    "rollback",
    "soft_delete",
    "submit_review",
]

#: 合法复核流转（draft → pending → approved / rejected；rejected → pending）
VALID_REVIEW_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"pending"}),
    "pending": frozenset({"approved", "rejected"}),
    "rejected": frozenset({"pending"}),
    "approved": frozenset(),
}


class ReportLifecycleError(ValueError):
    """生命周期领域错误基类。"""


class ReportNotFoundError(ReportLifecycleError):
    """报告 / 版本不存在或不可见（与越权同一语义，不泄漏存在性）。"""


class ReviewTransitionError(ReportLifecycleError):
    """非法复核状态流转。"""


class ConcurrencyConflict(ReportLifecycleError):
    """版本链并发冲突（乐观锁 / 唯一约束）。"""


async def _get_report(
    session: AsyncSession,
    report_id: uuid.UUID,
    access: AccessContext,
    *,
    include_deleted: bool = False,
) -> AnalysisReportORM:
    """取报告并做边界校验；不存在 / 不可见 / 已删除统一 404 语义。"""
    report = await AnalysisReportStore().get(
        session, report_id, access=access, include_deleted=include_deleted
    )
    if report is None:
        raise ReportNotFoundError(f"报告不存在或不可见: {report_id}")
    return report


def _require_owner(report: AnalysisReportORM, access: AccessContext) -> None:
    """版本 / 删除 / 恢复 / 提交复核限 owner（他人报告按不存在处理）。"""
    if report.owner_id != access.user_id:
        raise ReportNotFoundError(f"报告不存在或不可见: {report.id}")


def _check_lock(report: AnalysisReportORM, expected_lock_version: int | None) -> None:
    """乐观锁预检：调用方携带的版本与库中不一致即冲突。"""
    if expected_lock_version is not None and expected_lock_version != report.lock_version:
        raise ConcurrencyConflict(
            f"报告 {report.id} 版本链并发冲突：期望 lock_version={expected_lock_version}，"
            f"实际 {report.lock_version}"
        )


async def _flush(session: AsyncSession) -> None:
    """flush 并翻译 SQLAlchemy 乐观锁异常为领域错误。"""
    try:
        await session.flush()
    except StaleDataError as exc:  # 并发写：另一事务已推进 lock_version
        raise ConcurrencyConflict(f"报告版本链并发冲突：{exc}") from exc


async def create_version(
    session: AsyncSession,
    report_id: uuid.UUID,
    *,
    access: AccessContext,
    expected_lock_version: int | None = None,
    source: str = "service",
) -> AnalysisReportVersionORM:
    """追加当前报告状态为新版本（append-only；供编辑 / 重分析后调用）。"""
    report = await _get_report(session, report_id, access)
    _require_owner(report, access)
    _check_lock(report, expected_lock_version)
    report.current_version += 1
    version = AnalysisReportVersionORM(
        report_id=report.id,
        version=report.current_version,
        snapshot=build_snapshot(report),
        created_by=access.user_id,
    )
    session.add(version)
    await _flush(session)
    await record_audit(
        session,
        user_id=access.user_id,
        action="report_version",
        resource_type="analysis_report",
        resource_id=str(report.id),
        detail={"version": version.version},
        source=source,
    )
    return version


async def list_versions(
    session: AsyncSession,
    report_id: uuid.UUID,
    *,
    access: AccessContext,
) -> list[AnalysisReportVersionORM]:
    """列出报告版本链（新版本在前）；不可见 / 已软删除 → 404 语义。"""
    await _get_report(session, report_id, access)
    rows = (
        (
            await session.execute(
                select(AnalysisReportVersionORM)
                .where(AnalysisReportVersionORM.report_id == report_id)
                .order_by(AnalysisReportVersionORM.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def rollback(
    session: AsyncSession,
    report_id: uuid.UUID,
    *,
    version: int,
    access: AccessContext,
    expected_lock_version: int | None = None,
    source: str = "service",
) -> AnalysisReportVersionORM:
    """回滚到目标版本：append 一个内容等于目标快照的新版本并恢复报告状态。"""
    report = await _get_report(session, report_id, access)
    _require_owner(report, access)
    _check_lock(report, expected_lock_version)
    target = (
        await session.execute(
            select(AnalysisReportVersionORM).where(
                AnalysisReportVersionORM.report_id == report_id,
                AnalysisReportVersionORM.version == version,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise ReportNotFoundError(f"报告版本不存在: report={report_id} version={version}")

    report.current_version += 1
    _apply_snapshot(report, target.snapshot)
    new_version = AnalysisReportVersionORM(
        report_id=report.id,
        version=report.current_version,
        snapshot=dict(target.snapshot),
        created_by=access.user_id,
    )
    session.add(new_version)
    await _flush(session)
    await record_audit(
        session,
        user_id=access.user_id,
        action="report_rollback",
        resource_type="analysis_report",
        resource_id=str(report.id),
        detail={"from_version": version, "to_version": report.current_version},
        source=source,
    )
    return new_version


def _apply_snapshot(report: AnalysisReportORM, snapshot: dict) -> None:
    """把版本快照恢复到报告行（只恢复内容 / 运行记录，不改归属与创建时间）。"""
    report.payload = snapshot.get("payload") or {}
    report.verification = snapshot.get("verification")
    report.status = snapshot.get("status") or report.status
    report.subject_label = snapshot.get("subject_label") or report.subject_label
    report.model = snapshot.get("model") or report.model
    report.prompt_version = snapshot.get("prompt_version") or report.prompt_version
    report.usage_ = snapshot.get("usage") or {}
    report.source_doc_ids = snapshot.get("source_doc_ids") or []
    report.source_chunk_count = int(snapshot.get("source_chunk_count") or 0)
    access_level = snapshot.get("access_level")
    if access_level:
        report.access_level = ClearanceLevel(access_level)
    library_scope = snapshot.get("library_scope")
    if library_scope:
        report.library_scope = LibraryScope(library_scope)


async def soft_delete(
    session: AsyncSession,
    report_id: uuid.UUID,
    *,
    access: AccessContext,
    source: str = "service",
) -> AnalysisReportORM:
    """软删除：置 ``deleted_at``（可恢复；不硬删）。重复删除幂等。"""
    report = await _get_report(session, report_id, access, include_deleted=True)
    _require_owner(report, access)
    if report.deleted_at is None:
        report.deleted_at = datetime.now(UTC)
        await _flush(session)
        await record_audit(
            session,
            user_id=access.user_id,
            action="report_delete",
            resource_type="analysis_report",
            resource_id=str(report.id),
            detail={"deleted_at": report.deleted_at.isoformat()},
            source=source,
        )
    return report


async def restore(
    session: AsyncSession,
    report_id: uuid.UUID,
    *,
    access: AccessContext,
    source: str = "service",
) -> AnalysisReportORM:
    """恢复软删除报告；未删除时幂等返回。"""
    report = await _get_report(session, report_id, access, include_deleted=True)
    if not visible_to(report, access):
        raise ReportNotFoundError(f"报告不存在或不可见: {report_id}")
    _require_owner(report, access)
    if report.deleted_at is not None:
        report.deleted_at = None
        await _flush(session)
        await record_audit(
            session,
            user_id=access.user_id,
            action="report_restore",
            resource_type="analysis_report",
            resource_id=str(report.id),
            detail={"review_status": report.review_status},
            source=source,
        )
    return report


def _transition(report: AnalysisReportORM, target: str) -> None:
    """复核状态机流转校验（非法流转抛 409 语义错误）。"""
    current = report.review_status or "draft"
    if target not in VALID_REVIEW_TRANSITIONS.get(current, frozenset()):
        raise ReviewTransitionError(f"非法复核流转：{current} → {target}（报告 {report.id}）")


async def submit_review(
    session: AsyncSession,
    report_id: uuid.UUID,
    *,
    access: AccessContext,
    note: str | None = None,
    source: str = "service",
) -> AnalysisReportORM:
    """提交复核：draft / rejected → pending（owner 操作）。"""
    report = await _get_report(session, report_id, access)
    _require_owner(report, access)
    _transition(report, "pending")
    report.review_status = "pending"
    report.review_note = note
    report.reviewed_by = None
    report.reviewed_at = None
    await _flush(session)
    await record_audit(
        session,
        user_id=access.user_id,
        action="report_review_submit",
        resource_type="analysis_report",
        resource_id=str(report.id),
        detail={"to": "pending"},
        source=source,
    )
    return report


async def approve(
    session: AsyncSession,
    report_id: uuid.UUID,
    *,
    access: AccessContext,
    note: str | None = None,
    source: str = "service",
) -> AnalysisReportORM:
    """复核通过：pending → approved（需 APPROVE 权限）。"""
    return await _review_decision(
        session, report_id, access=access, target="approved", note=note, source=source
    )


async def reject(
    session: AsyncSession,
    report_id: uuid.UUID,
    *,
    access: AccessContext,
    note: str | None = None,
    source: str = "service",
) -> AnalysisReportORM:
    """复核拒绝：pending → rejected（需 APPROVE 权限；拒绝后可重提交）。"""
    return await _review_decision(
        session, report_id, access=access, target="rejected", note=note, source=source
    )


async def _review_decision(
    session: AsyncSession,
    report_id: uuid.UUID,
    *,
    access: AccessContext,
    target: str,
    note: str | None,
    source: str,
) -> AnalysisReportORM:
    """复核决策公共路径：可见性 + APPROVE 权限 + 状态机 + 审计。"""
    report = await _get_report(session, report_id, access)
    if not access.has_permission(Permission.APPROVE):
        raise ReportNotFoundError(f"报告不存在或不可见: {report_id}")
    _require_owner(report, access)
    _transition(report, target)
    report.review_status = target
    report.reviewed_by = access.user_id
    report.reviewed_at = datetime.now(UTC)
    report.review_note = note
    await _flush(session)
    await record_audit(
        session,
        user_id=access.user_id,
        action=f"report_review_{target}",
        resource_type="analysis_report",
        resource_id=str(report.id),
        detail={"to": target, "note": note or ""},
        source=source,
    )
    return report
