"""
GET /v1/changes — incremental sync feed with tombstones.
GET /v1/yanks  — focused subset of `changes` filtered to yank ops only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..database import get_session
from ..models import ChangesEvent
from ..schemas import ChangeEvent, ChangesFeed, YankFeed
from ..services.capability_router import requires_capability
from ..services.changes_emitter import parse_etag
from ..services.sync_helpers import clamp_limit

router = APIRouter(prefix="/v1", tags=["changes"])


def _serialize(event: ChangesEvent) -> ChangeEvent:
    return ChangeEvent(
        op=event.op,
        kind=event.kind,
        slug=event.slug,
        version=event.version,
        etag=event.etag,
        payload=event.payload,
        created_at=event.created_at,
    )


@router.get("/changes", response_model=ChangesFeed)
@requires_capability("catalog.changes")
async def get_changes(
    since: str | None = Query(None),
    limit: int | None = Query(None),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ChangesFeed:
    page_limit = clamp_limit(limit, settings.pagination_default_limit, settings.pagination_max_limit)
    cursor = parse_etag(since)
    stmt = (
        select(ChangesEvent)
        .where(ChangesEvent.seq > cursor)
        .order_by(asc(ChangesEvent.seq))
        .limit(page_limit + 1)
    )
    rows = (await db.execute(stmt)).scalars().all()
    has_more = len(rows) > page_limit
    rows = list(rows[:page_limit])

    if rows:
        next_etag = rows[-1].etag
    else:
        # Caller is fully caught up — surface the tip so subsequent polls
        # short-circuit immediately.
        last = (
            await db.execute(select(ChangesEvent).order_by(ChangesEvent.seq.desc()).limit(1))
        ).scalar_one_or_none()
        next_etag = last.etag if last else (since or "v0")

    return ChangesFeed(
        events=[_serialize(r) for r in rows],
        next_etag=next_etag,
        has_more=has_more,
    )


@router.get("/yanks", response_model=YankFeed)
@requires_capability("yanks.feed")
async def get_yanks_feed(
    since: str | None = Query(None),
    limit: int | None = Query(None),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> YankFeed:
    page_limit = clamp_limit(limit, settings.pagination_default_limit, settings.pagination_max_limit)
    cursor = parse_etag(since)
    stmt = (
        select(ChangesEvent)
        .where(ChangesEvent.seq > cursor, ChangesEvent.op.in_(["yank", "version_remove"]))
        .order_by(asc(ChangesEvent.seq))
        .limit(page_limit + 1)
    )
    rows = (await db.execute(stmt)).scalars().all()
    has_more = len(rows) > page_limit
    rows = list(rows[:page_limit])

    if rows:
        next_etag = rows[-1].etag
    else:
        last = (
            await db.execute(
                select(ChangesEvent)
                .where(ChangesEvent.op.in_(["yank", "version_remove"]))
                .order_by(ChangesEvent.seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        next_etag = last.etag if last else (since or "v0")

    return YankFeed(
        events=[_serialize(r) for r in rows],
        next_etag=next_etag,
        has_more=has_more,
    )
