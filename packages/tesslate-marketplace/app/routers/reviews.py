"""Reviews — read list, read aggregate, write per-user review."""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Item, Review, ReviewAggregate
from ..schemas import (
    ReviewAggregateOut,
    ReviewCreate,
    ReviewList,
    ReviewOut,
)
from ..services.auth import Principal, get_principal
from ..services.capability_router import requires_capability
from .items import _load_item_or_404

router = APIRouter(prefix="/v1", tags=["reviews"])


@router.get("/items/{kind}/{slug}/reviews", response_model=ReviewList)
@requires_capability("reviews.read")
async def list_reviews(
    kind: str,
    slug: str,
    db: AsyncSession = Depends(get_session),
) -> ReviewList:
    item = await _load_item_or_404(db, kind, slug)
    rows = (
        await db.execute(
            select(Review).where(Review.item_id == item.id).order_by(desc(Review.created_at))
        )
    ).scalars().all()
    return ReviewList(reviews=[ReviewOut.model_validate(r, from_attributes=True) for r in rows])


@router.get("/items/{kind}/{slug}/reviews/aggregate", response_model=ReviewAggregateOut)
@requires_capability("reviews.aggregates")
async def get_review_aggregate(
    kind: str,
    slug: str,
    db: AsyncSession = Depends(get_session),
) -> ReviewAggregateOut:
    item = await _load_item_or_404(db, kind, slug)
    row = (
        await db.execute(select(ReviewAggregate).where(ReviewAggregate.item_id == item.id))
    ).scalar_one_or_none()
    if row is None:
        return ReviewAggregateOut(count=0, mean=0.0, distribution={str(i): 0 for i in range(1, 6)})
    return ReviewAggregateOut.model_validate(row, from_attributes=True)


async def _recompute_aggregate(db: AsyncSession, item: Item) -> None:
    rows = (await db.execute(select(Review).where(Review.item_id == item.id))).scalars().all()
    counts = Counter(r.rating for r in rows)
    distribution = {str(i): counts.get(i, 0) for i in range(1, 6)}
    total = sum(r.rating for r in rows)
    n = len(rows)
    mean = (total / n) if n else 0.0

    aggregate = (
        await db.execute(select(ReviewAggregate).where(ReviewAggregate.item_id == item.id))
    ).scalar_one_or_none()
    if aggregate is None:
        aggregate = ReviewAggregate(item_id=item.id, count=n, mean=mean, distribution=distribution)
        db.add(aggregate)
    else:
        aggregate.count = n
        aggregate.mean = mean
        aggregate.distribution = distribution

    item.rating = mean
    item.reviews_count = n


@router.post("/items/{kind}/{slug}/reviews", response_model=ReviewOut, status_code=201)
@requires_capability("reviews.write")
async def create_review(
    kind: str,
    slug: str,
    payload: ReviewCreate,
    db: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> ReviewOut:
    principal.require_scope("reviews.write")
    item = await _load_item_or_404(db, kind, slug)
    handle = payload.reviewer_handle or principal.handle
    if not handle:
        raise HTTPException(status_code=400, detail={"error": "missing_reviewer_handle"})

    review = Review(
        item_id=item.id,
        rating=payload.rating,
        title=payload.title,
        body=payload.body,
        reviewer_handle=handle,
    )
    db.add(review)
    await db.flush()
    await _recompute_aggregate(db, item)
    await db.commit()
    await db.refresh(review)
    return ReviewOut.model_validate(review, from_attributes=True)
