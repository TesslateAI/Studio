# Stripe Integration - Complete Guide

## Overview

OpenSail uses Stripe for subscription management, credit purchases, and marketplace payments. This guide covers the complete implementation.

---

## System Architecture

### 4-Tier Subscription Model

| Tier | Monthly Price | Projects | Deploys | Bundled Credits | BYOK |
|------|---------------|----------|---------|-----------------|------|
| **Free** | $0 | 3 | 1 | 1,000 | No |
| **Basic** | $8 | 5 | 2 | 1,000 | No |
| **Pro** | $20 | 10 | 5 | 2,500 | Yes |
| **Ultra** | $100 | Unlimited | 20 | 12,000 | Yes |

### Dual Credit System

**1 credit = $0.01 USD**

| Credit Type | Description | Expiration |
|-------------|-------------|------------|
| **Bundled Credits** | Monthly allowance included with tier | Reset on billing date |
| **Purchased Credits** | Additional credits bought separately | Never expire |

**Consumption Order**:
1. Bundled credits are consumed first
2. Purchased credits are consumed after bundled credits are depleted

### Credit Packages

| Package | Credits | Price |
|---------|---------|-------|
| Small | 500 | $5 |
| Medium | 1,000 | $10 |

---

## Backend Implementation

### Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/routers/billing.py` | API endpoints |
| `orchestrator/app/routers/webhooks.py` | Stripe webhook handler |
| `orchestrator/app/services/stripe_service.py` | Stripe API wrapper |
| `orchestrator/app/services/usage_service.py` | Usage tracking |
| `orchestrator/app/config.py` | Stripe configuration |
| `orchestrator/app/models.py` | CreditPurchase, UsageLog models |
| `orchestrator/app/models_auth.py` | User model with credit fields |

### API Endpoints

```
# Subscription
GET  /api/billing/subscription     - Get current subscription status
POST /api/billing/subscribe        - Create Stripe checkout for tier upgrade
POST /api/billing/cancel           - Cancel subscription at period end
POST /api/billing/renew            - Reactivate cancelled subscription
GET  /api/billing/portal           - Get Stripe Customer Portal URL

# Credits
GET  /api/billing/credits          - Get detailed credit balance
GET  /api/billing/credits/status   - Get low balance warning status
POST /api/billing/credits/purchase - Create Stripe checkout for credits
GET  /api/billing/credits/history  - Get credit purchase history

# Usage
GET  /api/billing/usage            - Get usage summary for date range
POST /api/billing/usage/sync       - Sync usage from LiteLLM
GET  /api/billing/usage/logs       - Get detailed usage logs

# Transactions
GET  /api/billing/transactions     - Get all transaction history

# Creator
GET  /api/billing/earnings         - Get creator earnings
POST /api/billing/connect          - Create Stripe Connect onboarding link

# Config (public)
GET  /api/billing/config           - Get public billing configuration
```

### Database Models

```python
# User model (models_auth.py)
class User(Base):
    # Credit system
    bundled_credits: int = 1000      # Monthly allowance
    purchased_credits: int = 0        # Never expire
    credits_reset_date: datetime      # When bundled credits reset

    # Subscription
    subscription_tier: str = "free"   # free, basic, pro, ultra
    stripe_customer_id: str
    stripe_subscription_id: str

    @property
    def total_credits(self) -> int:
        return (self.bundled_credits or 0) + (self.purchased_credits or 0)

# Credit purchase record (models.py)
class CreditPurchase(Base):
    id: UUID
    user_id: UUID
    amount_cents: int              # Amount paid
    credits_amount: int            # Credits received
    stripe_payment_intent: str     # For idempotency
    stripe_checkout_session: str
    status: str                    # pending, completed, failed
    created_at: datetime
    completed_at: datetime

# Usage log (models.py)
class UsageLog(Base):
    id: UUID
    user_id: UUID
    model: str                     # Model used
    tokens_input: int
    tokens_output: int
    cost_total_cents: int          # Credits consumed
    agent_id: UUID
    project_id: UUID
    billed_status: str             # unbilled, paid
    created_at: datetime
```

