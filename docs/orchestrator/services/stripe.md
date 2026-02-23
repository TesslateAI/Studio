# Stripe Service - Payment Processing & Subscriptions

**File**: `orchestrator/app/services/stripe_service.py` (~1,080 lines)

Handles all payment processing through Stripe for subscriptions, credit purchases, marketplace agent sales, deploy slot purchases, and creator payouts.

## Overview

The Stripe Service manages:
- **Customer Management**: Create/retrieve Stripe customers
- **Subscriptions**: 4-tier system (free/basic/pro/ultra) with monthly and annual billing
- **Credit Purchases**: 4 package tiers (small/medium/large/team) as one-time payments
- **Agent Purchases**: One-time and monthly marketplace agent sales with revenue sharing
- **Deploy Slot Purchases**: Additional deployment capacity
- **Webhook Handling**: Unified fulfillment with idempotency via `stripe_payment_intent` lookup
- **Usage Invoicing**: Multi-source credit deduction (daily > bundled > signup_bonus > purchased)
- **Creator Payouts**: Stripe Connect transfers with 90/10 revenue split

## Configuration

```bash
# .env
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_CONNECT_CLIENT_ID=ca_...

# Tier-specific Stripe Price IDs (monthly)
STRIPE_BASIC_PRICE_ID=price_...   # $20/month
STRIPE_PRO_PRICE_ID=price_...     # $49/month
STRIPE_ULTRA_PRICE_ID=price_...   # $149/month

# Tier-specific Stripe Price IDs (annual)
STRIPE_BASIC_ANNUAL_PRICE_ID=price_...
STRIPE_PRO_ANNUAL_PRICE_ID=price_...
STRIPE_ULTRA_ANNUAL_PRICE_ID=price_...

# Deploy pricing
ADDITIONAL_DEPLOY_PRICE=1000  # $10.00 in cents
```

## Subscription Tiers

| Tier | Price | Bundled Credits | Daily Credits | Max Projects | Max Deploys | BYOK | Support |
|------|-------|-----------------|---------------|--------------|-------------|------|---------|
| Free | $0 | 0 | 5/day | 3 | 1 | No | Community |
| Basic | $20/mo | 500 | 0 | 7 | 3 | No | Email |
| Pro | $49/mo | 2,000 | 0 | 15 | 5 | Yes | Priority |
| Ultra | $149/mo | 8,000 | 0 | 40 | 20 | Yes | Priority |

All paid tiers also support annual billing via separate Stripe Price IDs. BYOK (Bring Your Own Key) tiers are configured via `BYOK_ENABLED_TIERS` and default to `basic,pro,ultra`.

### Signup Bonus

New users receive **15,000 bonus credits** that expire after **60 days**. These are tracked separately in `user.signup_bonus_credits` and `user.signup_bonus_expires_at`.

## Credit System

Credits are the unified currency for AI usage. 1 credit = $0.01. Credits come from four sources, deducted in this priority order:

1. **Daily credits** (free tier only, 5/day, expire at end of day)
2. **Bundled credits** (monthly allowance from subscription tier, reset every 30 days)
3. **Signup bonus credits** (one-time new user bonus, expire after 60 days)
4. **Purchased credits** (bought via credit packages, never expire)

### Credit Packages

| Package | Credits | Price |
|---------|---------|-------|
| small | 500 | $5 |
| medium | 2,500 | $25 |
| large | 10,000 | $100 |
| team | 50,000 | $500 |

Credit-to-cents ratio is 1:1 (1 credit = 1 cent). Package amounts are defined in `config.py` via `credit_package_small`, `credit_package_medium`, `credit_package_large`, `credit_package_team`.

## Core Operations

### 1. Customer Management

```python
from services.stripe_service import stripe_service

# Get or create customer (auto-creates if user.stripe_customer_id is None)
customer_id = await stripe_service.get_or_create_customer(user, db)
```

### 2. Subscription Checkout

```python
# Create checkout session for a tier (basic, pro, or ultra)
session = await stripe_service.create_subscription_checkout(
    user=user,
    success_url="https://app.tesslate.com/settings/billing?success=true",
    cancel_url="https://app.tesslate.com/settings/billing?cancelled=true",
    db=db,
    tier="pro",                    # basic, pro, or ultra
    billing_interval="monthly",    # monthly or annual
)

# Redirect user to Stripe Checkout
return {"checkout_url": session["url"]}

# After payment, fulfillment handles:
# - Update user.subscription_tier to requested tier
# - Set user.stripe_subscription_id
# - Set user.support_tier based on tier
# - Grant bundled_credits for the tier
# - Set user.credits_reset_date to 30 days from now
```

