"""
Stripe payment processing service for marketplace.
"""

import logging
from typing import Optional
from datetime import datetime, timezone
import os

from sqlalchemy.ext.asyncio import AsyncSession
from ..models import User, MarketplaceAgent
from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Note: Stripe will be configured when you add your Stripe keys to .env
# For now, this is a placeholder implementation

class StripeService:
    """
    Service for handling Stripe payments and subscriptions.
    """

    def __init__(self):
        """Initialize Stripe service."""
        self.stripe_key = os.getenv("STRIPE_SECRET_KEY", "")
        self.webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

        if self.stripe_key:
            try:
                import stripe
                stripe.api_key = self.stripe_key
                self.stripe = stripe
                logger.info("Stripe initialized successfully")
            except ImportError:
                logger.warning("Stripe library not installed. Run: pip install stripe")
                self.stripe = None
        else:
            logger.warning("Stripe API key not configured. Payments will not work.")
            self.stripe = None

    async def create_checkout_session(
        self,
        user: User,
        agent: MarketplaceAgent,
        success_url: str,
        cancel_url: str,
        db: AsyncSession
    ) -> dict:
        """
        Create a Stripe checkout session for purchasing an agent.

        Args:
            user: User making the purchase
            agent: Agent being purchased
            success_url: URL to redirect to on successful payment
            cancel_url: URL to redirect to if payment is cancelled
            db: Database session

        Returns:
            Checkout session object with URL for redirect
        """

        if not self.stripe:
            # Return a mock session for development
            logger.warning("Stripe not configured. Returning mock checkout session.")
            return {
                "id": "mock_session_123",
                "url": f"{success_url}?session_id=mock_session_123",
                "status": "open"
            }

        try:
            # Get or create Stripe customer
            if not user.stripe_customer_id:
                customer = self.stripe.Customer.create(
                    email=user.email,
                    metadata={"user_id": str(user.id)}
                )
                user.stripe_customer_id = customer.id
                await db.commit()
            else:
                customer = {"id": user.stripe_customer_id}

            # Create line items based on pricing type
            if agent.pricing_type == "monthly":
                # For subscriptions, we need a price ID from Stripe
                if agent.stripe_price_id:
                    line_items = [{
                        "price": agent.stripe_price_id,
                        "quantity": 1
                    }]
                    mode = "subscription"
                else:
                    # Create price data on the fly
                    line_items = [{
                        "price_data": {
                            "currency": "usd",
                            "product_data": {
                                "name": agent.name,
                                "description": agent.description,
                                "metadata": {"agent_id": str(agent.id)}
                            },
                            "unit_amount": agent.price,  # Already in cents
                            "recurring": {"interval": "month"}
                        },
                        "quantity": 1
                    }]
                    mode = "subscription"
            else:
                # One-time payment
                line_items = [{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": agent.name,
                            "description": agent.description,
                            "metadata": {"agent_id": str(agent.id)}
                        },
                        "unit_amount": agent.price  # Already in cents
                    },
                    "quantity": 1
                }]
                mode = "payment"

            # Create checkout session
            session = self.stripe.checkout.Session.create(
                customer=customer["id"],
                payment_method_types=["card"],
                line_items=line_items,
                mode=mode,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": str(user.id),
                    "agent_id": str(agent.id)
                }
            )

            return session

        except Exception as e:
            logger.error(f"Failed to create Stripe checkout session: {e}")
            raise

    async def handle_webhook(self, payload: bytes, sig_header: str, db: AsyncSession) -> dict:
        """
        Handle Stripe webhook events.

        Args:
            payload: Raw webhook payload
            sig_header: Stripe signature header
            db: Database session

        Returns:
            Response indicating success/failure
        """

        if not self.stripe or not self.webhook_secret:
            logger.warning("Stripe webhook not configured")
            return {"success": False, "message": "Webhook not configured"}

        try:
            # Verify webhook signature
            event = self.stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )

            # Handle different event types
            if event.type == "checkout.session.completed":
                await self._handle_checkout_completed(event.data.object, db)
            elif event.type == "customer.subscription.created":
                await self._handle_subscription_created(event.data.object, db)
            elif event.type == "customer.subscription.deleted":
                await self._handle_subscription_cancelled(event.data.object, db)
            elif event.type == "invoice.payment_succeeded":
                await self._handle_payment_succeeded(event.data.object, db)
            else:
                logger.info(f"Unhandled webhook event type: {event.type}")

            return {"success": True, "message": f"Handled {event.type}"}

        except Exception as e:
            logger.error(f"Webhook processing failed: {e}")
            return {"success": False, "message": str(e)}

    async def _handle_checkout_completed(self, session: dict, db: AsyncSession):
        """Handle successful checkout completion."""
        from ..models import UserPurchasedAgent
        from sqlalchemy import select

        from uuid import UUID
        user_id = UUID(session["metadata"]["user_id"])
        agent_id = UUID(session["metadata"]["agent_id"])

        # Create purchase record
        purchase = UserPurchasedAgent(
            user_id=user_id,
            agent_id=agent_id,
            purchase_type="subscription" if session["mode"] == "subscription" else "purchased",
            stripe_payment_intent=session.get("payment_intent"),
            stripe_subscription_id=session.get("subscription"),
            is_active=True
        )
        db.add(purchase)

        # Update agent download count
        agent_result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
        )
        agent = agent_result.scalar_one()
        agent.downloads += 1

        await db.commit()
        logger.info(f"Purchase completed: User {user_id} purchased agent {agent_id}")

    async def _handle_subscription_created(self, subscription: dict, db: AsyncSession):
        """Handle new subscription creation."""
        logger.info(f"Subscription created: {subscription['id']}")

    async def _handle_subscription_cancelled(self, subscription: dict, db: AsyncSession):
        """Handle subscription cancellation."""
        from ..models import UserPurchasedAgent
        from sqlalchemy import select

        # Find and deactivate the purchase
        result = await db.execute(
            select(UserPurchasedAgent).where(
                UserPurchasedAgent.stripe_subscription_id == subscription["id"]
            )
        )
        purchase = result.scalar_one_or_none()

        if purchase:
            purchase.is_active = False
            purchase.expires_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(f"Subscription cancelled: {subscription['id']}")

    async def _handle_payment_succeeded(self, invoice: dict, db: AsyncSession):
        """Handle successful payment (for recurring subscriptions)."""
        logger.info(f"Payment succeeded for invoice: {invoice['id']}")

    async def cancel_subscription(self, subscription_id: str) -> bool:
        """
        Cancel a Stripe subscription.

        Args:
            subscription_id: Stripe subscription ID

        Returns:
            True if cancellation successful
        """

        if not self.stripe:
            logger.warning("Stripe not configured")
            return False

        try:
            self.stripe.Subscription.delete(subscription_id)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel subscription: {e}")
            return False