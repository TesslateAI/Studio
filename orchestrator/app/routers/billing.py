"""
Billing and subscription management endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from uuid import UUID

from ..database import get_db
from ..users import current_active_user
from ..models import User, CreditPurchase, UsageLog, MarketplaceTransaction
from ..models_auth import User as AuthUser
from ..services.stripe_service import stripe_service
from ..services.usage_service import usage_service
from ..config import get_settings

router = APIRouter(prefix="/billing", tags=["billing"])
settings = get_settings()


# ============================================================================
# Pydantic Models
# ============================================================================

class SubscriptionResponse(BaseModel):
    """Response model for subscription status."""
    tier: str
    is_active: bool
    subscription_id: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    max_projects: int
    max_deploys: int
    current_period_start: Optional[str] = None  # ISO format date string
    current_period_end: Optional[str] = None    # ISO format date string
    cancel_at_period_end: Optional[bool] = None
    cancel_at: Optional[str] = None             # ISO format date string

    class Config:
        from_attributes = True


class CheckoutSessionResponse(BaseModel):
    """Response model for checkout session."""
    session_id: str
    url: str


class CreditBalanceResponse(BaseModel):
    """Response model for credit balance."""
    balance_cents: int
    balance_usd: float


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
    by_model: Dict[str, Any]
    by_agent: Dict[str, Any]
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
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current subscription status for the user.
    """
    from datetime import datetime
    import stripe as stripe_lib

    # Determine limits based on tier
    if user.subscription_tier == "pro":
        max_projects = settings.premium_max_projects
        max_deploys = settings.premium_max_deploys
    else:
        max_projects = settings.free_max_projects
        max_deploys = settings.free_max_deploys

    # Fetch subscription details from Stripe if user has an active subscription
    current_period_start = None
    current_period_end = None
    cancel_at_period_end = None
    cancel_at = None

    if user.subscription_tier == "pro" and user.stripe_subscription_id and stripe_service.stripe:
        try:
            subscription = stripe_lib.Subscription.retrieve(user.stripe_subscription_id)
            # Stripe objects support both attribute and dict access
            print(f"DEBUG: Subscription type: {type(subscription)}")
            print(f"DEBUG: Subscription keys: {dir(subscription)[:10]}")

            # Stripe subscription object - access directly via attributes
            # start_date = when subscription was created
            # billing_cycle_anchor = current period start (Unix timestamp)
            print(f"DEBUG: Accessing subscription attributes directly")
            print(f"DEBUG: start_date = {subscription.start_date}")
            print(f"DEBUG: billing_cycle_anchor = {subscription.billing_cycle_anchor}")

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
            # Log error but don't fail the request
            print(f"Error fetching subscription details: {e}")
            import traceback
            traceback.print_exc()

    return SubscriptionResponse(
        tier=user.subscription_tier,
        is_active=user.subscription_tier != "free",
        subscription_id=user.stripe_subscription_id,
        stripe_customer_id=user.stripe_customer_id,
        max_projects=max_projects,
        max_deploys=max_deploys,
        current_period_start=current_period_start,
        current_period_end=current_period_end,
        cancel_at_period_end=cancel_at_period_end,
        cancel_at=cancel_at
    )


@router.post("/subscribe", response_model=CheckoutSessionResponse)
async def create_subscription(
    request: Request,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a checkout session for premium subscription.
    """
    # Check if already subscribed
    if user.subscription_tier == "pro":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already subscribed to premium"
        )

    # Create checkout session with origin-based URLs to preserve user's domain
    origin = request.headers.get('origin') or request.headers.get('referer', '').rstrip('/').split('?')[0].rsplit('/', 1)[0] or settings.get_app_base_url
    success_url = f"{origin}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/billing/cancel"

    session = await stripe_service.create_subscription_checkout(
        user=user,
        success_url=success_url,
        cancel_url=cancel_url,
        db=db
    )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create checkout session"
        )

    return CheckoutSessionResponse(
        session_id=session["id"],
        url=session["url"]
    )


@router.post("/cancel")
async def cancel_subscription(
    at_period_end: bool = True,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel the user's subscription.
    """
    if user.subscription_tier == "free":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active subscription"
        )

    if not user.stripe_subscription_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No subscription ID found"
        )

    success = await stripe_service.cancel_subscription(
        subscription_id=user.stripe_subscription_id,
        at_period_end=at_period_end
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel subscription"
        )

    # If immediate cancellation, update tier now
    if not at_period_end:
        user.subscription_tier = "free"
        user.stripe_subscription_id = None
        await db.commit()

    return {
        "success": True,
        "message": "Subscription cancelled" if not at_period_end else "Subscription will cancel at end of period"
    }


