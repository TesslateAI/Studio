# Stripe Integration Testing Guide

This guide provides comprehensive instructions for testing the Stripe integration in Tesslate Studio.

## Prerequisites

1. **Stripe Account**: Sign up at https://dashboard.stripe.com/register
2. **Stripe CLI**: Install from https://stripe.com/docs/stripe-cli
3. **Test API Keys**: Available in your Stripe Dashboard (Test mode)

## Initial Setup

### 1. Configure Environment Variables

Update your `.env` file with your Stripe test keys:

```bash
# Stripe Test Keys (from https://dashboard.stripe.com/test/apikeys)
STRIPE_SECRET_KEY=sk_test_your_test_secret_key_here
STRIPE_PUBLISHABLE_KEY=pk_test_your_test_publishable_key_here

# Stripe Webhook Secret (will be generated in step 3)
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret_here

# Stripe Connect (optional, for creator payouts)
STRIPE_CONNECT_CLIENT_ID=ca_your_connect_client_id_here
```

### 2. Create Stripe Products

In your Stripe Dashboard (Test mode), create the following products:

#### Premium Subscription Product
1. Go to https://dashboard.stripe.com/test/products
2. Click "Add product"
3. Name: "Tesslate Studio Premium"
4. Description: "$5/month subscription"
5. Pricing model: "Standard pricing"
6. Price: $5.00 USD
7. Billing period: Monthly
8. Copy the **Price ID** (starts with `price_`) and set it in your `.env`:
   ```bash
   STRIPE_PREMIUM_PRICE_ID=price_xxxxxxxxxxxxx
   ```

### 3. Set Up Webhook Forwarding

For local testing, use the Stripe CLI to forward webhook events:

```bash
# Login to Stripe CLI
stripe login

# Forward webhooks to your local server
stripe listen --forward-to http://localhost:8000/api/webhooks/stripe
```

**Important**: Copy the webhook signing secret from the output (starts with `whsec_`) and add it to your `.env`:

```bash
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxx
```

### 4. Run Database Migration

Apply the Stripe database migration:

```bash
cd orchestrator
python -m alembic upgrade head
```

### 5. Start the Application

```bash
# Start backend
cd orchestrator
python -m uvicorn app.main:app --reload

# Start frontend (in another terminal)
cd app
npm run dev
```

## Test Scenarios

### Scenario 1: User Registration with Stripe Customer Creation

**Test**: New user registration automatically creates a Stripe customer.

1. Register a new user at http://localhost:5173/register
2. Check logs for: `Created Stripe customer for user {username}: cus_xxxxx`
3. Verify in Stripe Dashboard: https://dashboard.stripe.com/test/customers
4. Confirm customer metadata includes `user_id` and `username`

**Expected**: User has `stripe_customer_id` in database.

---

### Scenario 2: Premium Subscription Purchase

**Test**: User can subscribe to premium tier ($5/month).

#### API Testing:
```bash
# Get subscription status
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  http://localhost:8000/api/billing/subscription

# Create subscription checkout
curl -X POST -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  http://localhost:8000/api/billing/subscribe
```

#### Full Flow:
1. Login as a user
2. Navigate to billing page
3. Click "Upgrade to Premium"
4. Complete checkout using test card: `4242 4242 4242 4242`
   - Expiry: Any future date
   - CVC: Any 3 digits
   - ZIP: Any 5 digits
5. Webhook fires: `checkout.session.completed`
6. User's `subscription_tier` changes to "pro"
7. Verify in database: `SELECT subscription_tier, stripe_subscription_id FROM users WHERE id = 'user_id';`

**Expected**: User is upgraded to premium, can create 5 projects and 5 deploys.

---

### Scenario 3: Credit Purchase

**Test**: User can purchase credits ($5, $10, $50 packages).

#### API Testing:
```bash
# Get current balance
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  http://localhost:8000/api/billing/credits

# Purchase $10 credits
curl -X POST -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"package": "medium"}' \
  http://localhost:8000/api/billing/credits/purchase
```

