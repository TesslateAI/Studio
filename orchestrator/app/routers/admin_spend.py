"""Admin spend rollup — aggregate ``SpendRecord`` by user / app / team.

Phase 5 polish — surfaces a per-user / per-app / per-team rollup of
``spend_records`` so admins can see who is burning credits where without
running raw SQL. Backs the admin dashboard at
``app/src/pages/admin/SpendDashboard.tsx``.

Joins
-----
``SpendRecord`` carries an ``invocation_subject_id`` column (Phase 0
attribution) but the FK to ``invocation_subjects`` only landed in
Phase 2 (alembic ``0075``). All grouping happens through that join so
unattributed rows (``invocation_subject_id IS NULL``) are intentionally
excluded — they belong to legacy code paths the rollup can't bucket.

The query shape is::

    SELECT invs.invoking_user_id,
           invs.app_instance_id,
           SUM(sr.amount_usd)
    FROM spend_records sr
    JOIN invocation_subjects invs
      ON invs.id = sr.invocation_subject_id
    WHERE sr.created_at BETWEEN :start AND :end
    GROUP BY invs.invoking_user_id, invs.app_instance_id;

The router transforms the inner row tuples into a flat list with the
joined display names (``user_email``, ``app_name``) so the frontend
table can render in one pass.

Auth
----
Superusers only. Team admins are NOT granted access here — a separate
``/api/teams/{slug}/spend/rollup`` endpoint (out of scope for this
deliverable) handles per-team admin rollups using the existing
``Permission.team_admin`` gate.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import SpendRecord, User
from ..models_automations import AppInstance, InvocationSubject
from ..users import current_superuser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/spend", tags=["admin-spend"])


GroupBy = Literal["user", "app", "team"]


class SpendRollupRow(BaseModel):
    """One bucket from the rollup. Optional fields stay None when the
    grouping doesn't include them — e.g. group_by='user' returns
    ``app_instance_id=None`` because the bucket is per-user across all
    apps.
    """

    user_id: UUID | None = None
    user_email: str | None = None
    app_instance_id: UUID | None = None
    app_name: str | None = None
    team_id: UUID | None = None
    total_usd: str = "0.00"
    currency: str = "USD"


class SpendRollupTotals(BaseModel):
    all_users_usd: str
    currency: str = "USD"


class SpendRollupResponse(BaseModel):
    rows: list[SpendRollupRow]
    totals: SpendRollupTotals
    group_by: GroupBy
    start: datetime
    end: datetime


def _quantize(value: Decimal | None) -> str:
    """Render a numeric spend total to fixed 2-decimal USD."""
    if value is None:
        return "0.00"
    # Strings (not floats) all the way to JSON to avoid binary-float drift.
    return f"{Decimal(value).quantize(Decimal('0.01'))}"


@router.get("/rollup", response_model=SpendRollupResponse)
async def spend_rollup(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    group_by: GroupBy = Query(default="user"),
    _admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> SpendRollupResponse:
    """Aggregate spend over a time window, bucketed by user, app, or team.

    * ``start`` / ``end``: ISO8601. Defaults to the last 30 days.
    * ``group_by``: one of ``user`` / ``app`` / ``team``.
    """
    now = datetime.now(UTC)
    if end is None:
        end = now
    if start is None:
        start = end - timedelta(days=30)
    if start >= end:
        raise HTTPException(status_code=400, detail="start must be before end")

    # Grand total — independent of group_by so the dashboard can render a
    # consistent footer regardless of slice.
    total_stmt = (
        select(func.coalesce(func.sum(SpendRecord.amount_usd), 0))
        .select_from(SpendRecord)
        .join(InvocationSubject, InvocationSubject.id == SpendRecord.invocation_subject_id)
        .where(SpendRecord.created_at >= start)
        .where(SpendRecord.created_at <= end)
    )
    total_value: Decimal | float | int = await db.scalar(total_stmt) or 0

    rows: list[SpendRollupRow] = []

    if group_by == "user":
        stmt = (
            select(
                InvocationSubject.invoking_user_id.label("user_id"),
                User.email.label("user_email"),
                func.coalesce(func.sum(SpendRecord.amount_usd), 0).label("total"),
            )
            .select_from(SpendRecord)
            .join(
                InvocationSubject,
                InvocationSubject.id == SpendRecord.invocation_subject_id,
            )
            .outerjoin(User, User.id == InvocationSubject.invoking_user_id)
            .where(SpendRecord.created_at >= start)
            .where(SpendRecord.created_at <= end)
            .group_by(InvocationSubject.invoking_user_id, User.email)
            .order_by(func.sum(SpendRecord.amount_usd).desc())
        )
        for row in (await db.execute(stmt)).all():
            rows.append(
                SpendRollupRow(
                    user_id=row.user_id,
                    user_email=row.user_email,
                    total_usd=_quantize(row.total),
                )
            )

    elif group_by == "app":
        # The "app name" the dashboard wants is the marketplace app name,
        # but ``AppInstance`` only carries app_id; the name lives on
        # ``MarketplaceApp``. We project the FK and let the frontend
        # resolve names if needed — at this scale the rollup is read on
        # demand by superusers, not a hot path.
        from ..models import MarketplaceApp  # local import to avoid cycle

        stmt = (
            select(
                InvocationSubject.app_instance_id.label("app_instance_id"),
                MarketplaceApp.name.label("app_name"),
                func.coalesce(func.sum(SpendRecord.amount_usd), 0).label("total"),
            )
            .select_from(SpendRecord)
            .join(
                InvocationSubject,
                InvocationSubject.id == SpendRecord.invocation_subject_id,
            )
            .outerjoin(
                AppInstance, AppInstance.id == InvocationSubject.app_instance_id
            )
            .outerjoin(MarketplaceApp, MarketplaceApp.id == AppInstance.app_id)
            .where(SpendRecord.created_at >= start)
            .where(SpendRecord.created_at <= end)
            .group_by(InvocationSubject.app_instance_id, MarketplaceApp.name)
            .order_by(func.sum(SpendRecord.amount_usd).desc())
        )
        for row in (await db.execute(stmt)).all():
            rows.append(
                SpendRollupRow(
                    app_instance_id=row.app_instance_id,
                    app_name=row.app_name,
                    total_usd=_quantize(row.total),
                )
            )

    elif group_by == "team":
        stmt = (
            select(
                InvocationSubject.team_id.label("team_id"),
                func.coalesce(func.sum(SpendRecord.amount_usd), 0).label("total"),
            )
            .select_from(SpendRecord)
            .join(
                InvocationSubject,
                InvocationSubject.id == SpendRecord.invocation_subject_id,
            )
            .where(SpendRecord.created_at >= start)
            .where(SpendRecord.created_at <= end)
            .group_by(InvocationSubject.team_id)
            .order_by(func.sum(SpendRecord.amount_usd).desc())
        )
        for row in (await db.execute(stmt)).all():
            rows.append(
                SpendRollupRow(
                    team_id=row.team_id,
                    total_usd=_quantize(row.total),
                )
            )

    return SpendRollupResponse(
        rows=rows,
        totals=SpendRollupTotals(all_users_usd=_quantize(total_value)),
        group_by=group_by,
        start=start,
        end=end,
    )