### Webhook Handling

```python
# orchestrator/app/routers/webhooks.py
@router.post("/stripe")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    event = stripe.Webhook.construct_event(
        payload, sig, settings.stripe_webhook_secret
    )

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session["metadata"]

        if metadata.get("type") == "subscription":
            # Handle subscription upgrade
            await handle_subscription_checkout(session, db)
        elif metadata.get("type") == "credit_purchase":
            # Handle credit purchase
            await handle_credit_purchase_checkout(session, db)

    elif event["type"] == "customer.subscription.deleted":
        # Downgrade to free tier
        await handle_subscription_deleted(event["data"]["object"], db)

    elif event["type"] == "invoice.payment_succeeded":
        # Reset bundled credits on subscription renewal
        await handle_invoice_paid(event["data"]["object"], db)

    return {"status": "success"}
```

---

## Frontend Implementation

### Key Files

| File | Purpose |
|------|---------|
| `app/src/pages/settings/BillingSettings.tsx` | Main billing page |
| `app/src/components/billing/` | Billing components |
| `app/src/lib/api.ts` | billingApi methods |
| `app/src/types/billing.ts` | TypeScript types |

### API Client

```typescript
// app/src/lib/api.ts
export const billingApi = {
  // Subscription
  getSubscription: () => api.get('/api/billing/subscription').then(r => r.data),
  subscribe: (tier: string) => api.post('/api/billing/subscribe', { tier }).then(r => r.data),
  cancelSubscription: (atPeriodEnd: boolean) =>
    api.post(`/api/billing/cancel?at_period_end=${atPeriodEnd}`).then(r => r.data),
  renewSubscription: () => api.post('/api/billing/renew').then(r => r.data),
  getCustomerPortal: () => api.get('/api/billing/portal').then(r => r.data),

  // Credits
  getCreditsBalance: () => api.get('/api/billing/credits').then(r => r.data),
  getCreditsStatus: () => api.get('/api/billing/credits/status').then(r => r.data),
  purchaseCredits: (pkg: 'small' | 'medium') =>
    api.post('/api/billing/credits/purchase', { package: pkg }).then(r => r.data),
  getCreditsHistory: (limit = 50, offset = 0) =>
    api.get(`/api/billing/credits/history?limit=${limit}&offset=${offset}`).then(r => r.data),

  // Usage
  getUsage: (startDate?: string, endDate?: string) =>
    api.get('/api/billing/usage', { params: { start_date: startDate, end_date: endDate } }).then(r => r.data),
  getUsageLogs: (limit = 100, offset = 0) =>
    api.get(`/api/billing/usage/logs?limit=${limit}&offset=${offset}`).then(r => r.data),

  // Transactions
  getTransactions: (limit = 50, offset = 0) =>
    api.get(`/api/billing/transactions?limit=${limit}&offset=${offset}`).then(r => r.data),

  // Config
  getConfig: () => api.get('/api/billing/config').then(r => r.data),
};
```

### TypeScript Types

```typescript
// app/src/types/billing.ts
interface SubscriptionResponse {
  tier: 'free' | 'basic' | 'pro' | 'ultra';
  is_active: boolean;
  subscription_id: string | null;
  stripe_customer_id: string | null;
  max_projects: number;
  max_deploys: number;
  current_period_start: string;
  current_period_end: string;
  cancel_at_period_end: boolean;
  cancel_at: string | null;
  bundled_credits: number;
  purchased_credits: number;
  total_credits: number;
  monthly_allowance: number;
  credits_reset_date: string;
  byok_enabled: boolean;
}

interface CreditBalanceResponse {
  bundled_credits: number;
  purchased_credits: number;
  total_credits: number;
  monthly_allowance: number;
  credits_reset_date: string;
  tier: string;
}

interface CreditStatusResponse {
  total_credits: number;
  is_low: boolean;
  is_empty: boolean;
  threshold: number;
  tier: string;
  monthly_allowance: number;
}
```

