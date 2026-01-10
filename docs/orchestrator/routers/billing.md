# Billing Router

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/billing.py` (702 lines)

The billing router handles subscription management, credit purchases, usage tracking, and Stripe integration for Tesslate Studio.

## Overview

Tesslate Studio uses a hybrid monetization model:
- **Subscription Tiers**: Free and Pro tiers with different limits
- **Credits**: Pay-as-you-go for AI agent usage and marketplace purchases
- **Usage Tracking**: Monitor API calls, tokens, and costs

## Base Path

All endpoints are mounted at `/api/billing`

## Subscription Management

### Get Subscription

```
GET /api/billing/subscription
```

Returns current subscription status and limits.

**Response**:
```json
{
  "tier": "free|pro",
  "is_active": true,
  "subscription_id": "sub_xxx",
  "stripe_customer_id": "cus_xxx",
  "max_projects": 5,
  "max_deploys": 3,
  "current_period_start": "2025-01-09T00:00:00Z",
  "current_period_end": "2025-02-09T00:00:00Z",
  "cancel_at_period_end": false,
  "cancel_at": null
}
```

**Tier Limits**:

| Feature | Free | Pro |
|---------|------|-----|
| Projects | 3 | 20 |
| Concurrent Deploys | 1 | 5 |
| AI Agent Calls | 50/day | Unlimited |
| Storage | 500MB | 10GB |
| Custom Domains | No | Yes |

### Create Checkout Session

```
POST /api/billing/subscription/checkout
```

Creates a Stripe Checkout session for Pro subscription purchase.

**Request Body**:
```json
{
  "price_id": "price_xxx",  // Stripe price ID
  "success_url": "https://app.tesslate.com/success",
  "cancel_url": "https://app.tesslate.com/cancel"
}
```

**Response**:
```json
{
  "session_id": "cs_test_xxx",
  "url": "https://checkout.stripe.com/pay/cs_test_xxx"
}
```

**Flow**:
1. Frontend calls this endpoint
2. Backend creates Stripe Checkout session
3. Frontend redirects user to Stripe checkout
4. User completes payment
5. Stripe redirects to `success_url`
6. Webhook updates user's subscription

### Cancel Subscription

```
POST /api/billing/subscription/cancel
```

Cancels the Pro subscription at the end of the current billing period.

**Response**:
```json
{
  "message": "Subscription will cancel at period end",
  "cancel_at": "2025-02-09T00:00:00Z"
}
```

User retains Pro features until period end.

### Reactivate Subscription

```
POST /api/billing/subscription/reactivate
```

Reactivates a canceled subscription (before it expires).

**Response**:
```json
{
  "message": "Subscription reactivated"
}
```

## Credit Management

### Get Credit Balance

```
GET /api/billing/credits/balance
```

Returns current credit balance.

**Response**:
```json
{
  "balance_cents": 10000,
  "balance_usd": 100.00
}
```

Credits are stored in cents to avoid floating-point errors.

### Purchase Credits

```
POST /api/billing/credits/purchase
```

Creates a Stripe Checkout session for credit purchase.

**Request Body**:
```json
{
  "package": "small|medium|large",
  "success_url": "https://...",
  "cancel_url": "https://..."
}
```

**Credit Packages**:
- **Small**: $10 = 1,000 credits
- **Medium**: $50 = 5,500 credits (10% bonus)
- **Large**: $100 = 12,000 credits (20% bonus)

**Response**: Checkout session URL

### Get Credit Transactions

```
GET /api/billing/credits/transactions
```

Returns history of credit purchases and usage.

**Response**:
```json
{
  "transactions": [
    {
      "id": "uuid",
      "type": "purchase|usage|refund",
      "amount_cents": 1000,
      "amount_usd": 10.00,
      "status": "completed",
      "description": "Credit package purchase",
      "created_at": "2025-01-09T10:00:00Z"
    }
  ],
  "total": 45
}
```

## Usage Tracking

### Get Usage Summary

```
GET /api/billing/usage/summary
```

Returns AI agent usage statistics for the current billing period.

**Query Parameters**:
- `start_date`: Start of period (ISO format)
- `end_date`: End of period (ISO format)

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
    },
    "gpt-4-turbo": {
      "requests": 45,
      "tokens_input": 10000,
      "tokens_output": 5000,
      "cost_cents": 200
    }
  },
  "by_agent": {
    "default-agent": {
      "requests": 250,
      "cost_cents": 2000
    },
    "react-specialist": {
      "requests": 75,
      "cost_cents": 500
    }
  },
  "period_start": "2025-01-01T00:00:00Z",
  "period_end": "2025-01-31T23:59:59Z"
}
```

### Get Usage Details

```
GET /api/billing/usage/details
```

Returns detailed usage logs with pagination.

**Query Parameters**:
- `skip`: Pagination offset (default: 0)
- `limit`: Results per page (default: 50, max: 100)
- `model`: Filter by model
- `agent_id`: Filter by agent

**Response**:
```json
{
  "logs": [
    {
      "id": "uuid",
      "timestamp": "2025-01-09T10:15:30Z",
      "model": "claude-sonnet-4-5-20250929",
      "agent_id": "uuid",
      "project_id": "uuid",
      "tokens_input": 1500,
      "tokens_output": 800,
      "cost_cents": 12,
      "request_type": "chat"
    }
  ],
  "total": 325,
  "skip": 0,
  "limit": 50
}
```

## Stripe Webhooks

### Webhook Handler

```
POST /api/billing/webhooks/stripe
```

Handles Stripe webhook events for payment processing.

