"""
Billing and subscription management endpoints.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import CreditPurchase, MarketplaceTransaction, UsageLog
from ..models_auth import User as AuthUser
from ..services.stripe_service import stripe_service
from ..services.usage_service import usage_service
from ..users import current_active_user

router = APIRouter(prefix="/billing", tags=["billing"])
settings = get_settings()


# ============================================================================
# Pydantic Models
# ============================================================================


class SubscriptionResponse(BaseModel):
    """Response model for subscription status."""

    tier: str  # free, basic, pro, ultra
    is_active: bool
    subscription_id: str | None = None
    stripe_customer_id: str | None = None
    max_projects: int
    max_deploys: int
    current_period_start: str | None = None  # ISO format date string
    current_period_end: str | None = None  # ISO format date string
    cancel_at_period_end: bool | None = None
    cancel_at: str | None = None  # ISO format date string
    # New fields for credit system
    bundled_credits: int = 0
    purchased_credits: int = 0
    total_credits: int = 0
    monthly_allowance: int = 0
    credits_reset_date: str | None = None
    byok_enabled: bool = False

    class Config:
        from_attributes = True


class CheckoutSessionResponse(BaseModel):
    """Response model for checkout session."""

    session_id: str
    url: str


class CreditBalanceResponse(BaseModel):
    """Response model for credit balance."""

    bundled_credits: int = 0
    purchased_credits: int = 0
    total_credits: int = 0
    monthly_allowance: int = 0
    credits_reset_date: str | None = None
    tier: str = "free"


class CreditStatusResponse(BaseModel):
    """Response model for credit status (low balance warning)."""

    total_credits: int
    is_low: bool
    is_empty: bool
    threshold: int
    tier: str
    monthly_allowance: int


class CreditPurchaseRequest(BaseModel):
    """Request model for credit purchase."""

    package: str  # small, medium, large


class UsageSummaryResponse(BaseModel):
    """Response model for usage summary."""

    total_cost_cents: int
    total_cost_usd: float
    total_tokens_input: int
    total_tokens_output: int
    total_requests: int
    by_model: dict[str, Any]
    by_agent: dict[str, Any]
    period_start: str
    period_end: str


class TransactionResponse(BaseModel):
    """Response model for transaction."""

    id: str
    type: str
    amount_cents: int
    amount_usd: float
    status: str
    created_at: str


# ============================================================================
# Subscription Endpoints
# ============================================================================


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    user: AuthUser = Depends(current_active_user), db: AsyncSession = Depends(get_db)
):
    """
    Get current subscription status for the user.
    """
    import logging
    from datetime import datetime

    import stripe as stripe_lib

    logger = logging.getLogger(__name__)

    # Use tier-specific limits
    tier = user.subscription_tier or "free"
    max_projects = settings.get_tier_max_projects(tier)
    max_deploys = settings.get_tier_max_deploys(tier)
    monthly_allowance = settings.get_tier_bundled_credits(tier)

    # Calculate total credits
    bundled = user.bundled_credits or 0
    purchased = user.purchased_credits or 0
    total_credits = bundled + purchased

    # Check if BYOK is enabled for this tier
    byok_enabled = tier in settings.byok_tiers_list

    # Fetch subscription details from Stripe if user has an active subscription
    current_period_start = None
    current_period_end = None
    cancel_at_period_end = None
    cancel_at = None

    if tier != "free" and user.stripe_subscription_id and stripe_service.stripe:
        try:
            subscription = stripe_lib.Subscription.retrieve(user.stripe_subscription_id)

            # Use start_date as subscription start
            current_period_start = datetime.fromtimestamp(subscription.start_date).isoformat()

            # Calculate next billing date from billing_cycle_anchor (add 1 month)
            from dateutil.relativedelta import relativedelta

            billing_anchor_date = datetime.fromtimestamp(subscription.billing_cycle_anchor)
            next_billing_date = billing_anchor_date + relativedelta(months=1)
            current_period_end = next_billing_date.isoformat()

            cancel_at_period_end = subscription.cancel_at_period_end
            if subscription.cancel_at:
                cancel_at = datetime.fromtimestamp(subscription.cancel_at).isoformat()
        except Exception as e:
            logger.error(f"Error fetching subscription details for user {user.id}: {e}")

    # Format credits reset date
    credits_reset_date = None
    if user.credits_reset_date:
        credits_reset_date = user.credits_reset_date.isoformat()

    return SubscriptionResponse(
        tier=tier,
        is_active=tier != "free",
        subscription_id=user.stripe_subscription_id,
        stripe_customer_id=user.stripe_customer_id,
        max_projects=max_projects,
        max_deploys=max_deploys,
        current_period_start=current_period_start,
        current_period_end=current_period_end,
        cancel_at_period_end=cancel_at_period_end,
        cancel_at=cancel_at,
        bundled_credits=bundled,
        purchased_credits=purchased,
        total_credits=total_credits,
        monthly_allowance=monthly_allowance,
        credits_reset_date=credits_reset_date,
        byok_enabled=byok_enabled,
    )


class SubscriptionRequest(BaseModel):
    """Request model for subscription."""

    tier: str = "pro"  # basic, pro, or ultra


@router.post("/subscribe", response_model=CheckoutSessionResponse)
async def create_subscription(
    request: Request,
    subscription_request: SubscriptionRequest | None = None,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a checkout session for a subscription tier.
    Supports: basic ($8/mo), pro ($20/mo), ultra ($100/mo)
    """
    # Get requested tier from body or default to pro
    requested_tier = subscription_request.tier if subscription_request else "pro"

    # Validate tier
    valid_tiers = ["basic", "pro", "ultra"]
    if requested_tier not in valid_tiers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier. Must be one of: {', '.join(valid_tiers)}",
        )

    # Get Stripe price ID for tier
    price_id = settings.get_stripe_price_id(requested_tier)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Stripe price ID not configured for tier: {requested_tier}",
        )

    # Check if already subscribed to same or higher tier
    tier_order = {"free": 0, "basic": 1, "pro": 2, "ultra": 3}
    current_tier_level = tier_order.get(user.subscription_tier, 0)
    requested_tier_level = tier_order.get(requested_tier, 0)

    if current_tier_level >= requested_tier_level and user.subscription_tier != "free":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Already subscribed to {user.subscription_tier} tier",
        )

    # Create checkout session with origin-based URLs to preserve user's domain
    origin = (
        request.headers.get("origin")
        or request.headers.get("referer", "").rstrip("/").split("?")[0].rsplit("/", 1)[0]
        or settings.get_app_base_url
    )
    success_url = f"{origin}/settings/billing?success=true&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/settings/billing?cancelled=true"

    session = await stripe_service.create_subscription_checkout(
        user=user, success_url=success_url, cancel_url=cancel_url, db=db, tier=requested_tier
    )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create checkout session",
        )

    return CheckoutSessionResponse(session_id=session["id"], url=session["url"])


