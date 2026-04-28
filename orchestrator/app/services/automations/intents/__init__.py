"""Controller intent helpers (Phase 4).

The intent contract: any K8s/Docker mutation a controller wants to do is
written as a row in ``controller_intents`` *inside the same transaction*
that verifies the leader's lease. The reconciler then reads pending
rows, filters out stale ``lease_term`` (those came from a deposed
leader and are marked ``superseded``), and applies idempotent
mutations.

Public functions:

* :func:`record_intent` — INSERT a pending intent row. Caller MUST
  already be inside a TXN that holds the lease verify (otherwise use
  :func:`record_intent_with_lease`).
* :func:`record_intent_with_lease` — convenience that opens its own
  TXN, verifies the lease, and inserts the intent atomically.
* :func:`mark_applied`, :func:`mark_superseded`, :func:`mark_failed` —
  reconciler-side state transitions.

:class:`LeaseLost` is raised when the lease verify fails. The
controller-main supervisor treats this as the signal to abandon
leadership and re-acquire.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class LeaseLost(RuntimeError):
    """Raised when an in-TXN lease verify discovers the lease is no longer ours.

    Carries no application-meaningful payload — the supervisor treats
    every instance the same way (cancel children, re-acquire).
    """


async def record_intent(
    db: AsyncSession,
    *,
    kind: str,
    target_ref: dict[str, Any],
    lease_term: int,
) -> UUID:
    """Insert a ``pending`` intent. Caller owns the TXN.

    The TXN MUST already have verified the lease — most callers should
    use :func:`record_intent_with_lease` instead.
    """
    from ....models_automations import ControllerIntent

    intent_id = uuid4()
    db.add(
        ControllerIntent(
            id=intent_id,
            kind=kind,
            target_ref=target_ref,
            lease_term=lease_term,
            status="pending",
            attempts=0,
        )
    )
    await db.flush()
    return intent_id


async def record_intent_with_lease(
    db: AsyncSession,
    *,
    name: str,
    our_term: int,
    kind: str,
    target_ref: dict[str, Any],
) -> UUID:
    """Verify the lease and insert the intent in one TXN.

    Raises :class:`LeaseLost` if the lease term in the DB differs from
    ``our_term`` (or the row is missing entirely). Caller must be on a
    session with no open inner TXN that would commit ahead of the
    verify.
    """
    bind = db.get_bind() if hasattr(db, "get_bind") else None
    dialect = getattr(getattr(bind, "dialect", None), "name", "") if bind else ""
    use_for_update = dialect == "postgresql"

    if use_for_update:
        row = (
            await db.execute(
                text(
                    "SELECT term FROM controller_leases "
                    "WHERE name = :name FOR UPDATE"
                ),
                {"name": name},
            )
        ).first()
    else:
        row = (
            await db.execute(
                text(
                    "SELECT term FROM controller_leases WHERE name = :name"
                ),
                {"name": name},
            )
        ).first()

    if row is None:
        raise LeaseLost(f"lease {name!r} row missing")
    if int(row[0] or 0) != our_term:
        raise LeaseLost(
            f"lease {name!r} term mismatch (db={row[0]} ours={our_term})"
        )

    return await record_intent(
        db,
        kind=kind,
        target_ref=target_ref,
        lease_term=our_term,
    )


async def mark_applied(
    db: AsyncSession, intent_id: UUID, lease_term: int
) -> None:
    """Move an intent to ``applied``."""
    from ....models_automations import ControllerIntent

    now = datetime.now(UTC)
    await db.execute(
        ControllerIntent.__table__.update()
        .where(ControllerIntent.id == intent_id)
        .values(
            status="applied",
            applied_at=now,
            applied_by_term=lease_term,
        )
    )
    await db.commit()


async def mark_superseded(db: AsyncSession, intent_id: UUID) -> None:
    """Move an intent to ``superseded`` (stale lease term)."""
    from ....models_automations import ControllerIntent

    await db.execute(
        ControllerIntent.__table__.update()
        .where(ControllerIntent.id == intent_id)
        .values(status="superseded")
    )
    await db.commit()


async def mark_failed(
    db: AsyncSession,
    intent_id: UUID,
    error: str,
    attempts: int,
) -> None:
    """Move an intent to ``failed`` (exhausted attempts)."""
    from ....models_automations import ControllerIntent

    await db.execute(
        ControllerIntent.__table__.update()
        .where(ControllerIntent.id == intent_id)
        .values(
            status="failed",
            last_error=error[:1000],
            attempts=attempts,
        )
    )
    await db.commit()


__all__ = [
    "LeaseLost",
    "record_intent",
    "record_intent_with_lease",
    "mark_applied",
    "mark_superseded",
    "mark_failed",
]
