"""Database-backed lease (default backend; works on Postgres + SQLite).

Implements the contract documented on
:class:`app.services.automations.lease.Lease`. The single durable row
lives in ``controller_leases`` (see ORM model
:class:`app.models_automations.ControllerLease` and alembic
``0080_controller_plane``).

Acquire algorithm (one TXN, ``SELECT ... FOR UPDATE`` on Postgres,
plain UPDATE on SQLite):

1. ``SELECT * FROM controller_leases WHERE name=:name FOR UPDATE``.
2. If the row is missing, ``INSERT`` it with ``term = 1``.
3. Else if it's expired OR currently held by us, ``UPDATE`` it bumping
   ``term`` (only on a fresh take, not a renewal) and resetting holder /
   expiry.
4. Else (held by someone else, not expired) → return ``None``.

Renew algorithm:

* ``UPDATE controller_leases SET expires_at=now()+ttl WHERE name=:name
  AND holder=:holder AND term=:term`` — atomic. If 0 rows updated the
  lease is gone (deposed by a fresher acquire).

Release algorithm:

* ``UPDATE controller_leases SET holder=NULL, expires_at=NULL
  WHERE name=:name AND holder=:holder AND term=:term``. Idempotent.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import text

from . import Lease, LeaseToken

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DBLease(Lease):
    """SQLAlchemy-backed lease — works on Postgres and SQLite alike.

    The class is stateless; sessions are opened on demand from
    :data:`app.database.AsyncSessionLocal`. That keeps the lease usable
    from any caller without requiring a session-context kwarg.
    """

    async def acquire(
        self, name: str, holder_id: str, ttl_seconds: int
    ) -> Optional[LeaseToken]:
        from app.database import AsyncSessionLocal

        now = _utcnow()
        new_expiry = now + timedelta(seconds=ttl_seconds)

        async with AsyncSessionLocal() as session:
            bind = session.get_bind()
            dialect = getattr(getattr(bind, "dialect", None), "name", "")
            use_for_update = dialect == "postgresql"

            try:
                # Lock the row (or read it cleanly on SQLite).
                if use_for_update:
                    row = (
                        await session.execute(
                            text(
                                "SELECT name, holder, term, expires_at "
                                "FROM controller_leases WHERE name = :name "
                                "FOR UPDATE"
                            ),
                            {"name": name},
                        )
                    ).first()
                else:
                    row = (
                        await session.execute(
                            text(
                                "SELECT name, holder, term, expires_at "
                                "FROM controller_leases WHERE name = :name"
                            ),
                            {"name": name},
                        )
                    ).first()

                if row is None:
                    # First-ever acquire of this lease.
                    await session.execute(
                        text(
                            "INSERT INTO controller_leases "
                            "(name, holder, term, expires_at, acquired_at) "
                            "VALUES (:name, :holder, 1, :expires, :acquired)"
                        ),
                        {
                            "name": name,
                            "holder": holder_id,
                            "expires": new_expiry,
                            "acquired": now,
                        },
                    )
                    await session.commit()
                    return LeaseToken(
                        name=name, holder=holder_id, term=1, expires_at=new_expiry
                    )

                cur_holder = row[1]
                cur_term = int(row[2] or 0)
                cur_expires = row[3]
                # Normalize expires for tz-aware comparison. SQLite returns
                # timestamps as ISO strings (no datetime adapter); Postgres
                # returns proper datetime objects. Parse strings first, then
                # ensure UTC tz on naive datetimes.
                if cur_expires is not None and isinstance(cur_expires, str):
                    cur_expires = datetime.fromisoformat(cur_expires)
                if cur_expires is not None and getattr(cur_expires, "tzinfo", None) is None:
                    cur_expires = cur_expires.replace(tzinfo=UTC)

                expired = cur_expires is None or cur_expires < now
                same_holder = cur_holder == holder_id

                if not expired and not same_holder:
                    # Held by someone else, still valid — caller stands down.
                    await session.rollback()
                    return None

                # Bump term on every fresh acquire (also on takeover after
                # expiry by the same holder — that's a fresh leadership
                # period, distinct from a renew).
                new_term = cur_term + 1
                await session.execute(
                    text(
                        "UPDATE controller_leases "
                        "SET holder = :holder, term = :term, "
                        "    expires_at = :expires, acquired_at = :acquired "
                        "WHERE name = :name"
                    ),
                    {
                        "name": name,
                        "holder": holder_id,
                        "term": new_term,
                        "expires": new_expiry,
                        "acquired": now,
                    },
                )
                await session.commit()
                return LeaseToken(
                    name=name,
                    holder=holder_id,
                    term=new_term,
                    expires_at=new_expiry,
                )
            except Exception:
                logger.exception("DBLease.acquire: failed for name=%s", name)
                await session.rollback()
                return None

    async def renew(self, token: LeaseToken) -> bool:
        from app.database import AsyncSessionLocal

        now = _utcnow()
        new_expiry = now + (token.expires_at - now if token.expires_at > now else timedelta(seconds=60))
        # On renew we keep the same TTL window length the holder originally
        # asked for. We can't know that from the token alone, so default
        # to a 60s extension — the supervisor calls renew well before
        # expiry so this is a soft bound.
        new_expiry = now + timedelta(seconds=60)

        async with AsyncSessionLocal() as session:
            try:
                result = await session.execute(
                    text(
                        "UPDATE controller_leases "
                        "SET expires_at = :expires "
                        "WHERE name = :name AND holder = :holder "
                        "  AND term = :term"
                    ),
                    {
                        "expires": new_expiry,
                        "name": token.name,
                        "holder": token.holder,
                        "term": token.term,
                    },
                )
                await session.commit()
                return (result.rowcount or 0) > 0
            except Exception:
                logger.exception(
                    "DBLease.renew: failed for name=%s term=%s",
                    token.name,
                    token.term,
                )
                await session.rollback()
                return False

    async def release(self, token: LeaseToken) -> None:
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            try:
                await session.execute(
                    text(
                        "UPDATE controller_leases "
                        "SET holder = NULL, expires_at = NULL "
                        "WHERE name = :name AND holder = :holder "
                        "  AND term = :term"
                    ),
                    {
                        "name": token.name,
                        "holder": token.holder,
                        "term": token.term,
                    },
                )
                await session.commit()
            except Exception:
                logger.exception(
                    "DBLease.release: failed for name=%s term=%s",
                    token.name,
                    token.term,
                )
                await session.rollback()


__all__ = ["DBLease"]
