"""
Stripe payment processing service for marketplace, subscriptions, and billing.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models import (
    User,
    MarketplaceAgent,
    UserPurchasedAgent,
    CreditPurchase,
    MarketplaceTransaction,
    UsageLog
)
from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class StripeService:
    """
    Service for handling Stripe payments, subscriptions, and billing.
    """

    def __init__(self):
        """Initialize Stripe service."""
        self.stripe_key = settings.stripe_secret_key
        self.webhook_secret = settings.stripe_webhook_secret
        self.publishable_key = settings.stripe_publishable_key

        if self.stripe_key:
            try:
                import stripe
                stripe.api_key = self.stripe_key
                self.stripe = stripe
                logger.info("Stripe initialized successfully")
            except ImportError:
                logger.error("Stripe library not installed. Run: pip install stripe")
                self.stripe = None
        else:
            logger.warning("Stripe API key not configured. Payments will not work.")
            self.stripe = None

    # ========================================================================
    # Customer Management
    # ========================================================================

    async def create_customer(
        self,
        email: str,
        name: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a Stripe customer.

        Args:
            email: Customer email
            name: Customer name
            metadata: Additional metadata

        Returns:
            Stripe customer object or None if failed
        """
        if not self.stripe:
            logger.warning("Stripe not configured")
            return None

        try:
            customer = self.stripe.Customer.create(
                email=email,
                name=name,
                metadata=metadata or {}
            )
            logger.info(f"Created Stripe customer: {customer.id} for {email}")
            return customer
        except Exception as e:
            logger.error(f"Failed to create Stripe customer: {e}")
            raise

    async def get_or_create_customer(
        self,
        user: User,
        db: AsyncSession
    ) -> Optional[str]:
        """
        Get existing Stripe customer ID or create a new one.

        Args:
            user: User object
            db: Database session

        Returns:
            Stripe customer ID
        """
        if user.stripe_customer_id:
            return user.stripe_customer_id

        customer = await self.create_customer(
            email=user.email,
            name=user.name,
            metadata={"user_id": str(user.id)}
        )

        if customer:
            user.stripe_customer_id = customer["id"]
            await db.commit()
            return customer["id"]

        return None

    # ========================================================================
    # Subscription Management (Premium Tier)
    # ========================================================================

    async def create_subscription_checkout(
        self,
        user: User,
        success_url: str,
        cancel_url: str,
        db: AsyncSession
    ) -> Optional[Dict[str, Any]]:
        """
        Create a checkout session for premium subscription.

        Args:
            user: User subscribing
            success_url: Success redirect URL
            cancel_url: Cancel redirect URL
            db: Database session

        Returns:
            Checkout session with URL
        """
        if not self.stripe:
            logger.warning("Stripe not configured")
            return None

        try:
            # Get or create customer
            customer_id = await self.get_or_create_customer(user, db)

            if not customer_id:
                raise ValueError("Failed to create Stripe customer")

            # Create checkout session
            session = self.stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[{
                    "price": settings.stripe_premium_price_id,
                    "quantity": 1
                }],
                mode="subscription",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": str(user.id),
                    "type": "premium_subscription"
                }
            )

            logger.info(f"Created subscription checkout for user {user.id}")
            return session

        except Exception as e:
            logger.error(f"Failed to create subscription checkout: {e}")
            raise

    async def cancel_subscription(
        self,
        subscription_id: str,
        at_period_end: bool = False
    ) -> bool:
        """
        Cancel a Stripe subscription.

        Args:
            subscription_id: Stripe subscription ID
            at_period_end: If True, cancel at end of billing period

        Returns:
            True if successful
        """
        if not self.stripe:
            logger.warning("Stripe not configured")
            return False

        try:
            if at_period_end:
                self.stripe.Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=True
                )
            else:
                self.stripe.Subscription.delete(subscription_id)

            logger.info(f"Cancelled subscription: {subscription_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel subscription: {e}")
            return False

    async def renew_subscription(
        self,
        subscription_id: str
    ) -> bool:
        """
        Renew a cancelled subscription by removing the cancellation.

        Args:
            subscription_id: Stripe subscription ID

        Returns:
            True if successful
        """
        if not self.stripe:
            logger.warning("Stripe not configured")
            return False

        try:
            # Reactivate by setting cancel_at_period_end to False
            self.stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=False
            )
            logger.info(f"Renewed subscription: {subscription_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to renew subscription: {e}")
            return False

    # ========================================================================
    # Credit Purchases
    # ========================================================================

    async def create_credit_purchase_checkout(
        self,
        user: User,
        amount_cents: int,
        success_url: str,
        cancel_url: str,
        db: AsyncSession
    ) -> Optional[Dict[str, Any]]:
        """
        Create a checkout session for purchasing credits.

        Args:
            user: User purchasing credits
            amount_cents: Amount in cents ($5 = 500, $10 = 1000, $50 = 5000)
            success_url: Success redirect URL
            cancel_url: Cancel redirect URL
            db: Database session

        Returns:
            Checkout session with URL
        """
        if not self.stripe:
            logger.warning("Stripe not configured")
            return None

        try:
            # Get or create customer
            customer_id = await self.get_or_create_customer(user, db)

            if not customer_id:
                raise ValueError("Failed to create Stripe customer")

            # Create checkout session
            session = self.stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": f"${amount_cents / 100:.2f} Credits",
                            "description": f"Purchase ${amount_cents / 100:.2f} in credits for AI usage"
                        },
                        "unit_amount": amount_cents
                    },
                    "quantity": 1
                }],
                mode="payment",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": str(user.id),
                    "type": "credit_purchase",
                    "amount_cents": str(amount_cents)
                }
            )

            logger.info(f"Created credit purchase checkout for user {user.id}: ${amount_cents / 100}")
            return session

        except Exception as e:
            logger.error(f"Failed to create credit purchase checkout: {e}")
            raise

    # ========================================================================
    # Marketplace Agent Purchases
    # ========================================================================

    async def create_agent_purchase_checkout(
        self,
        user: User,
        agent: MarketplaceAgent,
        success_url: str,
        cancel_url: str,
        db: AsyncSession
    ) -> Optional[Dict[str, Any]]:
        """
        Create a checkout session for purchasing a marketplace agent.

        Args:
            user: User purchasing the agent
            agent: Agent being purchased
            success_url: Success redirect URL
            cancel_url: Cancel redirect URL
            db: Database session

        Returns:
            Checkout session with URL
        """
        if not self.stripe:
            logger.warning("Stripe not configured")
            return None

        try:
            # Get or create customer
            customer_id = await self.get_or_create_customer(user, db)

            if not customer_id:
                raise ValueError("Failed to create Stripe customer")

            # Determine mode and line items based on pricing type
            if agent.pricing_type == "monthly":
                # Monthly subscription
                mode = "subscription"
                if agent.stripe_price_id:
                    line_items = [{
                        "price": agent.stripe_price_id,
                        "quantity": 1
                    }]
                else:
                    line_items = [{
                        "price_data": {
                            "currency": "usd",
                            "product_data": {
                                "name": agent.name,
                                "description": agent.description,
                                "metadata": {"agent_id": str(agent.id)}
                            },
                            "unit_amount": agent.price,
                            "recurring": {"interval": "month"}
                        },
                        "quantity": 1
                    }]
            elif agent.pricing_type == "one_time":
                # One-time payment
                mode = "payment"
                line_items = [{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": agent.name,
                            "description": agent.description,
                            "metadata": {"agent_id": str(agent.id)}
                        },
                        "unit_amount": agent.price
                    },
                    "quantity": 1
                }]
            else:
                raise ValueError(f"Invalid pricing type: {agent.pricing_type}")

            # Create checkout session
            session = self.stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=line_items,
                mode=mode,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": str(user.id),
                    "agent_id": str(agent.id),
                    "type": "agent_purchase",
                    "pricing_type": agent.pricing_type
                }
            )

            logger.info(f"Created agent purchase checkout for user {user.id}, agent {agent.id}")
            return session

        except Exception as e:
            logger.error(f"Failed to create agent purchase checkout: {e}")
            raise

    # ========================================================================
    # Deploy Slot Purchases
    # ========================================================================

    async def create_deploy_purchase_checkout(
        self,
        user: User,
        success_url: str,
        cancel_url: str,
        db: AsyncSession
    ) -> Optional[Dict[str, Any]]:
        """
        Create a checkout session for purchasing an additional deploy slot.

        Args:
            user: User purchasing deploy slot
            success_url: Success redirect URL
            cancel_url: Cancel redirect URL
            db: Database session

        Returns:
            Checkout session with URL
        """
        if not self.stripe:
            logger.warning("Stripe not configured")
            return None

        try:
            # Get or create customer
            customer_id = await self.get_or_create_customer(user, db)

            if not customer_id:
                raise ValueError("Failed to create Stripe customer")

            price = settings.additional_deploy_price

            # Create checkout session
            session = self.stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": "Additional Deploy Slot",
                            "description": "Purchase an additional deploy slot for continuous deployment"
                        },
                        "unit_amount": price
                    },
                    "quantity": 1
                }],
                mode="payment",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": str(user.id),
                    "type": "deploy_purchase"
                }
            )

            logger.info(f"Created deploy purchase checkout for user {user.id}")
            return session

        except Exception as e:
            logger.error(f"Failed to create deploy purchase checkout: {e}")
            raise

    # ========================================================================
    # Usage Invoicing (for API-based agents)
    # ========================================================================

    async def create_usage_invoice(
        self,
        user: User,
        usage_logs: list[UsageLog],
        db: AsyncSession
    ) -> Optional[str]:
        """
        Create a Stripe invoice for monthly API usage.

        Args:
            user: User to invoice
            usage_logs: List of usage logs for the billing period
            db: Database session

        Returns:
            Invoice ID or None if failed
        """
        if not self.stripe:
            logger.warning("Stripe not configured")
            return None

        try:
            # Get or create customer
            customer_id = await self.get_or_create_customer(user, db)

            if not customer_id:
                raise ValueError("Failed to create Stripe customer")

            # Calculate total cost
            total_cost = sum(log.cost_total for log in usage_logs)

            if total_cost <= 0:
                logger.info(f"No charges for user {user.id} this month")
                return None

            # Deduct from credits balance first
            remaining_cost = total_cost
            if user.credits_balance >= total_cost:
                # Fully covered by credits
                user.credits_balance -= total_cost
                await db.commit()
                logger.info(f"Usage paid from credits for user {user.id}: ${total_cost / 100:.2f}")

                # Mark usage logs as paid
                for log in usage_logs:
                    log.billed_status = "paid"
                    log.billed_at = datetime.now(timezone.utc)
                await db.commit()
                return None
            elif user.credits_balance > 0:
                # Partially covered by credits
                remaining_cost = total_cost - user.credits_balance
                user.credits_balance = 0
                await db.commit()

            # Create invoice for remaining amount
            invoice_item = self.stripe.InvoiceItem.create(
                customer=customer_id,
                amount=remaining_cost,
                currency="usd",
                description=f"AI Usage - {datetime.now().strftime('%B %Y')}"
            )

            invoice = self.stripe.Invoice.create(
                customer=customer_id,
                auto_advance=True,  # Automatically finalize and charge
                metadata={
                    "user_id": str(user.id),
                    "type": "usage_invoice",
                    "period_start": usage_logs[0].created_at.isoformat(),
                    "period_end": usage_logs[-1].created_at.isoformat()
                }
            )

            # Finalize and pay the invoice
            invoice = self.stripe.Invoice.finalize_invoice(invoice.id)
            invoice = self.stripe.Invoice.pay(invoice.id)

            # Mark usage logs as invoiced
            for log in usage_logs:
                log.invoice_id = invoice.id
                log.billed_status = "invoiced"
                log.billed_at = datetime.now(timezone.utc)

            user.total_spend += remaining_cost
            await db.commit()

            logger.info(f"Created usage invoice {invoice.id} for user {user.id}: ${remaining_cost / 100:.2f}")
            return invoice.id

        except Exception as e:
            logger.error(f"Failed to create usage invoice: {e}")
            raise

    # ========================================================================
    # Stripe Connect (Creator Payouts)
    # ========================================================================

    async def create_connect_account_link(
        self,
        user: User,
        refresh_url: str,
        return_url: str,
        db: AsyncSession
    ) -> Optional[str]:
        """
        Create a Stripe Connect account link for creator onboarding.

        Args:
            user: Creator user
            refresh_url: URL to refresh if expired
            return_url: URL to return to after onboarding
            db: Database session

        Returns:
            Onboarding URL
        """
        if not self.stripe:
            logger.warning("Stripe not configured")
            return None

        try:
            # Create or get existing account
            if not user.creator_stripe_account_id:
                account = self.stripe.Account.create(
                    type="express",
                    email=user.email,
                    metadata={"user_id": str(user.id)}
                )
                user.creator_stripe_account_id = account.id
                await db.commit()
            else:
                account = {"id": user.creator_stripe_account_id}

            # Create account link
            account_link = self.stripe.AccountLink.create(
                account=account["id"],
                refresh_url=refresh_url,
                return_url=return_url,
                type="account_onboarding"
            )

            logger.info(f"Created Connect account link for user {user.id}")
            return account_link.url

        except Exception as e:
            logger.error(f"Failed to create Connect account link: {e}")
            raise

    async def create_payout(
        self,
        transaction: MarketplaceTransaction,
        db: AsyncSession
    ) -> bool:
        """
        Create a payout to agent creator via Stripe Connect.

        Args:
            transaction: Transaction to pay out
            db: Database session

        Returns:
            True if successful
        """
        if not self.stripe:
            logger.warning("Stripe not configured")
            return False

        try:
            # Get creator's Connect account
            creator_result = await db.execute(
                select(User).where(User.id == transaction.creator_id)
            )
            creator = creator_result.scalar_one_or_none()

            if not creator or not creator.creator_stripe_account_id:
                logger.error(f"Creator {transaction.creator_id} has no Connect account")
                return False

            # Create transfer to connected account
            transfer = self.stripe.Transfer.create(
                amount=transaction.amount_creator,
                currency="usd",
                destination=creator.creator_stripe_account_id,
                metadata={
                    "transaction_id": str(transaction.id),
                    "agent_id": str(transaction.agent_id),
                    "user_id": str(transaction.user_id)
                }
            )

            # Update transaction
            transaction.payout_status = "paid"
            transaction.payout_date = datetime.now(timezone.utc)
            transaction.stripe_payout_id = transfer.id
            await db.commit()

            logger.info(f"Created payout {transfer.id} for transaction {transaction.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to create payout: {e}")
            return False

    # ========================================================================
    # Webhook Handling
    # ========================================================================

    async def handle_webhook(
        self,
        payload: bytes,
        sig_header: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
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
            event_type = event["type"]
            event_data = event["data"]["object"]

            if event_type == "checkout.session.completed":
                await self._handle_checkout_completed(event_data, db)
            elif event_type == "customer.subscription.created":
                await self._handle_subscription_created(event_data, db)
            elif event_type == "customer.subscription.updated":
                await self._handle_subscription_updated(event_data, db)
            elif event_type == "customer.subscription.deleted":
                await self._handle_subscription_deleted(event_data, db)
            elif event_type == "invoice.payment_succeeded":
                await self._handle_invoice_payment_succeeded(event_data, db)
            elif event_type == "invoice.payment_failed":
                await self._handle_invoice_payment_failed(event_data, db)
            elif event_type == "payment_intent.succeeded":
                await self._handle_payment_intent_succeeded(event_data, db)
            else:
                logger.info(f"Unhandled webhook event type: {event_type}")

            return {"success": True, "message": f"Handled {event_type}"}

        except Exception as e:
            logger.error(f"Webhook processing failed: {e}")
            return {"success": False, "message": str(e)}

    async def _handle_checkout_completed(self, session: Dict[str, Any], db: AsyncSession):
        """Handle successful checkout completion."""
        metadata = session.get("metadata", {})
        checkout_type = metadata.get("type")

        if checkout_type == "premium_subscription":
            await self._handle_premium_subscription_checkout(session, db)
        elif checkout_type == "credit_purchase":
            await self._handle_credit_purchase_checkout(session, db)
        elif checkout_type == "agent_purchase":
            await self._handle_agent_purchase_checkout(session, db)
        elif checkout_type == "deploy_purchase":
            await self._handle_deploy_purchase_checkout(session, db)
        else:
            logger.warning(f"Unknown checkout type: {checkout_type}")

    async def _handle_premium_subscription_checkout(self, session: Dict[str, Any], db: AsyncSession):
        """Handle premium subscription checkout completion."""
        user_id = UUID(session["metadata"]["user_id"])
        subscription_id = session.get("subscription")

        # Update user to premium tier
        user_result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one()
        user.subscription_tier = "pro"
        user.stripe_subscription_id = subscription_id
        await db.commit()

        logger.info(f"User {user_id} upgraded to premium")

    async def _handle_credit_purchase_checkout(self, session: Dict[str, Any], db: AsyncSession):
        """Handle credit purchase checkout completion."""
        user_id = UUID(session["metadata"]["user_id"])
        amount_cents = int(session["metadata"]["amount_cents"])
        payment_intent = session.get("payment_intent")

        # Check if already processed (idempotency)
        existing = await db.execute(
            select(CreditPurchase).where(CreditPurchase.stripe_payment_intent == payment_intent)
        )
        if existing.scalar_one_or_none():
            logger.info(f"Credit purchase already processed: {payment_intent}")
            return

        # Create credit purchase record
        purchase = CreditPurchase(
            user_id=user_id,
            amount_cents=amount_cents,
            credits_amount=amount_cents,  # 1:1 ratio
            stripe_payment_intent=payment_intent,
            stripe_checkout_session=session["id"],
            status="completed",
            completed_at=datetime.now(timezone.utc)
        )
        db.add(purchase)

        # Update user credits balance
        user_result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one()
        user.credits_balance += amount_cents
        user.total_spend += amount_cents

        await db.commit()
        logger.info(f"User {user_id} purchased ${amount_cents / 100} in credits")

    async def _handle_agent_purchase_checkout(self, session: Dict[str, Any], db: AsyncSession):
        """Handle agent purchase checkout completion."""
        user_id = UUID(session["metadata"]["user_id"])
        agent_id = UUID(session["metadata"]["agent_id"])
        pricing_type = session["metadata"]["pricing_type"]
        payment_intent = session.get("payment_intent")
        subscription_id = session.get("subscription")

        # Check if already processed
        existing = await db.execute(
            select(UserPurchasedAgent).where(
                UserPurchasedAgent.user_id == user_id,
                UserPurchasedAgent.agent_id == agent_id
            )
        )
        if existing.scalar_one_or_none():
            logger.info(f"Agent purchase already processed: user {user_id}, agent {agent_id}")
            return

        # Create purchase record
        purchase = UserPurchasedAgent(
            user_id=user_id,
            agent_id=agent_id,
            purchase_type="subscription" if pricing_type == "monthly" else "purchased",
            stripe_payment_intent=payment_intent,
            stripe_subscription_id=subscription_id,
            is_active=True
        )
        db.add(purchase)

        # Update agent stats
        agent_result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
        )
        agent = agent_result.scalar_one()
        agent.downloads += 1

        # Create transaction for revenue sharing
        amount_total = session["amount_total"]
        amount_creator = int(amount_total * settings.creator_revenue_share)
        amount_platform = amount_total - amount_creator

        transaction = MarketplaceTransaction(
            user_id=user_id,
            agent_id=agent_id,
            creator_id=agent.created_by_user_id,
            transaction_type="subscription" if pricing_type == "monthly" else "one_time",
            amount_total=amount_total,
            amount_creator=amount_creator,
            amount_platform=amount_platform,
            stripe_payment_intent=payment_intent,
            stripe_subscription_id=subscription_id
        )
        db.add(transaction)

        # Update user total spend
        user_result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one()
        user.total_spend += amount_total

        await db.commit()
        logger.info(f"User {user_id} purchased agent {agent_id}")

        # Schedule payout to creator (if applicable)
        if agent.created_by_user_id:
            await self.create_payout(transaction, db)

    async def _handle_deploy_purchase_checkout(self, session: Dict[str, Any], db: AsyncSession):
        """Handle deploy slot purchase checkout completion."""
        user_id = UUID(session["metadata"]["user_id"])

        # Update user deployed projects count limit
        user_result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one()

        # This doesn't increase current count, just allows one more deploy
        # The actual count is managed when projects are deployed
        # We track this purchase via total_spend
        user.total_spend += session["amount_total"]

        await db.commit()
        logger.info(f"User {user_id} purchased additional deploy slot")

    async def _handle_subscription_created(self, subscription: Dict[str, Any], db: AsyncSession):
        """Handle new subscription creation."""
        logger.info(f"Subscription created: {subscription['id']}")

    async def _handle_subscription_updated(self, subscription: Dict[str, Any], db: AsyncSession):
        """Handle subscription update."""
        logger.info(f"Subscription updated: {subscription['id']}")

    async def _handle_subscription_deleted(self, subscription: Dict[str, Any], db: AsyncSession):
        """Handle subscription cancellation."""
        subscription_id = subscription["id"]

        # Check if it's a premium subscription
        user_result = await db.execute(
            select(User).where(User.stripe_subscription_id == subscription_id)
        )
        user = user_result.scalar_one_or_none()

        if user:
            # Downgrade to free tier
            user.subscription_tier = "free"
            user.stripe_subscription_id = None
            await db.commit()
            logger.info(f"User {user.id} downgraded to free tier")
            return

        # Check if it's an agent subscription
        purchase_result = await db.execute(
            select(UserPurchasedAgent).where(
                UserPurchasedAgent.stripe_subscription_id == subscription_id
            )
        )
        purchase = purchase_result.scalar_one_or_none()

        if purchase:
            purchase.is_active = False
            purchase.expires_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(f"Agent subscription cancelled: {subscription_id}")

    async def _handle_invoice_payment_succeeded(self, invoice: Dict[str, Any], db: AsyncSession):
        """Handle successful invoice payment."""
        logger.info(f"Invoice payment succeeded: {invoice['id']}")

        metadata = invoice.get("metadata", {})
        if metadata.get("type") == "usage_invoice":
            # Mark usage logs as paid
            user_id = UUID(metadata["user_id"])
            usage_result = await db.execute(
                select(UsageLog).where(
                    UsageLog.user_id == user_id,
                    UsageLog.invoice_id == invoice["id"]
                )
            )
            usage_logs = usage_result.scalars().all()

            for log in usage_logs:
                log.billed_status = "paid"

            await db.commit()
            logger.info(f"Marked {len(usage_logs)} usage logs as paid")

    async def _handle_invoice_payment_failed(self, invoice: Dict[str, Any], db: AsyncSession):
        """Handle failed invoice payment."""
        logger.error(f"Invoice payment failed: {invoice['id']}")
        # TODO: Notify user, possibly suspend service

    async def _handle_payment_intent_succeeded(self, payment_intent: Dict[str, Any], db: AsyncSession):
        """Handle successful one-time payment."""
        logger.info(f"Payment intent succeeded: {payment_intent['id']}")


# Singleton instance
stripe_service = StripeService()
