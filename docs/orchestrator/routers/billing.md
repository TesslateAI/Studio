# Billing Router

**File**: `orchestrator/app/routers/billing.py`

The billing router handles subscription management, credit purchases, usage tracking, and Stripe integration for OpenSail.

## Overview

OpenSail uses a **4-tier subscription model** with a **dual credit system**:

### Subscription Tiers

| Tier | Price | Projects | Deploys | Monthly Credits | BYOK |
|------|-------|----------|---------|-----------------|------|
| **Free** | $0/mo | 3 | 1 | 1,000 | No |
| **Basic** | $8/mo | 5 | 2 | 1,000 | No |
| **Pro** | $20/mo | 10 | 5 | 2,500 | Yes |
| **Ultra** | $100/mo | Unlimited | 20 | 12,000 | Yes |

### Credit System

Credits are the currency for AI usage. **1 credit = $0.01 USD**.

- **Bundled Credits**: Monthly allowance that comes with your subscription. Resets on your billing date.
- **Purchased Credits**: Buy additional credits that **never expire**. Used after bundled credits are depleted.

**Credit Consumption Order**:
1. Bundled credits are consumed first
2. Purchased credits are consumed after bundled credits are exhausted
3. Total credits = bundled_credits + purchased_credits

## Base Path

All endpoints are mounted at `/api/billing`

---

## Subscription Endpoints

### Get Subscription Status

```
GET /api/billing/subscription
```

Returns current subscription status, limits, and credit balance.

**Response**:
```json
{
  "tier": "pro",
  "is_active": true,
  "subscription_id": "sub_xxx",
  "stripe_customer_id": "cus_xxx",
  "max_projects": 10,
  "max_deploys": 5,
  "current_period_start": "2026-01-01T00:00:00Z",
  "current_period_end": "2026-02-01T00:00:00Z",
  "cancel_at_period_end": false,
  "cancel_at": null,
  "bundled_credits": 2500,
  "purchased_credits": 500,
  "total_credits": 3000,
  "monthly_allowance": 2500,
  "credits_reset_date": "2026-02-01T00:00:00Z",
  "byok_enabled": true
}
```

### Create Subscription Checkout

```
POST /api/billing/subscribe
```

Creates a Stripe Checkout session for a subscription tier upgrade.

**Request Body**:
```json
{
  "tier": "pro"
}
```

Valid tiers: `basic`, `pro`, `ultra`

**Response**:
```json
{
  "session_id": "cs_test_xxx",
  "url": "https://checkout.stripe.com/c/pay/cs_test_xxx"
}
```

**Flow**:
1. Frontend calls this endpoint with desired tier
2. Backend validates tier and creates Stripe Checkout session
3. Frontend redirects user to Stripe checkout URL
4. User completes payment on Stripe
5. Stripe sends `checkout.session.completed` webhook
6. Backend updates user's tier and grants bundled credits
7. User is redirected to `/settings/billing?success=true`

### Cancel Subscription

```
POST /api/billing/cancel
```

Cancels the subscription at the end of the current billing period.

**Query Parameters**:
- `at_period_end`: boolean (default: true) - If true, access continues until period end

**Response**:
```json
{
  "success": true,
  "message": "Subscription will cancel at end of period"
}
```

### Renew Subscription

```
POST /api/billing/renew
```

Reactivates a cancelled subscription (before it expires).

**Response**:
```json
{
  "success": true,
  "message": "Subscription has been renewed and will continue after the current period"
}
```

### Get Customer Portal

```
GET /api/billing/portal
```

Returns a Stripe Customer Portal URL for managing payment methods and invoices.

**Response**:
```json
{
  "url": "https://billing.stripe.com/session/xxx"
}
```

---

## Credits Endpoints

### Get Credits Balance

```
GET /api/billing/credits
```

Returns detailed credit balance information.

**Response**:
```json
{
  "bundled_credits": 1500,
  "purchased_credits": 500,
  "total_credits": 2000,
  "monthly_allowance": 2500,
  "credits_reset_date": "2026-02-01T00:00:00Z",
  "tier": "pro"
}
```

### Get Credit Status (Low Balance Warning)

```
GET /api/billing/credits/status
```

Returns credit status for low balance warnings.

**Response**:
```json
{
  "total_credits": 200,
  "is_low": true,
  "is_empty": false,
  "threshold": 500,
  "tier": "pro",
  "monthly_allowance": 2500
}
```

**Thresholds**:
- `is_low`: True when total credits ≤ 20% of monthly allowance
- `is_empty`: True when total credits = 0

### Purchase Credits

```
POST /api/billing/credits/purchase
```

Creates a Stripe Checkout session for purchasing additional credits.

**Request Body**:
```json
{
  "package": "small"
}
```

**Credit Packages**:

| Package | Credits | Price |
|---------|---------|-------|
| `small` | 500 | $5 |
| `medium` | 1000 | $10 |

**Response**:
```json
{
  "session_id": "cs_test_xxx",
  "url": "https://checkout.stripe.com/c/pay/cs_test_xxx"
}
```

### Get Credit Purchase History

