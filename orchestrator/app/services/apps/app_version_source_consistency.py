"""Wave 7: ``AppVersion.source_id`` consistency enforcement.

Invariant
---------
Every ``AppVersion`` row's ``source_id`` MUST equal the parent
``MarketplaceApp.source_id``. The publisher (``services/apps/publisher.py``)
and the install path already honour this on write; the federated sync
worker preserves it on app-version yank/remove because it never
constructs a fresh ``AppVersion`` row from the changes feed (apps land
parent-first; versions are sourced from the orchestrator's own publish
pipeline). This module is the **defense-in-depth** layer that:

1. Raises :class:`AppVersionSourceMismatch` (subclass of ``ValueError``)
   on flush when an ``AppVersion`` row's ``source_id`` differs from its
   parent app's ``source_id``. The error carries a stable ``reason``
   token (``source_mismatch``) the caller can branch on without string-
   matching the message.
2. Provides :func:`assert_app_version_source_id_matches` for routers and
   services that want to surface a typed error before the flush.
3. Provides :func:`scan_orphans` for the CI parity test in
   ``tests/services/test_app_version_source_consistency.py``.

Why an event listener and not a CHECK constraint?
-------------------------------------------------
A Postgres CHECK on ``app_versions.source_id`` cannot reference a column
on ``marketplace_apps`` — CHECKs are row-local. A FK constraint cannot
express "must equal the parent's source_id" either. We could add a
trigger, but triggers are a maintenance burden across the SQLite desktop
backend and the Postgres cloud backend. An ORM-level event listener fires
on every flush in BOTH backends, runs in Python so the error message is
rich, and is opt-in from a single registration point at app startup.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ...models import AppVersion, MarketplaceApp

logger = logging.getLogger(__name__)


_SENTINEL_REASON = "source_mismatch"


class AppVersionSourceMismatch(ValueError):
    """Raised when an ``AppVersion`` write would violate the invariant.

    Subclasses :class:`ValueError` rather than the installer's
    :class:`SourceMismatchError` so the SQLAlchemy event hook can raise
    without dragging the installer module into the import graph for
    every flush. Callers that want the install-time semantics should
    catch :class:`SourceMismatchError` (which the installer raises
    directly before the flush ever happens) — this listener is the
    fallback for direct ORM writes that bypassed the installer.
    """

    reason = _SENTINEL_REASON

    def __init__(
        self,
        *,
        app_version_id: UUID | None,
        app_version_source_id: Any,
        parent_app_id: UUID,
        parent_source_id: Any,
    ) -> None:
        super().__init__(
            f"AppVersion source_id mismatch: app_version_id={app_version_id!r} "
            f"app_version_source_id={app_version_source_id!r} "
            f"parent_app_id={parent_app_id!r} "
            f"parent_source_id={parent_source_id!r}"
        )
        self.app_version_id = app_version_id
        self.app_version_source_id = app_version_source_id
        self.parent_app_id = parent_app_id
        self.parent_source_id = parent_source_id


def assert_app_version_source_id_matches(
    *,
    app_version_source_id: Any,
    parent_source_id: Any,
    app_version_id: UUID | None = None,
    parent_app_id: UUID | None = None,
) -> None:
    """Pre-flush assertion helper for service code paths.

    Raises :class:`AppVersionSourceMismatch` when the two ``source_id``
    values disagree. Call from publisher, fork, sync upsert, or anywhere
    else an ``AppVersion`` row's ``source_id`` is being set so the error
    surfaces close to the caller's intent rather than at flush time.
    """
    if app_version_source_id == parent_source_id:
        return
    raise AppVersionSourceMismatch(
        app_version_id=app_version_id,
        app_version_source_id=app_version_source_id,
        parent_app_id=parent_app_id,  # type: ignore[arg-type]
        parent_source_id=parent_source_id,
    )


def _check_pending(session: Session) -> None:
    """Synchronous flush hook — runs for both async and sync sessions.

    Walks the session's ``new`` and ``dirty`` collections for any
    :class:`AppVersion` rows being inserted/updated; for each, fetches
    the parent :class:`MarketplaceApp` from the same session's identity
    map (or, if the app is not yet loaded, from the bound DB) and
    enforces the invariant.
    """
    pending: list[AppVersion] = []
    for obj in list(session.new):
        if isinstance(obj, AppVersion):
            pending.append(obj)
    for obj in list(session.dirty):
        if isinstance(obj, AppVersion) and _has_source_id_change(obj):
            pending.append(obj)
    if not pending:
        return

    for av in pending:
        parent_app_id = av.app_id
        if parent_app_id is None:
            # AppVersion always has a NOT NULL app_id — the FK constraint
            # will reject the insert downstream. Don't double-fault here.
            continue

        parent_source_id = _resolve_parent_source_id(
            session, parent_app_id, pending_apps=session.new
        )
        if parent_source_id is _UNRESOLVED:
            # Parent not in this session and not in the DB yet — the FK
            # check will catch a fully missing parent. If the parent is
            # an in-flight insert without a source_id, treat that as a
            # mismatch only when the version row's source_id is set.
            continue

        if av.source_id != parent_source_id:
            raise AppVersionSourceMismatch(
                app_version_id=av.id,
                app_version_source_id=av.source_id,
                parent_app_id=parent_app_id,
                parent_source_id=parent_source_id,
            )


def _has_source_id_change(av: AppVersion) -> bool:
    """True iff this AppVersion's ``source_id`` is in the dirty change set."""
    state = getattr(av, "_sa_instance_state", None)
    if state is None:
        return False
    attr = state.attrs.get("source_id")
    if attr is None:
        return False
    history = attr.history
    return bool(history.added or history.deleted)


