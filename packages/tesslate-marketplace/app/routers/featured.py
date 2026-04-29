"""GET /v1/featured — editorial pinned items per kind."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import KINDS
from ..database import get_session
from ..models import FeaturedListing, Item
from ..schemas import FeaturedEntry, FeaturedList
from ..services.capability_router import requires_capability
from .items import _to_summary

router = APIRouter(prefix="/v1", tags=["featured"])


@router.get("/featured", response_model=FeaturedList)
@requires_capability("catalog.featured")
async def list_featured(
    kind: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> FeaturedList:
    if kind is not None and kind not in KINDS:
        raise HTTPException(
            status_code=400, detail={"error": "unknown_kind", "kind": kind, "allowed": list(KINDS)}
        )
    stmt = (
        select(FeaturedListing, Item)
        .join(Item, Item.id == FeaturedListing.item_id)
        .where(Item.is_active.is_(True), Item.is_published.is_(True))
        .order_by(asc(FeaturedListing.kind), asc(FeaturedListing.rank))
    )
    if kind:
        stmt = stmt.where(FeaturedListing.kind == kind)

    rows = (await db.execute(stmt)).all()
    out: list[FeaturedEntry] = []
    for listing, item in rows:
        out.append(FeaturedEntry(item=_to_summary(item), rank=listing.rank, note=listing.note))
    return FeaturedList(featured=out)