@router.post("/renew")
async def renew_subscription(
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Renew a cancelled subscription (reactivate before it ends).
    """
    if user.subscription_tier == "free":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active subscription"
        )

    if not user.stripe_subscription_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No subscription ID found"
        )

    success = await stripe_service.renew_subscription(
        subscription_id=user.stripe_subscription_id
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to renew subscription"
        )

    return {
        "success": True,
        "message": "Subscription has been renewed and will continue after the current period"
    }


@router.get("/portal")
async def get_customer_portal(
    request: Request,
    user: AuthUser = Depends(current_active_user)
):
    """
    Get Stripe customer portal link for managing subscription.
    """
    if not user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Stripe customer found"
        )

    if not stripe_service.stripe:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stripe not configured"
        )

    # Use origin-based URL to preserve user's domain
    origin = request.headers.get('origin') or request.headers.get('referer', '').rstrip('/').split('?')[0].rsplit('/', 1)[0] or settings.get_app_base_url

    try:
        portal_session = stripe_service.stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=f"{origin}/billing"
        )

        return {"url": portal_session.url}
    except Exception as e:
        error_msg = str(e)
        # Check if it's a portal configuration error
        if "No configuration" in error_msg or "default configuration has not been created" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Stripe Customer Portal not configured. Please use Library > Subscriptions tab to manage your subscription, or contact support."
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create portal session: {error_msg}"
        )


# ============================================================================
# Credits Endpoints
# ============================================================================

@router.get("/credits", response_model=CreditBalanceResponse)
async def get_credits_balance(
    user: AuthUser = Depends(current_active_user)
):
    """
    Get user's current credit balance.
    """
    return CreditBalanceResponse(
        balance_cents=user.credits_balance,
        balance_usd=user.credits_balance / 100
    )


@router.post("/credits/purchase", response_model=CheckoutSessionResponse)
async def purchase_credits(
    request: CreditPurchaseRequest,
    http_request: Request,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a checkout session for purchasing credits.
    """
    # Determine amount based on package
    package_amounts = {
        "small": settings.credit_package_small,
        "medium": settings.credit_package_medium,
        "large": settings.credit_package_large
    }

    if request.package not in package_amounts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid package. Must be: small, medium, or large"
        )

    amount_cents = package_amounts[request.package]

    # Create checkout session with origin-based URLs to preserve user's domain
    origin = http_request.headers.get('origin') or http_request.headers.get('referer', '').rstrip('/').split('?')[0].rsplit('/', 1)[0] or settings.get_app_base_url
    success_url = f"{origin}/billing/credits/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/billing/credits/cancel"

    session = await stripe_service.create_credit_purchase_checkout(
        user=user,
        amount_cents=amount_cents,
        success_url=success_url,
        cancel_url=cancel_url,
        db=db
    )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create checkout session"
        )

    return CheckoutSessionResponse(
        session_id=session["id"],
        url=session["url"]
    )


@router.get("/credits/history")
async def get_credit_purchase_history(
    limit: int = 50,
    offset: int = 0,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
                "completed_at": p.completed_at.isoformat() if p.completed_at else None
            }
            for p in purchases
        ]
    }


# ============================================================================
# Usage Endpoints
# ============================================================================

