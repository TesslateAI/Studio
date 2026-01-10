# Stripe Service - Payment Processing & Subscriptions

**File**: `orchestrator/app/services/stripe_service.py` (970 lines)

Handles all payment processing through Stripe for subscriptions, marketplace purchases, and credit top-ups.

## Overview

The Stripe Service manages:
- **Customer Management**: Create/retrieve Stripe customers
- **Subscriptions**: Premium tier monthly billing
- **One-Time Payments**: Credits, deploy slots, marketplace agents
- **Webhooks**: Handle payment events
- **Billing**: Generate invoices for usage

## Configuration

```bash
# .env
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PREMIUM_PRICE_ID=price_1234...  # Monthly subscription
ADDITIONAL_DEPLOY_PRICE=500  # $5.00 in cents
```

## Core Operations

### 1. Customer Management

```python
from services.stripe_service import StripeService

stripe = StripeService()

# Get or create customer
customer_id = await stripe.get_or_create_customer(user, db)
# Auto-creates if user.stripe_customer_id is None
```

### 2. Premium Subscription

```python
# Create checkout session
session = await stripe.create_subscription_checkout(
    user=user,
    success_url="https://app.tesslate.com/success",
    cancel_url="https://app.tesslate.com/pricing",
    db=db
)

# Redirect user to Stripe Checkout
return {"checkout_url": session.url}

# After payment, webhook handles:
# - Update user.subscription_tier = "premium"
# - Set user.subscription_id
# - Record subscription start date
```

### 3. Credit Purchase

```python
# Create checkout for $10 credits
session = await stripe.create_credit_purchase_checkout(
    user=user,
    amount_cents=1000,  # $10.00
    success_url="https://app.tesslate.com/dashboard",
    cancel_url="https://app.tesslate.com/credits",
    db=db
)

# After payment, webhook handles:
# - Add $10 to user.ai_credits
# - Create CreditPurchase record
# - Send receipt email
```

### 4. Marketplace Agent Purchase

```python
# Purchase marketplace agent (one-time or subscription)
session = await stripe.create_agent_purchase_checkout(
    user=user,
    agent=marketplace_agent,  # MarketplaceAgent model
    success_url="https://app.tesslate.com/marketplace/success",
    cancel_url=f"https://app.tesslate.com/marketplace/agents/{agent.id}",
    db=db
)

# Handles both:
# - One-time: Creates payment, grants immediate access
# - Monthly: Creates subscription, access while active
```

### 5. Deploy Slot Purchase

```python
# Purchase additional deployment slot
session = await stripe.create_deploy_purchase_checkout(
    user=user,
    success_url="https://app.tesslate.com/deployments",
    cancel_url="https://app.tesslate.com/billing",
    db=db
)

# After payment:
# - Increment user.deploy_slots
# - Allow deploying more projects
```

## Subscription Management

### Cancel Subscription

```python
success = await stripe.cancel_subscription(
    subscription_id=user.subscription_id,
    at_period_end=True  # Cancel at end of billing cycle
)

# User retains premium until period ends
```

### Renew Subscription

```python
success = await stripe.renew_subscription(
    subscription_id=user.subscription_id
)

# Removes cancellation, subscription continues
```

## Webhook Handling

```python
# routers/billing.py
@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: AsyncSession):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle event types
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        metadata = session['metadata']

        if metadata['type'] == 'premium_subscription':
            # Activate premium subscription
            user = await get_user_by_id(metadata['user_id'], db)
            user.subscription_tier = "premium"
            user.subscription_id = session['subscription']
            await db.commit()

        elif metadata['type'] == 'credit_purchase':
            # Add credits
            user = await get_user_by_id(metadata['user_id'], db)
            amount = float(metadata['amount_cents']) / 100
            user.ai_credits += amount
            await db.commit()

    elif event['type'] == 'customer.subscription.deleted':
        # Downgrade to free tier
        subscription = event['data']['object']
        user = await get_user_by_subscription_id(subscription['id'], db)
        user.subscription_tier = "free"
        user.subscription_id = None
        await db.commit()

    return {"status": "success"}
```

## Pricing Models

### Subscription Tiers

```python
# Premium Subscription: $20/month
# - Unlimited AI usage
# - 5 deploy slots
# - Priority support
```

### One-Time Purchases

```python
# Credits: $5, $10, $25, $50
# Deploy Slots: $5 per additional slot
# Marketplace Agents: $0-$99 (set by creator)
```

## Testing

### Test Cards (Stripe Test Mode)

```
Success: 4242 4242 4242 4242
Decline: 4000 0000 0000 0002
Requires Auth: 4000 0025 0000 3155
```

### Webhook Testing

```bash
# Use Stripe CLI
stripe listen --forward-to localhost:8000/api/billing/webhooks/stripe

# Trigger event
stripe trigger checkout.session.completed
```

## Error Handling

```python
try:
    session = await stripe.create_subscription_checkout(...)
except stripe.error.CardError as e:
    # Card declined
    return {"error": "Payment failed"}
except stripe.error.InvalidRequestError as e:
    # Invalid parameters
    logger.error(f"Stripe API error: {e}")
    return {"error": "Invalid request"}
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    return {"error": "Payment processing failed"}
```

## Security

1. **Webhook Signature Verification**: Always verify `stripe-signature` header
2. **Customer Isolation**: Each user has separate Stripe customer
3. **Idempotency**: Use `idempotency_key` for safe retries
4. **PCI Compliance**: Never store card details (Stripe handles)
5. **Test Mode**: Use test keys for development

## Troubleshooting

**Problem**: Webhook not received
- Check webhook endpoint is publicly accessible
- Verify `STRIPE_WEBHOOK_SECRET` matches Stripe dashboard
- Check Stripe dashboard for delivery failures

**Problem**: Payment succeeded but user not upgraded
- Check webhook logs
- Verify `metadata.user_id` is correct
- Manually update user if needed

**Problem**: "No such price" error
- Verify `STRIPE_PREMIUM_PRICE_ID` is correct
- Price must exist in your Stripe account
- Check test vs live mode mismatch

## Related Documentation

- [litellm.md](./litellm.md) - AI credits use LiteLLM budget
- [usage_service.md](./usage-service.md) - Track usage for invoicing
- [../routers/billing.md](../routers/billing.md) - Billing API endpoints
