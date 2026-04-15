"""Monitoring + adversarial + creator-reputation helpers.

Thin service-layer primitives for the MonitoringRun / AdversarialRun
tables and a reputation UPSERT. No scheduling or orchestration logic —
the worker owns the run loop; this module only does per-row writes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    AdversarialRun,
    CreatorReputation,
    MonitoringRun,
)

__all__ = [
    "start_monitoring_run",
    "finish_monitoring_run",
    "record_adversarial_run",
    "upsert_creator_reputation",
]

logger = logging.getLogger(__name__)

MonitoringKind = Literal["canary", "replay", "drift"]
MonitoringStatus = Literal["passed", "failed", "errored"]


async def start_monitoring_run(
    db: AsyncSession,
    *,
    app_version_id: UUID,
    kind: MonitoringKind,
) -> UUID:
    """Insert a MonitoringRun in status='running'."""
    run_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    db.add(
        MonitoringRun(
            id=run_id,
            app_version_id=app_version_id,
            kind=kind,
            status="running",
            started_at=now,
            findings={},
        )
    )
    await db.flush()
    return run_id


async def finish_monitoring_run(
    db: AsyncSession,
    *,
    run_id: UUID,
    status: MonitoringStatus,
    findings: dict | None = None,
) -> None:
    """Close out a MonitoringRun with a terminal status."""
    row = (
        await db.execute(
            select(MonitoringRun)
            .where(MonitoringRun.id == run_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"monitoring_run {run_id} not found")
    row.status = status
    row.finished_at = datetime.now(tz=timezone.utc)
    if findings is not None:
        row.findings = findings
    await db.flush()


async def record_adversarial_run(
    db: AsyncSession,
    *,
    suite_id: UUID,
    app_version_id: UUID,
    score: float | None,
    findings: dict | None = None,
) -> UUID:
    """Append an AdversarialRun result row."""
    run_id = uuid.uuid4()
    db.add(
        AdversarialRun(
            id=run_id,
            suite_id=suite_id,
            app_version_id=app_version_id,
            score=Decimal(str(score)) if score is not None else None,
            findings=findings or {},
        )
    )
    await db.flush()
    return run_id


async def upsert_creator_reputation(
    db: AsyncSession,
    *,
    user_id: UUID,
    delta_score: Decimal = Decimal("0"),
    delta_approvals: int = 0,
    delta_yanks: int = 0,
    delta_critical_yanks: int = 0,
) -> None:
    """UPSERT into creator_reputation accumulating the supplied deltas."""
    now = datetime.now(tz=timezone.utc)
    stmt = pg_insert(CreatorReputation).values(
        user_id=user_id,
        score=Decimal(delta_score),
        approvals_count=delta_approvals,
        yanks_count=delta_yanks,
        critical_yanks_count=delta_critical_yanks,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[CreatorReputation.user_id],
        set_={
            "score": CreatorReputation.score + stmt.excluded.score,
            "approvals_count": (
                CreatorReputation.approvals_count + stmt.excluded.approvals_count
            ),
            "yanks_count": (
                CreatorReputation.yanks_count + stmt.excluded.yanks_count
            ),
            "critical_yanks_count": (
                CreatorReputation.critical_yanks_count
                + stmt.excluded.critical_yanks_count
            ),
            "updated_at": now,
        },
    )
    await db.execute(stmt)
    await db.flush()