Tier price IDs are resolved via `settings.get_stripe_price_id(tier)` for monthly or `settings.get_stripe_annual_price_id(tier)` for annual billing.

### 3. Credit Purchase

```python
# Create checkout for a credit package
session = await stripe_service.create_credit_purchase_checkout(
    user=user,
    amount_cents=2500,  # $25 = 2,500 credits (medium package)
    success_url="https://app.tesslate.com/settings/billing?success=true",
    cancel_url="https://app.tesslate.com/settings/billing?cancelled=true",
    db=db,
)

# After payment, fulfillment handles:
# - Cross-validate Stripe amount_total against metadata amount_cents
# - Add credits to user.purchased_credits (not bundled)
# - Create CreditPurchase record with stripe_payment_intent for idempotency
# - Update user.total_spend
```

### 4. Marketplace Agent Purchase

```python
# Purchase marketplace agent (one-time or monthly subscription)
session = await stripe_service.create_agent_purchase_checkout(
    user=user,
    agent=marketplace_agent,  # MarketplaceAgent model
    success_url="https://app.tesslate.com/marketplace/success",
    cancel_url=f"https://app.tesslate.com/marketplace/agents/{agent.id}",
    db=db,
)

# Handles both pricing_type == "one_time" and "monthly":
# - one_time: mode="payment", creates UserPurchasedAgent record
# - monthly: mode="subscription", creates subscription + UserPurchasedAgent
# - Creates MarketplaceTransaction with 90/10 revenue split
# - Increments agent.downloads
# - Schedules creator payout via Stripe Connect
```

### 5. Deploy Slot Purchase

```python
session = await stripe_service.create_deploy_purchase_checkout(
    user=user,
    success_url="https://app.tesslate.com/deployments",
    cancel_url="https://app.tesslate.com/billing",
    db=db,
)

# After payment:
# - Updates user.total_spend
# - Price: $10 per additional slot (configurable via ADDITIONAL_DEPLOY_PRICE)
```

## Unified Fulfillment

Subscription and credit fulfillment use a **dual-path idempotent pattern**: both the Stripe webhook and the frontend's `verify-checkout` endpoint call the same fulfillment methods. Whichever fires first wins; the other is a safe no-op.

### fulfill_subscription(session, db)

```python
result = await stripe_service.fulfill_subscription(session, db)
# Returns: {"tier": "pro", "already_fulfilled": bool}
```

- Validates tier is one of `["basic", "pro", "ultra"]`
- Idempotency: checks if `user.stripe_subscription_id` already matches the session's subscription
- Sets `user.subscription_tier`, `user.stripe_subscription_id`, `user.support_tier`
- Grants tier-appropriate `bundled_credits` and sets `credits_reset_date`

### fulfill_credit_purchase(session, db)

```python
result = await stripe_service.fulfill_credit_purchase(session, db)
# Returns: {"credits_added": N, "already_fulfilled": bool}
```

- Cross-validates `session.amount_total` against `metadata.amount_cents` (blocks on mismatch)
- Idempotency: looks up `CreditPurchase` by `stripe_payment_intent`
- Adds credits to `user.purchased_credits` (permanent, never expire)
- Handles race conditions via `IntegrityError` catch on commit

## Subscription Management

### Cancel Subscription

```python
success = await stripe_service.cancel_subscription(
    subscription_id=user.stripe_subscription_id,
    at_period_end=True  # Cancel at end of billing cycle
)

# User retains tier benefits until period ends
```

### Renew Subscription

```python
success = await stripe_service.renew_subscription(
    subscription_id=user.stripe_subscription_id
)

# Removes cancellation, subscription continues
```

## Webhook Handling

```
POST /api/billing/webhooks/stripe
```

The `handle_webhook` method processes Stripe events with three-tier error handling:

1. **`SignatureVerificationError`** -- returns 400 (invalid signature)
2. **`IntegrityError`** -- returns 200 (already processed, idempotent success)
3. **Generic `Exception`** -- returns 500 (logged for investigation)

### Handled Event Types

| Event | Handler | Action |
|-------|---------|--------|
| `checkout.session.completed` | `_handle_checkout_completed` | Routes to type-specific handler based on `metadata.type` |
| `customer.subscription.created` | `_handle_subscription_created` | Logged |
| `customer.subscription.updated` | `_handle_subscription_updated` | Logged |
| `customer.subscription.deleted` | `_handle_subscription_deleted` | Downgrades user to free or deactivates agent subscription |
| `invoice.payment_succeeded` | `_handle_invoice_payment_succeeded` | Marks usage logs as paid |
| `invoice.payment_failed` | `_handle_invoice_payment_failed` | Logged (TODO: user notification) |
| `payment_intent.succeeded` | `_handle_payment_intent_succeeded` | Logged |

### Checkout Session Types (metadata.type)