@router.get("/usage", response_model=UsageSummaryResponse)
async def get_usage_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get usage summary for a date range.
    Defaults to current month if no dates provided.
    """
    # Parse dates
    if start_date:
        start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
    else:
        # Default to start of current month
        now = datetime.now(timezone.utc)
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    if end_date:
        end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
    else:
        # Default to now
        end = datetime.now(timezone.utc)

    # Get usage summary
    summary = await usage_service.get_user_usage_summary(
        user_id=user.id,
        start_date=start,
        end_date=end,
        db=db
    )

    return UsageSummaryResponse(**summary)


@router.post("/usage/sync")
async def sync_usage(
    start_date: Optional[str] = None,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually sync usage data from LiteLLM.
    """
    # Parse start date
    if start_date:
        start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
    else:
        # Default to 24 hours ago
        start = datetime.now(timezone.utc) - timedelta(days=1)

    # Sync usage
    usage_logs = await usage_service.sync_user_usage(
        user=user,
        start_date=start,
        db=db
    )

    return {
        "success": True,
        "logs_synced": len(usage_logs),
        "message": f"Synced {len(usage_logs)} usage entries"
    }


@router.get("/usage/logs")
async def get_usage_logs(
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed usage logs.
    """
    # Build query
    query = select(UsageLog).where(UsageLog.user_id == user.id)

    if start_date:
        start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        query = query.where(UsageLog.created_at >= start)

    if end_date:
        end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
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
                "created_at": log.created_at.isoformat()
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
    db: AsyncSession = Depends(get_db)
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
        all_transactions.append({
            "id": str(credit.id),
            "type": "credit_purchase",
            "amount_cents": credit.amount_cents,
            "amount_usd": credit.amount_cents / 100,
            "status": credit.status,
            "created_at": credit.created_at.isoformat()
        })

    for trans in transactions:
        all_transactions.append({
            "id": str(trans.id),
            "type": trans.transaction_type,
            "amount_cents": trans.amount_total,
            "amount_usd": trans.amount_total / 100,
            "status": "completed",
            "agent_id": str(trans.agent_id) if trans.agent_id else None,
            "created_at": trans.created_at.isoformat()
        })

    # Sort by created_at
    all_transactions.sort(key=lambda x: x["created_at"], reverse=True)

    return {"transactions": all_transactions[:limit]}


# ============================================================================
# Creator Earnings (for marketplace creators)
# ============================================================================

@router.get("/earnings")
async def get_creator_earnings(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get earnings from marketplace agents (for creators).
    """
    # Parse dates
    if start_date:
        start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
    else:
        # Default to start of current month
        now = datetime.now(timezone.utc)
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    if end_date:
        end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
    else:
        end = datetime.now(timezone.utc)

    # Get earnings
    earnings = await usage_service.get_creator_earnings(
        creator_id=user.id,
        start_date=start,
        end_date=end,
        db=db
    )

    return earnings


@router.post("/connect")
async def connect_stripe_account(
    request: Request,
    user: AuthUser = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create Stripe Connect onboarding link for receiving payouts.
    """
    # Use origin-based URLs to preserve user's domain
    origin = request.headers.get('origin') or request.headers.get('referer', '').rstrip('/').split('?')[0].rsplit('/', 1)[0] or settings.get_app_base_url
    refresh_url = f"{origin}/billing/connect/refresh"
    return_url = f"{origin}/billing/connect/complete"

    url = await stripe_service.create_connect_account_link(
        user=user,
        refresh_url=refresh_url,
        return_url=return_url,
        db=db
    )

    if not url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create Connect account link"
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
            "small": settings.credit_package_small,
            "medium": settings.credit_package_medium,
            "large": settings.credit_package_large
        },
        "premium_price": settings.premium_subscription_price,
        "deploy_price": settings.additional_deploy_price,
        "free_limits": {
            "max_projects": settings.free_max_projects,
            "max_deploys": settings.free_max_deploys
        },
        "premium_limits": {
            "max_projects": settings.premium_max_projects,
            "max_deploys": settings.premium_max_deploys
        }
    }