---

## Environment Variables

### Required Variables

```bash
# Stripe API Keys
STRIPE_SECRET_KEY=sk_test_xxx           # Backend only
STRIPE_PUBLISHABLE_KEY=pk_test_xxx      # Exposed to frontend
STRIPE_WEBHOOK_SECRET=whsec_xxx         # For webhook verification

# Stripe Price IDs (create in Stripe Dashboard)
STRIPE_BASIC_PRICE_ID=price_xxx         # $8/month Basic tier
STRIPE_PRO_PRICE_ID=price_xxx           # $20/month Pro tier
STRIPE_ULTRA_PRICE_ID=price_xxx         # $100/month Ultra tier
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

# BYOK
BYOK_ENABLED_TIERS=pro,ultra
```

### Credit Packages

```bash
# Credit package prices (cents) - 1:1 ratio with credits
CREDIT_PACKAGE_SMALL=500    # $5 = 500 credits
CREDIT_PACKAGE_MEDIUM=1000  # $10 = 1000 credits

# Low balance threshold
CREDITS_LOW_BALANCE_THRESHOLD=0.20  # 20% of monthly allowance
```

---

## Stripe Dashboard Setup

### 1. Create Products

In Stripe Dashboard → Products:

1. **Basic Plan**
   - Name: "Tesslate Basic"
   - Price: $8/month (recurring)
   - Copy Price ID → `STRIPE_BASIC_PRICE_ID`

2. **Pro Plan**
   - Name: "Tesslate Pro"
   - Price: $20/month (recurring)
   - Copy Price ID → `STRIPE_PRO_PRICE_ID`

3. **Ultra Plan**
   - Name: "Tesslate Ultra"
   - Price: $100/month (recurring)
   - Copy Price ID → `STRIPE_ULTRA_PRICE_ID`

### 2. Configure Webhooks

In Stripe Dashboard → Developers → Webhooks:

1. Add endpoint: `https://your-domain.com/api/webhooks/stripe`
2. Select events:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
3. Copy Signing secret → `STRIPE_WEBHOOK_SECRET`

### 3. Customer Portal

In Stripe Dashboard → Settings → Billing → Customer portal:

1. Enable customer portal
2. Configure allowed actions:
   - Update payment methods
   - View invoices
   - Cancel subscriptions

---

## Checkout Flows

### Subscription Upgrade

```
1. User clicks "Upgrade to Pro"
2. Frontend calls POST /api/billing/subscribe { tier: "pro" }
3. Backend creates Stripe Checkout Session
4. Backend returns { url: "https://checkout.stripe.com/..." }
5. Frontend redirects to Stripe
6. User completes payment
7. Stripe sends checkout.session.completed webhook
8. Backend updates user.subscription_tier to "pro"
9. Backend sets user.bundled_credits to 2500
10. Stripe redirects user to /settings/billing?success=true
11. Frontend shows success toast and refreshes data
```

### Credit Purchase

```
1. User clicks "Purchase 500 Credits"
2. Frontend calls POST /api/billing/credits/purchase { package: "small" }
3. Backend creates Stripe Checkout Session
4. Backend returns { url: "https://checkout.stripe.com/..." }
5. Frontend redirects to Stripe
6. User completes payment
7. Stripe sends checkout.session.completed webhook
8. Backend checks idempotency (payment_intent not processed)
9. Backend adds 500 to user.purchased_credits
10. Backend creates CreditPurchase record
11. Stripe redirects user to /settings/billing?success=true
```

### Subscription Cancellation

```
1. User clicks "Cancel Subscription"
2. Frontend shows confirmation dialog
3. User confirms
4. Frontend calls POST /api/billing/cancel?at_period_end=true
5. Backend calls stripe.Subscription.modify(cancel_at_period_end=True)
6. User retains access until period end
7. At period end, Stripe sends customer.subscription.deleted
8. Backend downgrades user to free tier
```