@router.post("/cancel")
async def cancel_subscription(
    at_period_end: bool = True,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel the user's subscription.
    """
    if user.subscription_tier == "free":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No active subscription"
        )

    if not user.stripe_subscription_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No subscription ID found"
        )

    success = await stripe_service.cancel_subscription(
        subscription_id=user.stripe_subscription_id, at_period_end=at_period_end
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel subscription",
        )

    # If immediate cancellation, update tier now
    if not at_period_end:
        user.subscription_tier = "free"
        user.stripe_subscription_id = None
        await db.commit()

    return {
        "success": True,
        "message": "Subscription cancelled"
        if not at_period_end
        else "Subscription will cancel at end of period",
    }


@router.post("/renew")
async def renew_subscription(
    user: AuthUser = Depends(current_active_user), db: AsyncSession = Depends(get_db)
):
    """
    Renew a cancelled subscription (reactivate before it ends).
    """
    if user.subscription_tier == "free":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No active subscription"
        )

    if not user.stripe_subscription_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No subscription ID found"
        )

    success = await stripe_service.renew_subscription(subscription_id=user.stripe_subscription_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to renew subscription"
        )

    return {
        "success": True,
        "message": "Subscription has been renewed and will continue after the current period",
    }


@router.get("/portal")
async def get_customer_portal(request: Request, user: AuthUser = Depends(current_active_user)):
    """
    Get Stripe customer portal link for managing subscription.
    """
    if not user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No Stripe customer found"
        )

    if not stripe_service.stripe:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Stripe not configured"
        )

    # Use origin-based URL to preserve user's domain
    origin = (
        request.headers.get("origin")
        or request.headers.get("referer", "").rstrip("/").split("?")[0].rsplit("/", 1)[0]
        or settings.get_app_base_url
    )

    try:
        portal_session = stripe_service.stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id, return_url=f"{origin}/billing"
        )

        return {"url": portal_session.url}
    except Exception as e:
        error_msg = str(e)
        # Check if it's a portal configuration error
        if (
            "No configuration" in error_msg
            or "default configuration has not been created" in error_msg
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Stripe Customer Portal not configured. Please use Library > Subscriptions tab to manage your subscription, or contact support.",
            ) from e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create portal session: {error_msg}",
        ) from e


# ============================================================================
# Credits Endpoints
# ============================================================================


@router.get("/credits", response_model=CreditBalanceResponse)
async def get_credits_balance(user: AuthUser = Depends(current_active_user)):
    """
    Get user's current credit balance.
    Returns both bundled (monthly) and purchased (permanent) credits.
    """
    tier = user.subscription_tier or "free"
    bundled = user.bundled_credits or 0
    purchased = user.purchased_credits or 0
    total = bundled + purchased
    monthly_allowance = settings.get_tier_bundled_credits(tier)

    # Format credits reset date
    credits_reset_date = None
    if user.credits_reset_date:
        credits_reset_date = user.credits_reset_date.isoformat()

    return CreditBalanceResponse(
        bundled_credits=bundled,
        purchased_credits=purchased,
        total_credits=total,
        monthly_allowance=monthly_allowance,
        credits_reset_date=credits_reset_date,
        tier=tier,
    )


@router.get("/credits/status", response_model=CreditStatusResponse)
async def get_credit_status(user: AuthUser = Depends(current_active_user)):
    """
    Get credit status for low balance warning.
    Returns is_low=True when at 20% or below, is_empty=True when credits = 0.
    """
    tier = user.subscription_tier or "free"
    bundled = user.bundled_credits or 0
    purchased = user.purchased_credits or 0
    total = bundled + purchased
    monthly_allowance = settings.get_tier_bundled_credits(tier)

    # Calculate threshold (20% of monthly allowance)
    threshold = int(monthly_allowance * settings.credits_low_balance_threshold)

    return CreditStatusResponse(
        total_credits=total,
        is_low=total <= threshold and total > 0,
        is_empty=total <= 0,
        threshold=threshold,
        tier=tier,
        monthly_allowance=monthly_allowance,
    )


@router.post("/credits/purchase", response_model=CheckoutSessionResponse)
async def purchase_credits(
    request: CreditPurchaseRequest,
    http_request: Request,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a checkout session for purchasing credits.
    """
    # Determine amount based on package
    package_amounts = {
        "small": settings.credit_package_small,
        "medium": settings.credit_package_medium,
        "large": settings.credit_package_large,
    }

    if request.package not in package_amounts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid package. Must be: small, medium, or large",
        )

    amount_cents = package_amounts[request.package]

    # Create checkout session with origin-based URLs to preserve user's domain
    origin = (
        http_request.headers.get("origin")
        or http_request.headers.get("referer", "").rstrip("/").split("?")[0].rsplit("/", 1)[0]
        or settings.get_app_base_url
    )
    success_url = f"{origin}/billing/credits/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/billing/credits/cancel"

    session = await stripe_service.create_credit_purchase_checkout(
        user=user, amount_cents=amount_cents, success_url=success_url, cancel_url=cancel_url, db=db
    )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create checkout session",
        )

    return CheckoutSessionResponse(session_id=session["id"], url=session["url"])


