"""Tesslate Apps billing router (Wave 3).

Wallet + spend query endpoints for installers and creators, plus a
superuser-only spend-record writer (the worker-issued HMAC surface
arrives in a later wave).

Decimal serialization: all USD values are cast to ``float`` with 6-decimal
precision for JSON responses. The DB stores ``Numeric(12, 6)``; the router
boundary does the conversion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import SpendRecord, Wallet, WalletLedgerEntry
from ..models_auth import User
from ..services.apps import billing_dispatcher
from ..services.apps.settlement_worker import find_or_create_wallet
from ..users import current_active_user, current_superuser

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _money(x: Decimal | int | float | None) -> float:
    if x is None:
        return 0.0
    return round(float(Decimal(str(x))), 6)


def _sid(x: Any) -> str | None:
    return str(x) if x else None


def _wallet_view(w: Wallet) -> dict[str, Any]:
    return {
        "id": str(w.id),
        "balance_usd": _money(w.balance_usd),
        "state": w.state,
        "owner_type": w.owner_type,
        "created_at": w.created_at,
        "updated_at": w.updated_at,
    }


def _ledger_view(e: WalletLedgerEntry) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "wallet_id": str(e.wallet_id),
        "delta_usd": _money(e.delta_usd),
        "kind": e.kind,
        "reference_type": e.reference_type,
        "reference_id": _sid(e.reference_id),
        "meta": e.meta or {},
        "created_at": e.created_at,
    }


def _spend_view(r: SpendRecord) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "app_instance_id": _sid(r.app_instance_id),
        "session_id": _sid(r.session_id),
        "installer_user_id": _sid(r.installer_user_id),
        "dimension": r.dimension,
        "payer": r.payer,
        "payer_user_id": _sid(r.payer_user_id),
        "amount_usd": _money(r.amount_usd),
        "litellm_key_id": r.litellm_key_id,
        "usage_log_id": _sid(r.usage_log_id),
        "settled": r.settled,
        "settled_at": r.settled_at,
        "meta": r.meta or {},
        "created_at": r.created_at,
    }


# ---------------------------------------------------------------------------
# Wallet endpoints
# ---------------------------------------------------------------------------


@router.get("/wallet")
async def get_installer_wallet(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> dict[str, Any]:
    w = await find_or_create_wallet(db, owner_type="installer", owner_user_id=user.id)
    return _wallet_view(w)


@router.get("/wallet/creator")
async def get_creator_wallet(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> dict[str, Any]:
    if not getattr(user, "creator_stripe_account_id", None):
        raise HTTPException(status_code=403, detail="not a registered creator (no stripe account)")
    w = await find_or_create_wallet(db, owner_type="creator", owner_user_id=user.id)
    return _wallet_view(w)


class LedgerResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


@router.get("/wallet/ledger", response_model=LedgerResponse)
async def get_wallet_ledger(
    wallet_type: str | None = Query(default=None, pattern="^(installer|creator)$"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    since: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> LedgerResponse:
    types_filter = [wallet_type] if wallet_type else ["installer", "creator"]
    wallet_rows = (
        (
            await db.execute(
                select(Wallet.id).where(
                    and_(
                        Wallet.owner_user_id == user.id,
                        Wallet.owner_type.in_(types_filter),
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    if not wallet_rows:
        return LedgerResponse(items=[], total=0, limit=limit, offset=offset)
    where = [WalletLedgerEntry.wallet_id.in_(wallet_rows)]
    if since is not None:
        where.append(WalletLedgerEntry.created_at >= since)
    total = (
        await db.execute(select(func.count()).select_from(WalletLedgerEntry).where(and_(*where)))
    ).scalar_one()
    rows = (
        (
            await db.execute(
                select(WalletLedgerEntry)
                .where(and_(*where))
                .order_by(desc(WalletLedgerEntry.created_at))
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return LedgerResponse(
        items=[_ledger_view(r) for r in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Spend endpoints
# ---------------------------------------------------------------------------


class SpendResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


@router.get("/spend", response_model=SpendResponse)
async def get_spend(
    app_instance_id: UUID | None = Query(default=None),
    dimension: str | None = Query(default=None),
    settled: bool | None = Query(default=None),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> SpendResponse:
    where: list[Any] = [SpendRecord.installer_user_id == user.id]
    if app_instance_id is not None:
        where.append(SpendRecord.app_instance_id == app_instance_id)
    if dimension is not None:
        where.append(SpendRecord.dimension == dimension)
    if settled is not None:
        where.append(SpendRecord.settled == settled)
    if since is not None:
        where.append(SpendRecord.created_at >= since)
    total = (
        await db.execute(select(func.count()).select_from(SpendRecord).where(and_(*where)))
    ).scalar_one()
    rows = (
        (
            await db.execute(
                select(SpendRecord)
                .where(and_(*where))
                .order_by(desc(SpendRecord.created_at))
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return SpendResponse(
        items=[_spend_view(r) for r in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


@router.get("/spend/summary")
async def get_spend_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> dict[str, Any]:
    now = datetime.now(UTC)
    w30 = now - timedelta(days=30)
    w7 = now - timedelta(days=7)
    w24 = now - timedelta(hours=24)

    base = SpendRecord.installer_user_id == user.id

    async def _sum(window_start: datetime) -> float:
        v = (
            await db.execute(
                select(func.coalesce(func.sum(SpendRecord.amount_usd), 0)).where(
                    and_(base, SpendRecord.created_at >= window_start)
                )
            )
        ).scalar_one()
        return _money(v)

    total_30 = await _sum(w30)
    total_7 = await _sum(w7)
    total_24 = await _sum(w24)

    async def _sum_settled(s: bool) -> Any:
        return (
            await db.execute(
                select(func.coalesce(func.sum(SpendRecord.amount_usd), 0)).where(
                    and_(base, SpendRecord.settled.is_(s), SpendRecord.created_at >= w30)
                )
            )
        ).scalar_one()

    settled_total = await _sum_settled(True)
    unsettled_total = await _sum_settled(False)

    per_dim_rows = (
        await db.execute(
            select(SpendRecord.dimension, func.coalesce(func.sum(SpendRecord.amount_usd), 0))
            .where(and_(base, SpendRecord.created_at >= w30))
            .group_by(SpendRecord.dimension)
        )
    ).all()
    per_app_rows = (
        await db.execute(
            select(SpendRecord.app_instance_id, func.coalesce(func.sum(SpendRecord.amount_usd), 0))
            .where(and_(base, SpendRecord.created_at >= w30))
            .group_by(SpendRecord.app_instance_id)
        )
    ).all()
    return {
        "total_usd_30d": total_30,
        "total_usd_7d": total_7,
        "total_usd_24h": total_24,
        "total_settled_usd": _money(settled_total),
        "total_unsettled_usd": _money(unsettled_total),
        "per_dimension": {str(d): _money(v) for d, v in per_dim_rows},
        "per_app": [{"app_instance_id": _sid(a), "amount_usd": _money(v)} for a, v in per_app_rows],
    }


# ---------------------------------------------------------------------------
# Spend record writer (superuser-only this wave)
# ---------------------------------------------------------------------------


class SpendRecordRequest(BaseModel):
    app_instance_id: UUID
    installer_user_id: UUID
    dimension: str
    amount_usd: float = Field(ge=0)
    session_id: UUID | None = None
    litellm_key_id: str | None = None
    usage_log_id: UUID | None = None
    is_byok: bool = False
    meta: dict[str, Any] | None = None


@router.post("/spend/record", status_code=status.HTTP_201_CREATED)
async def post_spend_record(
    body: SpendRecordRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(current_superuser),
) -> dict[str, Any]:
    try:
        outcome = await billing_dispatcher.record_spend(
            db,
            app_instance_id=body.app_instance_id,
            installer_user_id=body.installer_user_id,
            dimension=body.dimension,  # type: ignore[arg-type]
            amount_usd=Decimal(str(body.amount_usd)),
            session_id=body.session_id,
            litellm_key_id=body.litellm_key_id,
            usage_log_id=body.usage_log_id,
            is_byok=body.is_byok,
            meta=body.meta,
        )
    except billing_dispatcher.MissingWalletMixError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except billing_dispatcher.UnknownDimensionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "spend_record_id": str(outcome.spend_record_id),
        "payer": outcome.payer,
        "amount_usd": _money(outcome.amount_usd),
        "dimension": outcome.dimension,
    }


# ---------------------------------------------------------------------------
# Platform wallet admin
# ---------------------------------------------------------------------------


@router.get("/wallet/admin/platform")
async def get_platform_wallet(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(current_superuser),
) -> dict[str, Any]:
    w = await find_or_create_wallet(db, owner_type="platform", owner_user_id=None)
    entries = (
        (
            await db.execute(
                select(WalletLedgerEntry)
                .where(WalletLedgerEntry.wallet_id == w.id)
                .order_by(desc(WalletLedgerEntry.created_at))
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return {
        "wallet": _wallet_view(w),
        "recent_entries": [_ledger_view(e) for e in entries],
    }
