"""GET /v1/categories — kind-scoped category index."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import KINDS
from ..database import get_session
from ..models import Category
from ..schemas import CategoryList, CategoryOut
from ..services.capability_router import requires_capability

router = APIRouter(prefix="/v1", tags=["categories"])


@router.get("/categories", response_model=CategoryList)
@requires_capability("catalog.categories")
async def list_categories(
    kind: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> CategoryList:
    if kind is not None and kind not in KINDS:
        raise HTTPException(
            status_code=400, detail={"error": "unknown_kind", "kind": kind, "allowed": list(KINDS)}
        )
    stmt = select(Category).order_by(asc(Category.kind), asc(Category.sort_order), asc(Category.name))
    if kind:
        stmt = stmt.where(Category.kind == kind)
    rows = (await db.execute(stmt)).scalars().all()
    return CategoryList(categories=[CategoryOut.model_validate(r) for r in rows])