---

## Usage Tracking

### How Credits Are Consumed

Credits are consumed during AI operations:

1. User sends message in chat
2. Backend processes with LiteLLM
3. LiteLLM logs usage
4. Periodic sync pulls usage from LiteLLM
5. Backend calculates cost based on model pricing
6. Backend deducts from bundled_credits first
7. If bundled_credits depleted, deducts from purchased_credits

### Cost Calculation

```python
# Cost per 1M tokens (example pricing)
MODEL_PRICING = {
    "claude-sonnet-4-5-20250929": {
        "input": 300,   # $3.00 per 1M input tokens
        "output": 1500  # $15.00 per 1M output tokens
    },
    "gpt-4o": {
        "input": 500,
        "output": 1500
    }
}

def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> int:
    """Returns cost in credits (cents)"""
    pricing = MODEL_PRICING.get(model, {"input": 100, "output": 300})
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return int(input_cost + output_cost)
```

---

## Testing

### Test Cards

| Card Number | Result |
|-------------|--------|
| `4242 4242 4242 4242` | Succeeds |
| `4000 0000 0000 0002` | Card declined |
| `4000 0000 0000 3220` | Requires 3D Secure |
| `4000 0000 0000 9995` | Insufficient funds |

### Local Webhook Testing

```bash
# Install Stripe CLI
brew install stripe/stripe-cli/stripe

# Login
stripe login

# Forward webhooks to local server
stripe listen --forward-to localhost:8000/api/webhooks/stripe

# Copy webhook signing secret and add to .env
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

### Test Scenarios

1. **Subscription upgrade**: Free → Pro
2. **Credit purchase**: Buy 500 credits
3. **Subscription cancel**: Cancel Pro subscription
4. **Credit depletion**: Use all credits, verify low balance warning
5. **Webhook idempotency**: Send same webhook twice, verify no duplicate processing

---

## Security Considerations

1. **Webhook Signature Verification**: All webhooks verified using STRIPE_WEBHOOK_SECRET
2. **Idempotency**: Payment intents checked before processing to prevent duplicates
3. **Server-side Validation**: All limits enforced on backend, not just frontend
4. **No Credit Card Storage**: Stripe handles all payment information
5. **Secrets Management**: Never commit real API keys to git

---

## Troubleshooting

### "Failed to initiate upgrade"

**Cause**: Missing Stripe price IDs

**Fix**:
1. Create products in Stripe Dashboard
2. Add price IDs to environment variables:
   ```bash
   STRIPE_BASIC_PRICE_ID=price_xxx
   STRIPE_PRO_PRICE_ID=price_xxx
   STRIPE_ULTRA_PRICE_ID=price_xxx
   ```
3. Restart backend

### Subscription not updating after checkout

**Check**:
1. Webhook endpoint accessible from internet
2. Webhook secret matches environment variable
3. Backend logs show webhook received
4. No database errors in webhook handler

### Credits not deducting

**Check**:
1. Usage sync running (check logs)
2. LiteLLM configured correctly
3. Cost calculation returning non-zero

### Low balance warning not showing

**Check**:
1. `getCreditsStatus()` API returns `is_low: true`
2. Threshold calculation: `totalCredits <= 0.20 * monthlyAllowance`

---

## Production Checklist

- [ ] Switch to live Stripe keys
- [ ] Create live products and prices
- [ ] Configure production webhook endpoint
- [ ] Test complete purchase flow with real payment
- [ ] Verify webhook events received
- [ ] Test subscription cancellation
- [ ] Test credit purchase
- [ ] Verify usage tracking
- [ ] Monitor Stripe Dashboard for failed payments

---

## Related Documentation

- **Backend Router**: `docs/orchestrator/routers/billing.md`
- **Frontend Components**: `docs/app/components/billing/README.md`
- **Agent Context**: `docs/app/components/billing/CLAUDE.md`
- **Billing Page**: `docs/app/pages/billing.md`
