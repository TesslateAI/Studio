"""Per-workflow health snapshot computer (G4, issue #469).

Single public function: :func:`compute_snapshot` reads
``automation_runs`` + ``automation_step_runs`` + ``automation_run_events``
+ ``workflow_proposals`` for one automation in one window and upserts
the corresponding :class:`WorkflowHealthSnapshot` row.

Used by:
* the G5 doctor agent (loaded into its tool context via
  ``read_workflow_history`` + ``manage_workflow_proposal``) so the
  agent can inspect failure trends before drafting a proposal.
* a planned background sweep that walks every active automation
  periodically and writes one snapshot per workflow per window — the
  sweep itself is a follow-up.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import (
    AutomationRun,
    AutomationRunEvent,
    AutomationStepRun,
)
from ...models_workflows import (
    WorkflowHealthSnapshot,
    WorkflowProposal,
    WorkflowVersion,
)

logger = logging.getLogger(__name__)


WINDOW_DELTAS: dict[str, timedelta] = {
    "short": timedelta(hours=24),
    "long": timedelta(days=7),
}


@dataclass
class HealthMetrics:
    run_count: int
    success_count: int
    failure_count: int
    awaiting_approval_count: int
    success_rate: Decimal | None
    median_duration_ms: int | None
    p95_duration_ms: int | None
    spend_p50_usd: Decimal | None
    spend_p95_usd: Decimal | None
    most_common_error_kind: str | None
    most_common_failed_step_ordinal: int | None
    last_failed_run_id: UUID | None
    last_failed_step_ordinal: int | None
    last_error_message: str | None
    runs_since_last_change: int
    open_proposal_count: int
    generation_at_window_start: int | None
    generation_at_window_end: int | None


async def compute_snapshot(
    db: AsyncSession,
    *,
    automation_id: UUID,
    window: str = "short",
) -> WorkflowHealthSnapshot:
    """Recompute and upsert the snapshot for one (automation, window)."""
    if window not in WINDOW_DELTAS:
        raise ValueError(f"window must be short|long, got {window!r}")

    cutoff = datetime.now(tz=UTC) - WINDOW_DELTAS[window]

    metrics = await _gather(db, automation_id=automation_id, cutoff=cutoff)

    existing = (
        await db.execute(
            select(WorkflowHealthSnapshot).where(
                WorkflowHealthSnapshot.automation_id == automation_id,
                WorkflowHealthSnapshot.window == window,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        snap = WorkflowHealthSnapshot(
            id=uuid.uuid4(),
            automation_id=automation_id,
            window=window,
            **_metrics_to_columns(metrics),
        )
        db.add(snap)
        try:
            await db.flush()
        except IntegrityError:
            # Race: another worker beat us. Re-read and update.
            await db.rollback()
            existing = (
                await db.execute(
                    select(WorkflowHealthSnapshot).where(
                        WorkflowHealthSnapshot.automation_id == automation_id,
                        WorkflowHealthSnapshot.window == window,
                    )
                )
            ).scalar_one()
        else:
            return snap

    # Update in place.
    for k, v in _metrics_to_columns(metrics).items():
        setattr(existing, k, v)
    existing.computed_at = datetime.now(tz=UTC)
    return existing


def _metrics_to_columns(m: HealthMetrics) -> dict[str, Any]:
    return {
        "run_count": m.run_count,
        "success_count": m.success_count,
        "failure_count": m.failure_count,
        "awaiting_approval_count": m.awaiting_approval_count,
        "success_rate": m.success_rate,
        "median_duration_ms": m.median_duration_ms,
        "p95_duration_ms": m.p95_duration_ms,
        "spend_p50_usd": m.spend_p50_usd,
        "spend_p95_usd": m.spend_p95_usd,
        "most_common_error_kind": m.most_common_error_kind,
        "most_common_failed_step_ordinal": m.most_common_failed_step_ordinal,
        "last_failed_run_id": m.last_failed_run_id,
        "last_failed_step_ordinal": m.last_failed_step_ordinal,
        "last_error_message": m.last_error_message,
        "runs_since_last_change": m.runs_since_last_change,
        "open_proposal_count": m.open_proposal_count,
        "generation_at_window_start": m.generation_at_window_start,
        "generation_at_window_end": m.generation_at_window_end,
    }


async def _gather(db: AsyncSession, *, automation_id: UUID, cutoff: datetime) -> HealthMetrics:
    """Pull the raw counters + percentiles for one window."""
    runs = (
        (
            await db.execute(
                select(AutomationRun)
                .where(
                    AutomationRun.automation_id == automation_id,
                    AutomationRun.created_at >= cutoff,
                )
                .order_by(AutomationRun.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    run_count = len(runs)
    success_count = sum(1 for r in runs if r.status == "succeeded")
    failure_count = sum(1 for r in runs if r.status in ("failed", "failed_preflight", "errored"))
    awaiting_approval_count = sum(1 for r in runs if r.status == "awaiting_approval")

    # success_rate is over terminal-ish runs only (skip queued / running /
    # awaiting). If nothing terminal yet, leave as None so the doctor
    # treats it as "no signal" rather than "100% failure."
    terminal = success_count + failure_count
    success_rate = Decimal(success_count) / Decimal(terminal) if terminal > 0 else None
    if success_rate is not None:
        # Round to 3 decimal places to fit Numeric(4, 3).
        success_rate = success_rate.quantize(Decimal("0.001"))

    # Durations from started_at + ended_at.
    durations_ms: list[int] = []
    for r in runs:
        if r.started_at is not None and r.ended_at is not None:
            delta = (r.ended_at - r.started_at).total_seconds() * 1000
            if delta >= 0:
                durations_ms.append(int(delta))

    median_duration_ms = _percentile_int(durations_ms, 0.5)
    p95_duration_ms = _percentile_int(durations_ms, 0.95)

    # Spend percentiles.
    spends = [Decimal(r.spend_usd or 0) for r in runs if r.spend_usd is not None]
    spend_p50 = _percentile_decimal(spends, 0.5)
    spend_p95 = _percentile_decimal(spends, 0.95)

    # Last failed run.
    last_failed = next(
        (r for r in runs if r.status in ("failed", "failed_preflight", "errored")),
        None,
    )
    last_failed_run_id = last_failed.id if last_failed is not None else None
    last_failed_step_ordinal: int | None = None
    last_error_message: str | None = None
    if last_failed is not None:
        step = (
            await db.execute(
                select(AutomationStepRun)
                .where(
                    AutomationStepRun.automation_run_id == last_failed.id,
                    AutomationStepRun.status == "failed",
                )
                .order_by(AutomationStepRun.ordinal.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if step is not None:
            last_failed_step_ordinal = int(step.ordinal)
            last_error_message = (step.error or "")[:1000] or None

    # Most common error kind via run-events of kind=error.raised.
    # Postgres can't GROUP BY a JSON column directly; fetch the
    # payloads and tally in Python. Bounded to the window so the
    # row count stays small.
    err_payloads = (
        (
            await db.execute(
                select(AutomationRunEvent.payload)
                .where(
                    AutomationRunEvent.kind == "error.raised",
                    AutomationRunEvent.ts >= cutoff,
                )
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    most_common_error_kind: str | None = None
    if err_payloads:
        from collections import Counter

        kinds = Counter(
            (
                (p.get("error_type") or p.get("kind") or "unknown")
                if isinstance(p, dict)
                else "unknown"
            )
            for p in err_payloads
        )
        if kinds:
            most_common_error_kind = kinds.most_common(1)[0][0]

    # Most common failed-step ordinal across the window's failed step_runs.
    step_failures = (
        await db.execute(
            select(AutomationStepRun.ordinal, func.count(AutomationStepRun.id))
            .where(
                AutomationStepRun.status == "failed",
                AutomationStepRun.created_at >= cutoff,
            )
            .group_by(AutomationStepRun.ordinal)
            .order_by(func.count(AutomationStepRun.id).desc())
            .limit(1)
        )
    ).all()
    most_common_failed_step_ordinal: int | None = None
    if step_failures:
        most_common_failed_step_ordinal = int(step_failures[0][0])

    # Generation window markers.
    gen_start, gen_end = await _generation_markers(db, automation_id=automation_id, cutoff=cutoff)
    runs_since_last_change = await _runs_since_head(db, automation_id=automation_id)

    # Open proposal count (status=submitted).
    open_proposal_count = (
        await db.scalar(
            select(func.count(WorkflowProposal.id)).where(
                WorkflowProposal.automation_id == automation_id,
                WorkflowProposal.status == "submitted",
            )
        )
    ) or 0

    return HealthMetrics(
        run_count=run_count,
        success_count=success_count,
        failure_count=failure_count,
        awaiting_approval_count=awaiting_approval_count,
        success_rate=success_rate,
        median_duration_ms=median_duration_ms,
        p95_duration_ms=p95_duration_ms,
        spend_p50_usd=spend_p50,
        spend_p95_usd=spend_p95,
        most_common_error_kind=most_common_error_kind,
        most_common_failed_step_ordinal=most_common_failed_step_ordinal,
        last_failed_run_id=last_failed_run_id,
        last_failed_step_ordinal=last_failed_step_ordinal,
        last_error_message=last_error_message,
        runs_since_last_change=runs_since_last_change,
        open_proposal_count=int(open_proposal_count),
        generation_at_window_start=gen_start,
        generation_at_window_end=gen_end,
    )


def _percentile_int(values: list[int], q: float) -> int | None:
    if not values:
        return None
    sorted_v = sorted(values)
    idx = max(0, min(len(sorted_v) - 1, int(len(sorted_v) * q)))
    return int(sorted_v[idx])


def _percentile_decimal(values: list[Decimal], q: float) -> Decimal | None:
    if not values:
        return None
    sorted_v = sorted(values)
    idx = max(0, min(len(sorted_v) - 1, int(len(sorted_v) * q)))
    return sorted_v[idx].quantize(Decimal("0.0001"))


async def _generation_markers(
    db: AsyncSession, *, automation_id: UUID, cutoff: datetime
) -> tuple[int | None, int | None]:
    """Earliest + latest WorkflowVersion.generation within the window."""
    rows = (
        await db.execute(
            select(
                func.min(WorkflowVersion.generation),
                func.max(WorkflowVersion.generation),
            ).where(
                WorkflowVersion.automation_id == automation_id,
                WorkflowVersion.created_at >= cutoff,
            )
        )
    ).first()
    if rows is None:
        return None, None
    a, b = rows
    return (int(a) if a is not None else None, int(b) if b is not None else None)


async def _runs_since_head(db: AsyncSession, *, automation_id: UUID) -> int:
    """Count runs that executed against the current head_version_id."""
    from ...models_automations import AutomationDefinition

    definition = (
        await db.execute(
            select(AutomationDefinition).where(AutomationDefinition.id == automation_id)
        )
    ).scalar_one_or_none()
    if definition is None or definition.head_version_id is None:
        return 0
    count = await db.scalar(
        select(func.count(AutomationRun.id)).where(
            AutomationRun.automation_id == automation_id,
            AutomationRun.workflow_version_id == definition.head_version_id,
        )
    )
    return int(count or 0)
