"""Shared source-resolution helpers for federation-aware routers.

Replaces the per-router process-wide ORM caches that were leaking
``MarketplaceSource`` rows attached to long-gone sessions and never
invalidating after mutations. Two helpers:

* :func:`resolve_source_filter` — handle → id lookup with a short TTL on
  the immutable ``(handle, id)`` pair (the hottest browse-path query).
* :func:`bulk_load_sources` — one ``SELECT ... IN`` per call. Always
  hits the DB so callers see fresh ``trust_level`` / ``is_active`` /
  ``encrypted_token`` values without us having to thread invalidation
  through every mutating endpoint.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MarketplaceSource

# Short TTL is safe: (handle, id) is the only immutable pair in the row.
# A 60s window means a renamed handle propagates within one minute.
_HANDLE_CACHE_TTL_S: float = 60.0
_handle_cache: dict[str, tuple[UUID, float]] = {}


def invalidate_source_cache(handle: str | None = None) -> None:
    """Drop the handle→id cache.

    Mutating endpoints call this with the affected handle (or ``None`` to
    flush everything) so the next request observes the new mapping.
    """
    if handle is None:
        _handle_cache.clear()
    else:
        _handle_cache.pop(handle, None)


async def resolve_source_filter(db: AsyncSession, source_handle: str | None) -> UUID | None:
    """Resolve a ``?source=<handle>`` query param to a ``source_id``.

    Returns ``None`` for the cross-source ("All sources") browse case.
    Raises 404 when the handle is unknown so the UI surfaces a typed
    error rather than silently returning an empty result set.
    """
    if not source_handle:
        return None

    cached = _handle_cache.get(source_handle)
    if cached is not None and (time.monotonic() - cached[1]) < _HANDLE_CACHE_TTL_S:
        return cached[0]

    result = await db.execute(
        select(MarketplaceSource.id, MarketplaceSource.handle).where(
            MarketplaceSource.handle == source_handle
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown marketplace source handle: {source_handle!r}",
        )
    src_id: UUID = row[0]  # type: ignore[assignment]
    _handle_cache[source_handle] = (src_id, time.monotonic())
    return src_id


async def load_source(db: AsyncSession, source_id: Any) -> MarketplaceSource | None:
    """Return the ``MarketplaceSource`` row, or ``None`` for missing FK."""
    if source_id is None:
        return None
    result = await db.execute(select(MarketplaceSource).where(MarketplaceSource.id == source_id))
    return result.scalar_one_or_none()


async def bulk_load_sources(
    db: AsyncSession, source_ids: set[Any]
) -> dict[UUID, MarketplaceSource]:
    """One-shot load of every distinct source referenced by a list result.

    Avoids N+1 lookups when serializing list responses with per-row
    source chips.
    """
    cleaned: set[UUID] = {sid for sid in source_ids if sid is not None}
    if not cleaned:
        return {}
    result = await db.execute(select(MarketplaceSource).where(MarketplaceSource.id.in_(cleaned)))
    out: dict[UUID, MarketplaceSource] = {}
    for src in result.scalars().all():
        out[src.id] = src  # type: ignore[index]
    return out


def lookup_source(
    sources: dict[UUID, MarketplaceSource], source_id: Any
) -> MarketplaceSource | None:
    """Type-erasing dict lookup for a per-row source."""
    if source_id is None:
        return None
    return sources.get(source_id)