#### Full Flow:
1. Navigate to credits page
2. Select package ($5/$10/$50)
3. Complete checkout with test card
4. Webhook fires: `checkout.session.completed`
5. Credits are added to `credits_balance`
6. Record created in `credit_purchases` table

**Expected**: User's credit balance increases by purchased amount.

---

### Scenario 4: Marketplace Agent Purchase (Monthly Subscription)

**Test**: User can purchase a monthly agent subscription.

**Prerequisites**:
- Create a test agent with `pricing_type="monthly"` and `price=X` (price in cents, e.g., 2000=$20, 500=$5, 9900=$99)
- Creators can set any monthly price they want
- Set `stripe_price_id` or leave null (will create on-the-fly)

#### API Testing:
```bash
# Purchase agent
curl -X POST -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  http://localhost:8000/api/marketplace/agents/{agent_id}/purchase
```

#### Full Flow:
1. Browse marketplace
2. Click on paid agent (monthly)
3. Click "Purchase"
4. Complete checkout
5. Webhook fires: `checkout.session.completed`
6. Agent added to user's library (`user_purchased_agents`)
7. Transaction created with 90/10 revenue split
8. Creator receives payout (if Connect account set up)

**Expected**: Agent appears in user's library, transaction tracked.

---

### Scenario 5: Project Limit Enforcement

**Test**: Free users are limited to 1 project, premium users to 5.

#### As Free User:
```bash
# Try to create 2nd project (should fail)
curl -X POST -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Second Project", "description": "Test"}' \
  http://localhost:8000/api/projects/
```

**Expected**: HTTP 403 with message about upgrading.

#### As Premium User:
1. Subscribe to premium
2. Create projects 1-5 (should succeed)
3. Try to create 6th project (should fail)

---

### Scenario 6: Deploy Project

**Test**: Users can deploy projects based on tier limits.

#### API Testing:
```bash
# Get deployment limits
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  http://localhost:8000/api/projects/deployment/limits

# Deploy a project
curl -X POST -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  http://localhost:8000/api/projects/{project_slug}/deploy
```

#### Full Flow:
1. Create a project
2. Click "Deploy" button
3. Project marked as deployed (`is_deployed=true`)
4. Container kept running permanently
5. Try to deploy beyond limit (1 for free, 5 for premium)
6. Should show option to purchase additional slot ($10)

---

### Scenario 7: Purchase Additional Deploy Slot

**Test**: Users can buy extra deploy slots for $10 each.

```bash
curl -X POST -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  http://localhost:8000/api/projects/deployment/purchase-slot
```

**Expected**: Checkout created for $10, after payment user can deploy one more project.

---

### Scenario 8: Usage Tracking & Billing

**Test**: API usage is tracked and billed monthly.

#### Manual Usage Sync:
```bash
# Sync usage from LiteLLM
curl -X POST -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  http://localhost:8000/api/billing/usage/sync

# Get usage summary
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  "http://localhost:8000/api/billing/usage?start_date=2025-01-01&end_date=2025-01-31"
```

#### Full Flow:
1. Use agents to generate AI completions
2. Usage tracked in `usage_logs` table
3. Run monthly invoice generation (manually or via cron):
   ```python
   from app.services.usage_service import usage_service
   from datetime import datetime

   # Generate invoices for January 2025
   await usage_service.generate_monthly_invoices(month=1, year=2025, db=db)
   ```
4. User's credits deducted first
5. Remaining balance charged to card
6. Invoice sent via Stripe

---

### Scenario 9: Creator Earnings (Stripe Connect)

**Test**: Agent creators can receive payouts.

#### Setup Creator Account:
```bash
# Generate Connect onboarding link
curl -X POST -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  http://localhost:8000/api/billing/connect
```

#### Full Flow:
1. Creator clicks "Connect Stripe" in dashboard
2. Completes Stripe Express onboarding
3. `creator_stripe_account_id` saved to user
4. When their agent is purchased:
   - Transaction created with 90/10 split
   - Payout automatically created to creator's account