**Webhook Events**:

1. **checkout.session.completed**: Payment successful
   - Updates user's subscription tier
   - Adds credits to user's balance
   - Creates transaction record

2. **customer.subscription.updated**: Subscription changed
   - Updates subscription status in database
   - Handles upgrades/downgrades

3. **customer.subscription.deleted**: Subscription canceled
   - Downgrades user to free tier
   - Preserves existing projects (within free limits)

4. **invoice.payment_failed**: Payment failed
   - Sends notification to user
   - Marks subscription for cancellation

5. **invoice.payment_succeeded**: Recurring payment successful
   - Extends subscription period
   - Updates billing history

**Webhook Security**:

Stripe signature verification:
```python
import stripe

try:
    event = stripe.Webhook.construct_event(
        payload=request.body,
        sig_header=request.headers['Stripe-Signature'],
        secret=settings.stripe_webhook_secret
    )
except stripe.error.SignatureVerificationError:
    raise HTTPException(status_code=400, detail="Invalid signature")
```

## Credit Deduction

Credits are deducted automatically for:

1. **AI Agent Calls**: Based on tokens used
   - Input tokens: $3 per 1M tokens
   - Output tokens: $15 per 1M tokens

2. **Marketplace Purchases**: Based on item price
   - Agent purchase: Fixed credit amount
   - Base purchase: Fixed credit amount

3. **Premium Features**: Coming soon
   - Custom domains
   - Advanced analytics
   - Priority support

**Deduction Example**:
```python
from ..services.usage_service import usage_service

# Track agent call
cost_cents = usage_service.calculate_cost(
    model="claude-sonnet-4-5-20250929",
    tokens_input=1500,
    tokens_output=800
)

# Deduct from balance
await usage_service.deduct_credits(
    user_id=user.id,
    amount_cents=cost_cents,
    description="Agent chat - Project XYZ"
)

# Check if user has sufficient balance
if user.credit_balance_cents < cost_cents:
    raise HTTPException(
        status_code=402,
        detail="Insufficient credits"
    )
```

## Billing Cycle

**Free Tier**:
- No billing cycle
- Usage resets daily (50 agent calls/day)
- No credit card required

**Pro Tier**:
- Monthly billing cycle
- Charged on subscription date each month
- Unlimited agent calls (pay per token)
- Auto-renews unless canceled

## Example Workflows

### Upgrading to Pro

1. **User clicks "Upgrade to Pro"**:
   ```
   POST /api/billing/subscription/checkout
   {
     "price_id": "price_pro_monthly",
     "success_url": "https://app.tesslate.com/success"
   }
   ```

2. **Backend creates Checkout session**

3. **User redirected to Stripe**

4. **User completes payment**

5. **Stripe sends webhook**:
   `checkout.session.completed`

6. **Backend processes webhook**:
   - Finds user by `customer_id`
   - Updates `subscription_tier` to "pro"
   - Updates `stripe_subscription_id`
   - Sends confirmation email

7. **User redirected to success page**

8. **User now has Pro features**

### Purchasing Credits

1. **User selects credit package**:
   ```
   POST /api/billing/credits/purchase
   {"package": "medium"}
   ```

2. **Checkout session created** ($50 for 5,500 credits)

3. **User completes payment**

4. **Webhook received**: `checkout.session.completed`

5. **Backend adds credits**:
   ```python
   user.credit_balance_cents += 550000  # 5,500 credits = $55 = 5500 cents
   ```

6. **Transaction recorded**:
   ```python
   transaction = CreditPurchase(
       user_id=user.id,
       amount_cents=5000,
       credits_purchased=550000,
       stripe_payment_intent_id=payment_intent_id
   )
   ```

### Using Credits for Agent Call

1. **User sends agent message**:
   ```
   POST /api/chat/agent
   {"message": "Create a login page"}
   ```

2. **Agent executes**:
   - Input: 1,500 tokens
   - Output: 800 tokens

3. **Cost calculated**:
   ```python
   cost = (1500 / 1000000) * 3.00 + (800 / 1000000) * 15.00
       = 0.0045 + 0.012
       = 0.0165 USD
       = 1.65 cents
   ```

4. **Credits deducted**:
   ```python
   user.credit_balance_cents -= 2  # Rounded to nearest cent
   ```

5. **Usage logged**:
   ```python
   log = UsageLog(
       user_id=user.id,
       model="claude-sonnet-4-5-20250929",
       tokens_input=1500,
       tokens_output=800,
       cost_cents=2
   )
   ```

## Pricing Calculator

Users can estimate costs before using features:

```
GET /api/billing/pricing/estimate
```

**Query Parameters**:
- `feature`: "agent_call|marketplace_agent|marketplace_base"
- `model`: AI model ID
- `tokens_input`: Estimated input tokens
- `tokens_output`: Estimated output tokens

**Response**:
```json
{
  "feature": "agent_call",
  "model": "claude-sonnet-4-5-20250929",
  "tokens_input": 2000,
  "tokens_output": 1000,
  "estimated_cost_cents": 21,
  "estimated_cost_usd": 0.21
}
```

## Security

1. **Webhook Verification**: Stripe signatures validated
2. **Idempotency**: Webhook events processed once (using Stripe event ID)
3. **Balance Checks**: Prevent negative balances
4. **Transaction Logging**: All credit changes audited
5. **PCI Compliance**: No credit card data stored (handled by Stripe)

## Related Files

- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/stripe_service.py` - Stripe integration
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/usage_service.py` - Usage tracking and cost calculation
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/models.py` - CreditPurchase, UsageLog models