_UNRESOLVED: Any = object()


def _resolve_parent_source_id(
    session: Session, parent_app_id: UUID, *, pending_apps
) -> Any:
    """Find the parent app's ``source_id`` in the session or DB.

    Looks first at in-flight inserts (``session.new``), then at the
    identity map, and finally falls back to a synchronous SELECT through
    the session's own ``connection()`` (NOT the bound engine — the
    session may already hold a transaction the engine cannot see).
    Returns the sentinel ``_UNRESOLVED`` when no parent row can be
    found at all.
    """
    for obj in pending_apps:
        if isinstance(obj, MarketplaceApp) and obj.id == parent_app_id:
            return obj.source_id
    cached = session.identity_map.get((MarketplaceApp, (parent_app_id,)))
    if cached is not None:
        return cached.source_id
    # Last resort — synchronous SELECT through the session's connection
    # so we see uncommitted in-flight rows the listener was triggered for.
    try:
        connection = session.connection()
    except Exception:
        return _UNRESOLVED
    row = connection.execute(
        select(MarketplaceApp.source_id).where(MarketplaceApp.id == parent_app_id)
    ).first()
    if row is None:
        return _UNRESOLVED
    return row[0]


def register() -> None:
    """Wire the ``before_flush`` listener once at app startup.

    Safe to call multiple times — SQLAlchemy de-duplicates listeners by
    ``(target, identifier, fn)`` triple.
    """
    event.listen(Session, "before_flush", _on_before_flush)
    logger.info("registered AppVersion source_id consistency listener")


def _on_before_flush(session: Session, flush_context, instances) -> None:  # noqa: ARG001
    _check_pending(session)


# Auto-register on import so any module that touches AppVersion is
# protected. Importing this module from app/main.py at startup is the
# canonical wire-up.
register()


# ---------------------------------------------------------------------------
# CI parity helper — used by tests/services/test_app_version_source_consistency.py
# ---------------------------------------------------------------------------


async def scan_orphans(session: AsyncSession) -> list[dict[str, Any]]:
    """Return every ``app_versions`` row whose source_id disagrees with parent.

    Used by the CI parity test to fail fast if a code path ever lands a
    mismatched row in production. Returns an empty list when the
    invariant holds.
    """
    stmt = (
        select(
            AppVersion.id,
            AppVersion.app_id,
            AppVersion.source_id.label("av_source_id"),
            MarketplaceApp.source_id.label("app_source_id"),
        )
        .join(MarketplaceApp, MarketplaceApp.id == AppVersion.app_id)
        .where(AppVersion.source_id.is_distinct_from(MarketplaceApp.source_id))
    )
    result = await session.execute(stmt)
    return [
        {
            "app_version_id": row.id,
            "app_id": row.app_id,
            "app_version_source_id": row.av_source_id,
            "app_source_id": row.app_source_id,
        }
        for row in result.all()
    ]


__all__ = [
    "AppVersionSourceMismatch",
    "assert_app_version_source_id_matches",
    "register",
    "scan_orphans",
]
