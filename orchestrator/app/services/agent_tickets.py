"""Ticket allocator for multi-agent orchestration.

Tickets are rows in ``agent_tasks`` identified by a human-readable
``ref_id`` of the form ``TSK-NNNN``. Allocation strictly monotonic across
the whole table (not per-project), which keeps references globally unique
and scan-friendly.

Three primitives:

- ``next_ref_id`` — compute the next free ``TSK-NNNN``.
- ``create_ticket`` — allocate + insert a queued ticket.
- ``checkout_ticket`` — atomic claim: pop one queued ticket to running.
- ``finish_ticket`` — mark a claimed ticket completed / failed / cancelled.

The queue is single-select-and-update using SQLAlchemy's dialect-agnostic
``UPDATE ... RETURNING``; the inner subquery is ``SELECT id ... LIMIT 1``
ordered by ``created_at``. Both SQLite and Postgres guarantee atomicity
inside a single statement, so concurrent workers cannot double-claim.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Integer, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentTask

REF_PREFIX = "TSK-"
REF_WIDTH = 4


def _format_ref(n: int) -> str:
    return f"{REF_PREFIX}{n:0{REF_WIDTH}d}"


async def next_ref_id(session: AsyncSession) -> str:
    """Return the next unused ``TSK-NNNN`` reference.

    Uses ``max(cast(substr(ref_id, 5), Integer))`` so the query works on
    both SQLite (no window funcs needed) and Postgres.
    """
    stmt = select(func.max(cast(func.substr(AgentTask.ref_id, len(REF_PREFIX) + 1), Integer)))
    result = await session.execute(stmt)
    current = result.scalar()
    next_n = (current or 0) + 1
    return _format_ref(next_n)


async def create_ticket(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    title: str,
    assignee_agent_id: uuid.UUID | None = None,
    parent_task_id: uuid.UUID | None = None,
    goal_ancestry: list[str] | None = None,
    requires_approval_for: list[str] | None = None,
    message_id: uuid.UUID | None = None,
) -> AgentTask:
    """Allocate a ref_id and insert a queued ticket."""
    ref_id = await next_ref_id(session)
    ticket = AgentTask(
        id=uuid.uuid4(),
        ref_id=ref_id,
        project_id=project_id,
        title=title,
        assignee_agent_id=assignee_agent_id,
        parent_task_id=parent_task_id,
        goal_ancestry=goal_ancestry,
        requires_approval_for=requires_approval_for,
        message_id=message_id,
        status="queued",
    )
    session.add(ticket)
    await session.flush()
    return ticket


async def checkout_ticket(
    session: AsyncSession,
    *,
    worker_id: str,
    project_id: uuid.UUID | None = None,
) -> AgentTask | None:
    """Atomic claim of the oldest queued ticket.

    Returns the claimed ``AgentTask`` or ``None`` if nothing was queued.
    The ``worker_id`` is currently recorded only indirectly via timestamp;
    a richer claim record (worker lease) is out of scope for the skeleton.
    """
    inner = select(AgentTask.id).where(AgentTask.status == "queued")
    if project_id is not None:
        inner = inner.where(AgentTask.project_id == project_id)
    inner = inner.order_by(AgentTask.created_at).limit(1)

    stmt = (
        update(AgentTask)
        .where(AgentTask.id.in_(inner.scalar_subquery()))
        .values(status="running", updated_at=datetime.now(UTC))
        .returning(AgentTask.id)
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    row = result.first()
    if row is None:
        return None
    claimed_id = row[0]
    await session.commit()

    fetched = await session.execute(select(AgentTask).where(AgentTask.id == claimed_id))
    return fetched.scalar_one_or_none()


async def checkout_ticket_by_id(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    worker_id: str,  # reserved for future lease tracking
) -> bool:
    """Atomically claim a specific ticket by ID.

    Flips status from ``queued`` → ``running``.  Returns ``True`` if the
    claim succeeded, ``False`` if the ticket was already running or missing
    (concurrent worker beat us; caller should skip the job).
    """
    stmt = (
        update(AgentTask)
        .where(AgentTask.id == ticket_id, AgentTask.status == "queued")
        .values(status="running", updated_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    await session.commit()
    # CursorResult exposes rowcount; SQLAlchemy AsyncResult proxies it.
    return getattr(result, "rowcount", 1) > 0


async def update_ticket_message_id(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    message_id: uuid.UUID,
) -> None:
    """Back-fill the ``message_id`` FK after the assistant Message is created."""
    stmt = (
        update(AgentTask)
        .where(AgentTask.id == ticket_id)
        .values(message_id=message_id, updated_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    await session.execute(stmt)
    await session.commit()


async def finish_ticket(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    status: str,
) -> None:
    """Mark a ticket finished with the given terminal status."""
    now = datetime.now(UTC)
    stmt = (
        update(AgentTask)
        .where(AgentTask.id == ticket_id)
        .values(status=status, updated_at=now, completed_at=now)
        .execution_options(synchronize_session=False)
    )
    await session.execute(stmt)
    await session.commit()


__all__: list[str] = [
    "next_ref_id",
    "create_ticket",
    "checkout_ticket",
    "checkout_ticket_by_id",
    "update_ticket_message_id",
    "finish_ticket",
]