```
GET /api/billing/credits/history
```

Returns history of credit purchases.

**Query Parameters**:
- `limit`: number (default: 50)
- `offset`: number (default: 0)

**Response**:
```json
{
  "purchases": [
    {
      "id": "uuid",
      "amount_cents": 500,
      "amount_usd": 5.00,
      "credits_amount": 500,
      "status": "completed",
      "created_at": "2026-01-15T10:00:00Z",
      "completed_at": "2026-01-15T10:01:00Z"
    }
  ]
}
```

---

## Usage Endpoints

### Get Usage Summary

```
GET /api/billing/usage
```

Returns AI usage statistics for a date range.

**Query Parameters**:
- `start_date`: ISO date string (default: start of current month)
- `end_date`: ISO date string (default: now)

**Response**:
```json
{
  "total_cost_cents": 2500,
  "total_cost_usd": 25.00,
  "total_tokens_input": 150000,
  "total_tokens_output": 50000,
  "total_requests": 325,
  "by_model": {
    "claude-sonnet-4-5-20250929": {
      "requests": 280,
      "tokens_input": 140000,
      "tokens_output": 45000,
      "cost_cents": 2300
    }
  },
  "by_agent": {
    "default-agent": {
      "requests": 250,
      "cost_cents": 2000
    }
  },
  "period_start": "2026-01-01T00:00:00Z",
  "period_end": "2026-01-31T23:59:59Z"
}
```

### Sync Usage from LiteLLM

```
POST /api/billing/usage/sync
```

Manually triggers usage sync from LiteLLM.

**Query Parameters**:
- `start_date`: ISO date string (default: 24 hours ago)

**Response**:
```json
{
  "success": true,
  "logs_synced": 45,
  "message": "Synced 45 usage entries"
}
```

### Get Usage Logs

```
GET /api/billing/usage/logs
```

Returns detailed usage logs with pagination.

**Query Parameters**:
- `limit`: number (default: 100)
- `offset`: number (default: 0)
- `start_date`: ISO date string
- `end_date`: ISO date string

**Response**:
```json
{
  "logs": [
    {
      "id": "uuid",
      "model": "claude-sonnet-4-5-20250929",
      "tokens_input": 1500,
      "tokens_output": 800,
      "cost_total_cents": 12,
      "cost_total_usd": 0.12,
      "agent_id": "uuid",
      "project_id": "uuid",
      "billed_status": "paid",
      "created_at": "2026-01-15T10:15:30Z"
    }
  ]
}
```

---

## Transaction History

### Get All Transactions

```
GET /api/billing/transactions
```

Returns combined transaction history (credits, subscriptions, agent purchases).

**Query Parameters**:
- `limit`: number (default: 50)
- `offset`: number (default: 0)

**Response**:
```json
{
  "transactions": [
    {
      "id": "uuid",
      "type": "credit_purchase",
      "amount_cents": 500,
      "amount_usd": 5.00,
      "status": "completed",
      "created_at": "2026-01-15T10:00:00Z"
    },
    {
      "id": "uuid",
      "type": "agent_purchase",
      "amount_cents": 999,
      "amount_usd": 9.99,
      "status": "completed",
      "agent_id": "uuid",
      "created_at": "2026-01-14T15:30:00Z"
    }
  ]
}
```

---

## Creator Endpoints

### Get Creator Earnings

```
GET /api/billing/earnings
```

Returns earnings from marketplace agents (for creators).

**Query Parameters**:
- `start_date`: ISO date string (default: start of current month)
- `end_date`: ISO date string (default: now)

**Response**:
```json
{
  "total_earnings_cents": 4500,
  "total_earnings_usd": 45.00,
  "transactions": [...],
  "period_start": "2026-01-01T00:00:00Z",
  "period_end": "2026-01-31T23:59:59Z"
}
```

### Connect Stripe Account

```
POST /api/billing/connect
```

Creates a Stripe Connect onboarding link for receiving payouts.

**Response**:
```json
{
  "url": "https://connect.stripe.com/setup/xxx"
}
```

---

## Configuration Endpoint

### Get Billing Config

```
GET /api/billing/config
```

Returns public billing configuration for the frontend. **No authentication required**.

**Response**:
```json
{
  "stripe_publishable_key": "pk_test_xxx",
  "credit_packages": {
    "small": {
      "credits": 500,
      "price_cents": 500
    },
    "medium": {
      "credits": 1000,
      "price_cents": 1000
    }
  },
  "deploy_price": 1000,
  "tiers": {
    "free": {
      "price_cents": 0,
      "max_projects": 3,
      "max_deploys": 1,
      "bundled_credits": 1000,
      "byok_enabled": false
    },
    "basic": {
      "price_cents": 800,
      "max_projects": 5,
      "max_deploys": 2,
      "bundled_credits": 1000,
      "byok_enabled": false
    },
    "pro": {
      "price_cents": 2000,
      "max_projects": 10,
      "max_deploys": 5,
      "bundled_credits": 2500,
      "byok_enabled": true
    },
    "ultra": {
      "price_cents": 10000,
      "max_projects": 999,
      "max_deploys": 20,
      "bundled_credits": 12000,
      "byok_enabled": true
    }
  },
  "low_balance_threshold": 0.20
}
```

