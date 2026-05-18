"""Cross-workflow learning store (G6, issue #469).

Tiny service: record + lookup + outcome-tracking. The doctor agent
calls these via tool wrappers. Team-scoped so customers don't
accidentally share learnings cross-tenant.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_workflows import WorkflowLearning

logger = logging.getLogger(__name__)


async def record_learning(
    db: AsyncSession,
    *,
    team_id: UUID | None,
    tag: str,
    symptom_pattern: dict[str, Any] | None,
    proposed_fix: dict[str, Any] | None,
    created_by_run_id: UUID | None,
) -> WorkflowLearning:
    row = WorkflowLearning(
        id=uuid.uuid4(),
        team_id=team_id,
        tag=tag[:64],
        symptom_pattern=symptom_pattern or {},
        proposed_fix=proposed_fix or {},
        created_by_run_id=created_by_run_id,
    )
    db.add(row)
    await db.flush()
    logger.info(
        "workflow_learning.recorded team=%s tag=%s run=%s",
        team_id,
        tag,
        created_by_run_id,
    )
    return row


async def lookup_learnings(
    db: AsyncSession,
    *,
    team_id: UUID | None,
    tag_prefix: str | None = None,
    limit: int = 5,
) -> list[WorkflowLearning]:
    """Return top N team-scoped learnings, ranked by success rate."""
    query = select(WorkflowLearning).where(WorkflowLearning.team_id == team_id)
    if tag_prefix:
        query = query.where(WorkflowLearning.tag.like(f"{tag_prefix}%"))
    rows = list(
        (await db.execute(query.order_by(WorkflowLearning.updated_at.desc()))).scalars().all()
    )

    def _rank(row: WorkflowLearning) -> float:
        total = (row.success_count or 0) + (row.failure_count or 0)
        if total == 0:
            return 0.0
        return float(row.success_count or 0) / float(total)

    rows.sort(key=_rank, reverse=True)
    return rows[:limit]


async def record_outcome(
    db: AsyncSession,
    *,
    learning_id: UUID,
    outcome: str,
    applied_run_id: UUID | None = None,
) -> WorkflowLearning:
    """outcome ∈ {success, failure}. Caller picks based on a follow-up run."""
    row = (
        await db.execute(select(WorkflowLearning).where(WorkflowLearning.id == learning_id))
    ).scalar_one()
    if outcome == "success":
        row.success_count = int(row.success_count or 0) + 1
    elif outcome == "failure":
        row.failure_count = int(row.failure_count or 0) + 1
    else:
        raise ValueError(f"outcome must be success|failure, got {outcome!r}")
    if applied_run_id is not None:
        row.last_applied_run_id = applied_run_id
    row.updated_at = datetime.now(tz=UTC)
    return row
