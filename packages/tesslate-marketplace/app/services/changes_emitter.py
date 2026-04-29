"""
Append a row to `changes_events` for every catalog mutation.

The orchestrator's federation client polls `/v1/changes?since=<etag>` and
applies every event in order. Tombstones (`delete`, `deactivate`,
`version_remove`, `yank`, `pricing_change`) are first-class — listed alongside
`upsert` rather than backfilled from a separate diff.

`etag` is `v{seq}` where `seq` is the auto-increment PK on the table. Because
`AsyncSession.flush()` resolves the PK before commit, we can compute the etag
inline.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChangesEvent

VALID_OPS: tuple[str, ...] = (
    "upsert",
    "delete",
    "deactivate",
    "yank",
    "version_remove",
    "pricing_change",
)


async def emit(
    session: AsyncSession,
    *,
    op: str,
    kind: str,
    slug: str,
    version: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ChangesEvent:
    """Insert a `ChangesEvent` row.

    The caller is responsible for committing the surrounding transaction.
    """
    if op not in VALID_OPS:
        raise ValueError(f"invalid changes op: {op!r}")
    event = ChangesEvent(
        # Placeholder etag, replaced after flush so it includes the seq id.
        etag="v0",
        op=op,
        kind=kind,
        slug=slug,
        version=version,
        payload=payload,
    )
    session.add(event)
    await session.flush()
    event.etag = f"v{event.seq}"
    return event


def parse_etag(value: str | None) -> int:
    """Convert `v123` -> 123. Empty or invalid input becomes 0."""
    if not value:
        return 0
    raw = value.strip()
    if not raw:
        return 0
    if raw.startswith("v") or raw.startswith("V"):
        raw = raw[1:]
    try:
        return max(0, int(raw))
    except ValueError:
        return 0