---

## Stripe Webhook Handling

Webhooks are handled at `POST /api/webhooks/stripe`

### Handled Events

| Event | Action |
|-------|--------|
| `checkout.session.completed` | Process subscription, credit, or agent purchase |
| `customer.subscription.created` | Log new subscription |
| `customer.subscription.updated` | Update subscription status |
| `customer.subscription.deleted` | Downgrade user to free tier |
| `invoice.payment_succeeded` | Mark usage as paid |
| `invoice.payment_failed` | Log failure, notify user |
| `payment_intent.succeeded` | Log one-time payment |

### Subscription Checkout Handling

When a subscription checkout completes:

1. Extract `user_id` and `tier` from session metadata
2. Update user's `subscription_tier` to the new tier
3. Set `bundled_credits` based on tier:
   - Free: 1,000
   - Basic: 1,000
   - Pro: 2,500
   - Ultra: 12,000
4. Set `credits_reset_date` to 30 days from now
5. Store `stripe_subscription_id` for future management

### Credit Purchase Handling

When a credit purchase completes:

1. Check for idempotency (payment_intent already processed)
2. Create `CreditPurchase` record
3. Add credits to `purchased_credits` (NOT bundled_credits)
4. Purchased credits never expire

---

## Environment Variables

### Required for Stripe

```bash
# Stripe API Keys
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_PUBLISHABLE_KEY=pk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx

# Stripe Price IDs (create in Stripe Dashboard)
STRIPE_BASIC_PRICE_ID=price_xxx
STRIPE_PRO_PRICE_ID=price_xxx
STRIPE_ULTRA_PRICE_ID=price_xxx
```

### Tier Configuration

```bash
# Tier Pricing (cents)
TIER_PRICE_FREE=0
TIER_PRICE_BASIC=800
TIER_PRICE_PRO=2000
TIER_PRICE_ULTRA=10000

# Bundled Credits per Tier
TIER_BUNDLED_CREDITS_FREE=1000
TIER_BUNDLED_CREDITS_BASIC=1000
TIER_BUNDLED_CREDITS_PRO=2500
TIER_BUNDLED_CREDITS_ULTRA=12000

# Project Limits
TIER_MAX_PROJECTS_FREE=3
TIER_MAX_PROJECTS_BASIC=5
TIER_MAX_PROJECTS_PRO=10
TIER_MAX_PROJECTS_ULTRA=999

# Deploy Limits
TIER_MAX_DEPLOYS_FREE=1
TIER_MAX_DEPLOYS_BASIC=2
TIER_MAX_DEPLOYS_PRO=5
TIER_MAX_DEPLOYS_ULTRA=20

# BYOK Tiers
BYOK_ENABLED_TIERS=pro,ultra
```

### Credit Packages

```bash
# Credit package prices (cents) - 1:1 ratio with credits
CREDIT_PACKAGE_SMALL=500    # $5 = 500 credits
CREDIT_PACKAGE_MEDIUM=1000  # $10 = 1000 credits

# Low balance threshold (percentage of monthly allowance)
CREDITS_LOW_BALANCE_THRESHOLD=0.20
```

---

## Database Models

### User Credit Fields

```python
class User(Base):
    # Credit system
    bundled_credits: int = 1000      # Monthly allowance, resets on billing date
    purchased_credits: int = 0        # Never expire
    credits_reset_date: datetime      # When bundled credits reset

    # Subscription
    subscription_tier: str = "free"   # free, basic, pro, ultra
    stripe_customer_id: str
    stripe_subscription_id: str

    @property
    def total_credits(self) -> int:
        return (self.bundled_credits or 0) + (self.purchased_credits or 0)
```

### Credit Purchase Record

```python
class CreditPurchase(Base):
    id: UUID
    user_id: UUID
    amount_cents: int              # Amount paid
    credits_amount: int            # Credits received (1:1 ratio)
    stripe_payment_intent: str
    stripe_checkout_session: str
    status: str                    # pending, completed, failed
    created_at: datetime
    completed_at: datetime
```

---

## Security Considerations

1. **Webhook Signature Verification**: All Stripe webhooks are verified using the webhook secret
2. **Idempotency**: Payment intents are checked to prevent duplicate processing
3. **Balance Checks**: Server-side validation before any credit-consuming operation
4. **User Isolation**: Users can only access their own billing data
5. **No Credit Card Storage**: All payment info handled by Stripe

---

## Related Files

- `orchestrator/app/services/stripe_service.py` - Stripe integration service
- `orchestrator/app/services/usage_service.py` - Usage tracking and cost calculation
- `orchestrator/app/routers/webhooks.py` - Webhook endpoint
- `orchestrator/app/models.py` - CreditPurchase, UsageLog models
- `orchestrator/app/models_auth.py` - User model with credit fields
- `orchestrator/app/config.py` - Billing configuration
- `orchestrator/alembic/versions/0005_billing_credits_system.py` - Credits migration
