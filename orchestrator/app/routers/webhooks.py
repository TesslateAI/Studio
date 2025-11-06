"""
Webhook handlers for external services (Stripe, etc.).
"""

from fastapi import APIRouter, Request, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from ..database import get_db
from ..services.stripe_service import stripe_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle Stripe webhook events.

    This endpoint receives and processes webhook events from Stripe,
    including payment confirmations, subscription updates, and more.
    """
    # Get the raw body and signature
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        logger.error("Missing Stripe signature header")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing stripe-signature header"
        )

    # Process the webhook
    result = await stripe_service.handle_webhook(
        payload=payload,
        sig_header=sig_header,
        db=db
    )

    if not result.get("success"):
        logger.error(f"Webhook processing failed: {result.get('message')}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("message", "Webhook processing failed")
        )

    return {"received": True, "message": result.get("message")}