@router.get("/credits/history")
async def get_credit_purchase_history(
    limit: int = 50,
    offset: int = 0,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get user's credit purchase history.
    """
    result = await db.execute(
        select(CreditPurchase)
        .where(CreditPurchase.user_id == user.id)
        .order_by(CreditPurchase.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    purchases = result.scalars().all()

    return {
        "purchases": [
            {
                "id": str(p.id),
                "amount_cents": p.amount_cents,
                "amount_usd": p.amount_cents / 100,
                "credits_amount": p.credits_amount,
                "status": p.status,
                "created_at": p.created_at.isoformat(),
                "completed_at": p.completed_at.isoformat() if p.completed_at else None,
            }
            for p in purchases
        ]
    }


# ============================================================================
# Usage Endpoints
# ============================================================================


@router.get("/usage", response_model=UsageSummaryResponse)
async def get_usage_summary(
    start_date: str | None = None,
    end_date: str | None = None,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get usage summary for a date range.
    Defaults to current month if no dates provided.
    """
    # Parse dates
    if start_date:
        start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    else:
        # Default to start of current month
        now = datetime.now(UTC)
        start = datetime(now.year, now.month, 1, tzinfo=UTC)

    end = datetime.fromisoformat(end_date.replace("Z", "+00:00")) if end_date else datetime.now(UTC)

    # Get usage summary
    summary = await usage_service.get_user_usage_summary(
        user_id=user.id, start_date=start, end_date=end, db=db
    )

    return UsageSummaryResponse(**summary)


@router.post("/usage/sync")
async def sync_usage(
    start_date: str | None = None,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Manually sync usage data from LiteLLM.
    """
    # Parse start date
    if start_date:
        start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    else:
        # Default to 24 hours ago
        start = datetime.now(UTC) - timedelta(days=1)

    # Sync usage
    usage_logs = await usage_service.sync_user_usage(user=user, start_date=start, db=db)

    return {
        "success": True,
        "logs_synced": len(usage_logs),
        "message": f"Synced {len(usage_logs)} usage entries",
    }


@router.get("/usage/logs")
async def get_usage_logs(
    limit: int = 100,
    offset: int = 0,
    start_date: str | None = None,
    end_date: str | None = None,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed usage logs.
    """
    # Build query
    query = select(UsageLog).where(UsageLog.user_id == user.id)

    if start_date:
        start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        query = query.where(UsageLog.created_at >= start)

    if end_date:
        end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        query = query.where(UsageLog.created_at <= end)

    query = query.order_by(UsageLog.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "logs": [
            {
                "id": str(log.id),
                "model": log.model,
                "tokens_input": log.tokens_input,
                "tokens_output": log.tokens_output,
                "cost_total_cents": log.cost_total,
                "cost_total_usd": log.cost_total / 100,
                "agent_id": str(log.agent_id) if log.agent_id else None,
                "project_id": str(log.project_id) if log.project_id else None,
                "billed_status": log.billed_status,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
    }


# ============================================================================
# Transaction History
# ============================================================================


@router.get("/transactions")
async def get_transactions(
    limit: int = 50,
    offset: int = 0,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all transactions (credits, subscriptions, agent purchases).
    """
    # Get credit purchases
    credit_result = await db.execute(
        select(CreditPurchase)
        .where(CreditPurchase.user_id == user.id)
        .order_by(CreditPurchase.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    credits = credit_result.scalars().all()

    # Get marketplace transactions
    transaction_result = await db.execute(
        select(MarketplaceTransaction)
        .where(MarketplaceTransaction.user_id == user.id)
        .order_by(MarketplaceTransaction.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    transactions = transaction_result.scalars().all()

    # Combine and format
    all_transactions = []

    for credit in credits:
        all_transactions.append(
            {
                "id": str(credit.id),
                "type": "credit_purchase",
                "amount_cents": credit.amount_cents,
                "amount_usd": credit.amount_cents / 100,
                "status": credit.status,
                "created_at": credit.created_at.isoformat(),
            }
        )

    for trans in transactions:
        all_transactions.append(
            {
                "id": str(trans.id),
                "type": trans.transaction_type,
                "amount_cents": trans.amount_total,
                "amount_usd": trans.amount_total / 100,
                "status": "completed",
                "agent_id": str(trans.agent_id) if trans.agent_id else None,
                "created_at": trans.created_at.isoformat(),
            }
        )

    # Sort by created_at
    all_transactions.sort(key=lambda x: x["created_at"], reverse=True)

    return {"transactions": all_transactions[:limit]}


# ============================================================================
# Creator Earnings (for marketplace creators)
# ============================================================================


@router.get("/earnings")
async def get_creator_earnings(
    start_date: str | None = None,
    end_date: str | None = None,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get earnings from marketplace agents (for creators).
    """
    # Parse dates
    if start_date:
        start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    else:
        # Default to start of current month
        now = datetime.now(UTC)
        start = datetime(now.year, now.month, 1, tzinfo=UTC)

    end = datetime.fromisoformat(end_date.replace("Z", "+00:00")) if end_date else datetime.now(UTC)

    # Get earnings
    earnings = await usage_service.get_creator_earnings(
        creator_id=user.id, start_date=start, end_date=end, db=db
    )

    return earnings


@router.post("/connect")
async def connect_stripe_account(
    request: Request,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create Stripe Connect onboarding link for receiving payouts.
    """
    # Use origin-based URLs to preserve user's domain
    origin = (
        request.headers.get("origin")
        or request.headers.get("referer", "").rstrip("/").split("?")[0].rsplit("/", 1)[0]
        or settings.get_app_base_url
    )
    refresh_url = f"{origin}/billing/connect/refresh"
    return_url = f"{origin}/billing/connect/complete"

    url = await stripe_service.create_connect_account_link(
        user=user, refresh_url=refresh_url, return_url=return_url, db=db
    )

    if not url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create Connect account link",
        )

    return {"url": url}


# ============================================================================
# Stripe Publishable Key (for frontend)
# ============================================================================


@router.get("/config")
async def get_billing_config():
    """
    Get public billing configuration for frontend.
    """
    return {
        "stripe_publishable_key": settings.stripe_publishable_key,
        "credit_packages": {
            "small": {"credits": 500, "price_cents": settings.credit_package_small},
            "medium": {"credits": 1000, "price_cents": settings.credit_package_medium},
        },
        "deploy_price": settings.additional_deploy_price,
        "tiers": {
            "free": {
                "price_cents": settings.tier_price_free,
                "max_projects": settings.tier_max_projects_free,
                "max_deploys": settings.tier_max_deploys_free,
                "bundled_credits": settings.tier_bundled_credits_free,
                "byok_enabled": False,
            },
            "basic": {
                "price_cents": settings.tier_price_basic,
                "max_projects": settings.tier_max_projects_basic,
                "max_deploys": settings.tier_max_deploys_basic,
                "bundled_credits": settings.tier_bundled_credits_basic,
                "byok_enabled": False,
            },
            "pro": {
                "price_cents": settings.tier_price_pro,
                "max_projects": settings.tier_max_projects_pro,
                "max_deploys": settings.tier_max_deploys_pro,
                "bundled_credits": settings.tier_bundled_credits_pro,
                "byok_enabled": True,
            },
            "ultra": {
                "price_cents": settings.tier_price_ultra,
                "max_projects": settings.tier_max_projects_ultra,
                "max_deploys": settings.tier_max_deploys_ultra,
                "bundled_credits": settings.tier_bundled_credits_ultra,
                "byok_enabled": True,
            },
        },
        "low_balance_threshold": settings.credits_low_balance_threshold,
    }
