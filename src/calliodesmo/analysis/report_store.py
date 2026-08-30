"""分析报告存储：AnalysisReportStore（create / get / list_visible，PG 单后端）。

P6 Task 12（决策 2）：报告持久化为三维权限一等公民。循 ``collab/service.py`` ORM 直用
先例（方法接收 ``AsyncSession``），**不新增 AppStores 槽位**——报告是强持久产物走 PG
单后端，memory 后端徒增假可用；未来若需 memory 后端再抽象（留痕 2026-W49，见计划
架构节「不新增 AppStores 槽位」）。

三维权限过滤经 ``stores/visibility.py`` ``visible_to``：AnalysisReportORM 五字段齐备，
``AccessOwned`` Protocol 鸭子类型直接生效（personal 报告他人不可见；低 clearance 看不到
高密报告，本人亦不可见——密级不洗白）。``get`` 不可见返回 ``None``（API 层转 404，
不泄漏存在性，Task 14）；``list_visible`` 全量拉取 + ``visible_to`` 内存过滤 +
limit/offset 分页（报告行量级小，谓词下推不必，与三 store list 留痕同批 → P9 再评估）。

**报告落库口径**（计划「报告落库口径」）：``AnalysisStatus`` 契约枚举含
ok / partial / failed 三值（契约完整）；持久化规则为**仅 ok / partial 落报告行**
（用户可见降级原因而非黑洞），``create`` 拒收 ``failed``——解析彻底失败 / LLM 调用
异常等完全失败走 ``job failed`` + 可读 ``error`` + 审计记 failed，不落空报告
（Task 13 worker 消费本口径）。

密级继承（决策 4）：``access_level`` 由调用方（worker）经
``analysis/access.compute_report_access_level`` 算得传入；``create`` 固定
``library_scope=personal`` / ``owner_id=提交者`` / ``project_id=team_id=None``。
``payload`` 写入前必过 ``utils/json.py`` ``json_safe``（UUID / datetime / Enum 清洗）。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from calliodesmo.analysis.schemas import AnalysisStatus, AnalysisType
from calliodesmo.auth.context import AccessContext
from calliodesmo.auth.models import ClearanceLevel, LibraryScope
from calliodesmo.db.models_analysis import AnalysisReportORM
from calliodesmo.stores.visibility import visible_to
from calliodesmo.utils.json import json_safe

#: 允许落库的报告状态（落库口径：仅 ok / partial 落行，failed 走 job failed）
_PERSISTABLE_STATUSES: frozenset[str] = frozenset(
    {AnalysisStatus.OK.value, AnalysisStatus.PARTIAL.value}
)


class AnalysisReportStore:
    """分析报告存储（PG 单后端，循 collab/service.py ORM 直用先例）。"""

    async def create(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID | None,
        user_id: uuid.UUID,
        task_type: str | AnalysisType,
        status: str | AnalysisStatus,
        subject_label: str,
        payload: dict,
        source_doc_ids: Sequence[str],
        source_chunk_count: int,
        access_level: ClearanceLevel,
        model: str,
        prompt_version: str,
        usage: dict,
    ) -> AnalysisReportORM:
        """落一条报告行：固定 personal scope + owner=提交者（决策 4）。

        参数:
            job_id: 来源 job（可空；不建 FK，同 ``Job.user_id`` 无 FK 决策）。
            user_id: 提交者（``user_id`` 与 ``owner_id`` 同值）。
            task_type: 分析类型（须为 ``AnalysisType`` 合法值）。
            status: 仅接受 ``ok`` / ``partial``（落库口径；``failed`` 抛 ``ValueError``）。
            payload: 完整信封（写入前经 ``json_safe`` 清洗）。
            access_level: 密级继承结果（``compute_report_access_level``，worker 算得传入）。

        异常:
            ValueError: status 非 ok / partial，或 task_type 非 AnalysisType 合法值。
        """
        status_value = status.value if isinstance(status, AnalysisStatus) else str(status)
        if status_value not in _PERSISTABLE_STATUSES:
            raise ValueError(
                f"报告落库口径仅接受 ok / partial，实际收到 status={status_value!r}"
                "（完全失败走 job failed，不落空报告）"
            )
        task_type_value = task_type.value if isinstance(task_type, AnalysisType) else str(task_type)
        try:
            AnalysisType(task_type_value)
        except ValueError as exc:
            raise ValueError(f"task_type 非 AnalysisType 合法值: {task_type_value!r}") from exc

        report = AnalysisReportORM(
            job_id=job_id,
            user_id=user_id,
            task_type=task_type_value,
            status=status_value,
            subject_label=subject_label,
            payload=json_safe(payload),
            source_doc_ids=json_safe(list(source_doc_ids)),
            source_chunk_count=source_chunk_count,
            access_level=access_level,
            library_scope=LibraryScope.PERSONAL,  # 固定 personal（决策 4）
            owner_id=user_id,  # owner = 提交者（决策 4）
            project_id=None,
            team_id=None,
            model=model,
            prompt_version=prompt_version,
            usage_=json_safe(usage),
        )
        session.add(report)
        await session.flush()
        return report

    async def get(
        self, session: AsyncSession, report_id: uuid.UUID, *, access: AccessContext
    ) -> AnalysisReportORM | None:
        """按 ID 取报告：不存在或 ``visible_to`` 不可见均返回 ``None``（不泄漏存在性）。"""
        report = await session.get(AnalysisReportORM, report_id)
        if report is None:
            return None
        return report if visible_to(report, access) else None

    async def list_visible(
        self,
        session: AsyncSession,
        *,
        access: AccessContext,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[AnalysisReportORM], int]:
        """可见报告历史列表：三维过滤（clearance + scope + owner）+ limit/offset 分页。

        返回 ``(items, total)``：``total`` 为过滤后全部可见行数（供前端分页器），
        ``items`` 为 ``created_at`` 降序（复合索引 ``ix_analysis_reports_owner_created``
        服务的主查询）切片 ``[offset, offset+limit)``。

        异常:
            ValueError: ``limit <= 0`` 或 ``offset < 0``。
        """
        if limit <= 0 or offset < 0:
            raise ValueError(
                f"分页参数非法：limit={limit}, offset={offset}（须 limit>0 且 offset>=0）"
            )
        stmt = select(AnalysisReportORM).order_by(
            AnalysisReportORM.created_at.desc(), AnalysisReportORM.id
        )
        rows = (await session.execute(stmt)).scalars().all()
        visible = [r for r in rows if visible_to(r, access)]
        return visible[offset : offset + limit], len(visible)


__all__ = ["AnalysisReportStore"]