| Type | Handler | Description |
|------|---------|-------------|
| `subscription` | `_handle_subscription_checkout` | Tier upgrade via `fulfill_subscription` |
| `premium_subscription` | `_handle_subscription_checkout` | Legacy alias, same handler |
| `credit_purchase` | `_handle_credit_purchase_checkout` | Credit fulfillment via `fulfill_credit_purchase` |
| `agent_purchase` | `_handle_agent_purchase_checkout` | Agent access grant + revenue split + creator payout |
| `deploy_purchase` | `_handle_deploy_purchase_checkout` | Deploy slot purchase |

### Subscription Deletion Flow

When `customer.subscription.deleted` fires:

1. Check if it is a **platform subscription** (basic/pro/ultra) by looking up `User.stripe_subscription_id`
   - Downgrade to free tier
   - Reset `bundled_credits` to free tier amount (0)
   - Purchased credits are NOT affected (they never expire)
2. Check if it is an **agent subscription** by looking up `UserPurchasedAgent.stripe_subscription_id`
   - Deactivate agent access (`is_active = False`)

## Usage Invoicing

The `create_usage_invoice` method handles monthly AI usage billing with credit deduction:

1. Calculate total cost from `UsageLog` entries
2. Attempt to cover cost from credits in priority order: daily > bundled > signup_bonus > purchased
3. If credits cover the full amount, deduct and mark logs as paid (no Stripe charge)
4. If partially covered, use all available credits and charge the remainder
5. If no credits, charge full amount via Stripe invoice

## Stripe Connect (Creator Payouts)

Marketplace agent creators receive payouts via Stripe Connect Express accounts:

```python
# Onboard creator
url = await stripe_service.create_connect_account_link(
    user=creator, refresh_url="...", return_url="...", db=db
)

# Payout after agent sale (90% to creator, 10% to platform)
success = await stripe_service.create_payout(transaction, db)
```

Revenue split is configured via `creator_revenue_share` (default 0.90) and `platform_revenue_share` (default 0.10) in `config.py`.

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

### Verify Checkout (Development)

The frontend calls `POST /api/billing/verify-checkout` with `{session_id}` after redirect from Stripe. This handles cases where webhooks have not fired yet (common in local development). Uses the same `fulfill_*` methods as webhooks for idempotent dual-path fulfillment.

## Error Handling

```python
try:
    session = await stripe_service.create_subscription_checkout(...)
except ValueError as e:
    # Missing/invalid price ID, customer creation failure
    return {"error": str(e)}
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

1. **Webhook Signature Verification**: Always verify `stripe-signature` header via `stripe.Webhook.construct_event`
2. **Customer Isolation**: Each user has a separate Stripe customer
3. **Idempotent Fulfillment**: `stripe_payment_intent` used as unique key to prevent double-fulfillment
4. **Amount Cross-Validation**: Credit purchases verify `session.amount_total` matches `metadata.amount_cents`
5. **Session Ownership**: `verify-checkout` confirms `metadata.user_id` matches the authenticated user
6. **PCI Compliance**: Card details never touch the server (Stripe Checkout handles)
7. **Race Condition Safety**: `IntegrityError` catch on commit handles webhook/verify-checkout race

## Troubleshooting

**Problem**: Webhook not received
- Check webhook endpoint is publicly accessible
- Verify `STRIPE_WEBHOOK_SECRET` matches Stripe dashboard
- Check Stripe dashboard for delivery failures
- For local dev, use `stripe listen` CLI or rely on `verify-checkout`

**Problem**: Payment succeeded but user not upgraded
- Check webhook logs for fulfillment errors
- Verify `metadata.user_id` is correct
- Check if `verify-checkout` already fulfilled (look for "already_fulfilled" in logs)
- Manually update user tier if needed

**Problem**: "No Stripe price ID configured for tier" error
- Verify `STRIPE_BASIC_PRICE_ID`, `STRIPE_PRO_PRICE_ID`, `STRIPE_ULTRA_PRICE_ID` are set
- For annual billing, also set `STRIPE_*_ANNUAL_PRICE_ID` variants
- Check test vs live mode mismatch

**Problem**: Double credit grant
- Should not happen due to `stripe_payment_intent` idempotency check
- If it does, check for missing `payment_intent` in Stripe session metadata

**Problem**: Credit purchase amount mismatch
- `fulfill_credit_purchase` blocks fulfillment if `amount_total != metadata.amount_cents`
- Logged at CRITICAL level for manual review

## Related Documentation

- [litellm.md](./litellm.md) - AI model routing and per-user keys
- [usage-service.md](./usage-service.md) - Usage tracking and credit deduction
- [../routers/billing.md](../routers/billing.md) - Billing API endpoints
