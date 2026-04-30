"""
GET  /v1/items/{kind}/{slug}/pricing — pricing detail.
POST /v1/items/{kind}/{slug}/checkout — Stripe Connect compatible checkout.
GET  /dev/checkout/{session_id}      — dev simulator landing page.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..database import get_session
from ..models import PriceListing
from ..schemas import (
    CheckoutRequest,
    CheckoutResponse,
    PricingDetail,
    PricingPayload,
    PricingUpdate,
)
from ..services import changes_emitter
from ..services.auth import Principal, get_principal
from ..services.capability_router import requires_capability
from ..services.stripe_client import get_stripe_client
from .items import _load_item_or_404, _pricing_from_item

router = APIRouter(prefix="/v1", tags=["pricing"])
dev_router = APIRouter(prefix="/dev", tags=["dev-checkout"])


@router.get("/items/{kind}/{slug}/pricing", response_model=PricingDetail)
@requires_capability("pricing.read")
async def get_pricing(
    kind: str,
    slug: str,
    db: AsyncSession = Depends(get_session),
) -> PricingDetail:
    item = await _load_item_or_404(db, kind, slug)
    listings = (
        await db.execute(
            select(PriceListing).where(PriceListing.item_id == item.id, PriceListing.is_active.is_(True))
        )
    ).scalars().all()
    return PricingDetail(
        pricing=_pricing_from_item(item),
        listings=[
            {
                "pricing_type": listing.pricing_type,
                "interval": listing.interval,
                "currency": listing.currency,
                "amount_cents": listing.amount_cents,
                "stripe_price_id": listing.stripe_price_id,
                "is_active": listing.is_active,
            }
            for listing in listings
        ],
    )


@router.post("/items/{kind}/{slug}/checkout", response_model=CheckoutResponse)
@requires_capability("pricing.checkout")
async def create_checkout(
    kind: str,
    slug: str,
    payload: CheckoutRequest,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> CheckoutResponse:
    item = await _load_item_or_404(db, kind, slug)
    pricing: PricingPayload = _pricing_from_item(item)

    if pricing.pricing_type == "free":
        raise HTTPException(
            status_code=400,
            detail={"error": "item_is_free", "kind": kind, "slug": slug},
        )
    if pricing.price_cents <= 0 and not pricing.stripe_price_id:
        raise HTTPException(
            status_code=400,
            detail={"error": "missing_pricing_metadata", "kind": kind, "slug": slug},
        )

    client = get_stripe_client(settings)
    result = client.create_checkout(
        item_kind=item.kind,
        item_slug=item.slug,
        item_name=item.name,
        amount_cents=pricing.price_cents,
        currency=pricing.currency,
        customer_email=payload.customer_email,
        success_url=payload.success_url,
        cancel_url=payload.cancel_url,
        metadata=payload.metadata,
        stripe_price_id=pricing.stripe_price_id,
    )

    return CheckoutResponse(
        checkout_url=result.checkout_url,
        session_id=result.session_id,
        mode=result.mode,
        expires_at=None,
    )


@router.patch("/items/{kind}/{slug}/pricing", response_model=PricingDetail)
@requires_capability("pricing.write")
async def update_pricing(
    kind: str,
    slug: str,
    payload: PricingUpdate,
    db: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> PricingDetail:
    """Admin update for an item's pricing snapshot.

    Mutates `item.pricing_type`, `item.price_cents`, `item.stripe_price_id`,
    and the cached `pricing_payload` in place, then emits a `pricing_change`
    tombstone with `from`/`to` deltas so federated orchestrators can apply
    their own stripping rules per source trust level.
    """
    principal.require_scope("pricing.write")
    item = await _load_item_or_404(db, kind, slug)

    before = {
        "pricing_type": item.pricing_type,
        "price_cents": item.price_cents,
        "stripe_price_id": item.stripe_price_id,
        "currency": (item.pricing_payload or {}).get("currency", "usd"),
        "interval": (item.pricing_payload or {}).get("interval"),
    }

    new_pricing_type = payload.pricing_type or item.pricing_type
    if payload.pricing_type == "free":
        new_price_cents = 0
        new_stripe_price_id = None
    else:
        new_price_cents = payload.price_cents if payload.price_cents is not None else item.price_cents
        new_stripe_price_id = (
            payload.stripe_price_id
            if payload.stripe_price_id is not None
            else item.stripe_price_id
        )
    new_currency = payload.currency or before["currency"]
    new_interval = payload.interval if payload.interval is not None else before["interval"]

    item.pricing_type = new_pricing_type
    item.price_cents = new_price_cents
    item.stripe_price_id = new_stripe_price_id
    item.pricing_payload = {
        "pricing_type": new_pricing_type,
        "price_cents": new_price_cents,
        "stripe_price_id": new_stripe_price_id,
        "currency": new_currency,
        "interval": new_interval,
    }

    after = {
        "pricing_type": item.pricing_type,
        "price_cents": item.price_cents,
        "stripe_price_id": item.stripe_price_id,
        "currency": new_currency,
        "interval": new_interval,
    }

    await db.flush()
    if before != after:
        await changes_emitter.emit(
            db,
            op="pricing_change",
            kind=kind,
            slug=slug,
            payload={"from": before, "to": after, "actor": principal.handle},
        )
    await db.commit()

    listings = (
        await db.execute(
            select(PriceListing).where(PriceListing.item_id == item.id, PriceListing.is_active.is_(True))
        )
    ).scalars().all()
    return PricingDetail(
        pricing=_pricing_from_item(item),
        listings=[
            {
                "pricing_type": listing.pricing_type,
                "interval": listing.interval,
                "currency": listing.currency,
                "amount_cents": listing.amount_cents,
                "stripe_price_id": listing.stripe_price_id,
                "is_active": listing.is_active,
            }
            for listing in listings
        ],
    )


@dev_router.get("/checkout/{session_id}", response_class=HTMLResponse)
async def dev_checkout_landing(session_id: str) -> HTMLResponse:
    """Dev-mode placeholder used only when STRIPE_API_KEY is unset.

    The real Stripe Checkout flow ships when the env var is configured.
    """
    body = f"""
    <!doctype html>
    <html>
    <head><meta charset="utf-8"><title>Tesslate Marketplace · Dev Checkout</title></head>
    <body style="font-family: system-ui; max-width: 480px; margin: 64px auto; padding: 32px; border: 1px solid #eee; border-radius: 12px;">
      <h1 style="font-size: 18px; margin-top: 0;">Dev checkout simulator</h1>
      <p>Session <code>{session_id}</code> would have launched a Stripe Checkout flow in production.</p>
      <p>Configure <code>STRIPE_API_KEY</code> on the marketplace service to enable live payments.</p>
      <p style="opacity: 0.6; font-size: 12px;">Generated at {datetime.now(tz=timezone.utc).isoformat()}</p>
    </body>
    </html>
    """
    return HTMLResponse(content=body)