5. View earnings:
   ```bash
   curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
     "http://localhost:8000/api/billing/earnings?start_date=2025-01-01&end_date=2025-01-31"
   ```

---

### Scenario 10: Subscription Cancellation

**Test**: User can cancel premium subscription.

```bash
# Cancel at period end
curl -X POST -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  "http://localhost:8000/api/billing/cancel?at_period_end=true"

# Immediate cancellation
curl -X POST -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  "http://localhost:8000/api/billing/cancel?at_period_end=false"
```

**Expected**:
- `at_period_end=true`: Subscription ends at billing period end
- `at_period_end=false`: Immediate downgrade to free tier

---

## Stripe Test Cards

Use these test cards during checkout:

### Successful Payments
- **Success**: `4242 4242 4242 4242`
- **3D Secure Required**: `4000 0025 0000 3155`

### Failed Payments
- **Generic Decline**: `4000 0000 0000 0002`
- **Insufficient Funds**: `4000 0000 0000 9995`
- **Lost Card**: `4000 0000 0000 9987`
- **Stolen Card**: `4000 0000 0000 9979`

For all cards:
- **Expiry**: Any future date (e.g., 12/25)
- **CVC**: Any 3 digits (e.g., 123)
- **ZIP**: Any 5 digits (e.g., 12345)

---

## Webhook Events Reference

The application handles these Stripe webhook events:

### Checkout Events
- `checkout.session.completed`: Payment successful, provision service
  - Premium subscription: Upgrade user to "pro" tier
  - Credit purchase: Add credits to balance
  - Agent purchase: Add to library
  - Deploy slot: Increment allowed deploys

### Subscription Events
- `customer.subscription.created`: New subscription started
- `customer.subscription.updated`: Subscription modified
- `customer.subscription.deleted`: Subscription cancelled
  - Downgrade user to "free" tier
  - Remove agent from library (if agent subscription)

### Invoice Events
- `invoice.payment_succeeded`: Recurring payment successful
  - Mark usage logs as paid
- `invoice.payment_failed`: Payment failed
  - Notify user
  - Consider suspending service

### Payment Events
- `payment_intent.succeeded`: One-time payment successful

---

## Troubleshooting

### Webhook Not Received

1. **Check Stripe CLI is running**:
   ```bash
   stripe listen --forward-to http://localhost:8000/api/webhooks/stripe
   ```

2. **Verify webhook secret in .env**:
   - Must match secret from Stripe CLI output
   - Should start with `whsec_`

3. **Check application logs**:
   ```bash
   # Look for webhook processing
   tail -f orchestrator/app.log
   ```

### Payment Not Processing

1. **Verify Stripe keys are test keys** (start with `sk_test_` and `pk_test_`)
2. **Check CORS settings** if using frontend
3. **Verify user has `stripe_customer_id`**:
   ```sql
   SELECT id, email, stripe_customer_id FROM users WHERE email = 'user@example.com';
   ```

### Database Errors

1. **Run migrations**:
   ```bash
   cd orchestrator
   python -m alembic upgrade head
   ```

2. **Check for missing columns**:
   ```sql
   \d users  -- PostgreSQL
   DESCRIBE users;  -- MySQL
   ```

### Subscription Tier Not Updating

1. **Check webhook was received**:
   - Look for "Handled checkout.session.completed" in logs
2. **Verify subscription_id in database**:
   ```sql
   SELECT id, email, subscription_tier, stripe_subscription_id
   FROM users
   WHERE email = 'user@example.com';
   ```
3. **Manually update if needed** (for testing):
   ```sql
   UPDATE users
   SET subscription_tier = 'pro', stripe_subscription_id = 'sub_xxxxx'
   WHERE email = 'user@example.com';
   ```

---

## Production Deployment

Before going live:

### 1. Switch to Live Keys
```bash
# Replace test keys with live keys
STRIPE_SECRET_KEY=sk_live_your_live_secret_key
STRIPE_PUBLISHABLE_KEY=pk_live_your_live_publishable_key
```

### 2. Create Live Products
- Recreate all products in live mode
- Update `STRIPE_PREMIUM_PRICE_ID` with live price ID

### 3. Configure Production Webhooks
1. Go to https://dashboard.stripe.com/webhooks
2. Add endpoint: `https://yourdomain.com/api/webhooks/stripe`
3. Select events to listen for:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
   - `payment_intent.succeeded`
4. Copy webhook signing secret to `.env`:
   ```bash
   STRIPE_WEBHOOK_SECRET=whsec_your_production_secret
   ```

### 4. Enable Stripe Connect (for creator payouts)
1. Go to https://dashboard.stripe.com/settings/applications
2. Enable Stripe Connect
3. Copy Client ID to `.env`:
   ```bash
   STRIPE_CONNECT_CLIENT_ID=ca_your_connect_client_id
   ```

### 5. Test in Production
- Use real card for test purchase
- Verify webhooks arrive
- Check all flows end-to-end
- Monitor Stripe Dashboard for errors

---

## Monitoring & Analytics

### Stripe Dashboard
- **Payments**: https://dashboard.stripe.com/payments
- **Subscriptions**: https://dashboard.stripe.com/subscriptions
- **Customers**: https://dashboard.stripe.com/customers
- **Webhooks**: https://dashboard.stripe.com/webhooks
- **Logs**: https://dashboard.stripe.com/logs

### Database Queries

#### Revenue Analytics
```sql
-- Total revenue
SELECT SUM(amount_total) / 100.0 AS total_revenue_usd
FROM marketplace_transactions;

-- Revenue by month
SELECT DATE_TRUNC('month', created_at) AS month,
       SUM(amount_total) / 100.0 AS revenue_usd
FROM marketplace_transactions
GROUP BY month
ORDER BY month DESC;

-- Top earning creators
SELECT u.username, SUM(mt.amount_creator) / 100.0 AS earnings_usd
FROM marketplace_transactions mt
JOIN users u ON mt.creator_id = u.id
GROUP BY u.username
ORDER BY earnings_usd DESC
LIMIT 10;
```

#### Subscription Analytics
```sql
-- Active subscriptions by tier
SELECT subscription_tier, COUNT(*) AS users
FROM users
GROUP BY subscription_tier;

-- Monthly recurring revenue (MRR)
SELECT COUNT(*) * 5.00 AS mrr_usd
FROM users
WHERE subscription_tier = 'pro';
```

#### Usage Analytics
```sql
-- Total usage costs
SELECT SUM(cost_total) / 100.0 AS total_cost_usd
FROM usage_logs;

-- Usage by model
SELECT model,
       COUNT(*) AS requests,
       SUM(tokens_input + tokens_output) AS total_tokens,
       SUM(cost_total) / 100.0 AS cost_usd
FROM usage_logs
GROUP BY model
ORDER BY cost_usd DESC;
```

---

## Support & Resources

- **Stripe Documentation**: https://stripe.com/docs
- **Stripe API Reference**: https://stripe.com/docs/api
- **Stripe Testing**: https://stripe.com/docs/testing
- **Stripe CLI**: https://stripe.com/docs/stripe-cli
- **Stripe Connect**: https://stripe.com/docs/connect

---

## Summary

This testing guide covers all major Stripe integration features:
- ✅ User registration with Stripe customer creation
- ✅ Premium subscriptions ($5/month)
- ✅ Credit purchases ($5/$10/$50)
- ✅ Marketplace agent purchases (monthly & one-time)
- ✅ Project & deploy limit enforcement
- ✅ Usage tracking & monthly billing
- ✅ Creator payouts (90/10 revenue split)
- ✅ Webhook handling for all event types

Follow this guide to ensure your Stripe integration works correctly before deploying to production.
