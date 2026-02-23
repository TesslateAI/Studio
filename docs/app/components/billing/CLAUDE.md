# Billing Components - AI Agent Context

## Quick Reference

### 4-Tier System
| Tier | Price | Projects | Deploys | Credits | BYOK |
|------|-------|----------|---------|---------|------|
| Free | $0 | 3 | 1 | 5/day | No |
| Basic | $20 | 7 | 3 | 500/mo | No |
| Pro | $49 | 15 | 5 | 2,000/mo | Yes |
| Ultra | $149 | 40 | 20 | 8,000/mo | Yes |

### Credit System
- **1 credit = $0.01 USD**
- **Bundled credits**: Monthly allowance, reset on billing date
- **Purchased credits**: Never expire, used after bundled

### Credit Packages
- Small: 500 credits / $5
- Medium: 2,500 credits / $25
- Large: 10,000 credits / $100
- Team: 50,000 credits / $500

---

## Component Notes

### SubscriptionPlans.tsx (Deleted)
`SubscriptionPlans.tsx` has been deleted. Its plan selection functionality is now inline in `BillingSettings.tsx` as a `PlanSelectionModal`.

### CreditsPurchaseModal.tsx
`CreditsPurchaseModal.tsx` renders the credit purchase options (Small, Medium, Large, Team packages). It displays a loading spinner during checkout initiation while the Stripe session is being created.

---

## Adding Usage Gating

**Pattern**: Check limits before allowing action, show upgrade modal if exceeded.

```typescript
const performAction = async () => {
  // 1. Fetch current subscription
  const subscription = await billingApi.getSubscription();

  // 2. Check limit
  if (subscription.feature_used >= subscription.feature_limit) {
    setShowUpgradeModal(true);
    return;
  }

  // 3. Check credits
  const credits = await billingApi.getCreditsBalance();
  if (credits.total_credits < COST) {
    setShowCreditsPurchase(true);
    return;
  }

  // 4. Perform action
  await doAction();
};
```

---

## Stripe Checkout Flow

### 1. Create Checkout Session (Backend)

```python
# orchestrator/app/routers/billing.py
@router.post("/subscribe")
async def create_subscription_checkout(
    request: SubscribeRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Map tier to Stripe price ID
    price_id = {
        'basic': settings.stripe_basic_price_id,
        'pro': settings.stripe_pro_price_id,
        'ultra': settings.stripe_ultra_price_id,
    }.get(request.tier)

    session = stripe.checkout.Session.create(
        mode='subscription',
        line_items=[{'price': price_id, 'quantity': 1}],
        success_url=f'{settings.frontend_url}/settings/billing?success=true',
        cancel_url=f'{settings.frontend_url}/settings/billing',
        client_reference_id=str(user.id),
        metadata={'user_id': str(user.id), 'tier': request.tier},
    )

    return {'session_id': session.id, 'url': session.url}
```

### 2. Redirect to Stripe (Frontend)

```typescript
const handleUpgrade = async (tier: string) => {
  try {
    setLoading(true);
    const { url } = await billingApi.subscribe(tier);
    window.location.href = url;
  } catch (error) {
    toast.error('Failed to start checkout');
  } finally {
    setLoading(false);
  }
};
```

### 3. Handle Success (Frontend)

```typescript
// BillingSettings.tsx
useEffect(() => {
  const params = new URLSearchParams(location.search);

  if (params.get('success') === 'true') {
    toast.success('Subscription updated!');
    navigate('/settings/billing', { replace: true });
    loadSubscription();  // Refresh data
  }
}, [location.search]);
```

### 4. Webhook Handler (Backend)

```python
# orchestrator/app/routers/webhooks.py
@router.post("/stripe")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get('stripe-signature')

    event = stripe.Webhook.construct_event(
        payload, sig, settings.stripe_webhook_secret
    )

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session['metadata']['user_id']
        tier = session['metadata']['tier']

        # Update subscription
        user = await db.get(User, user_id)
        user.subscription_tier = tier
        user.bundled_credits = TIER_CREDITS[tier]
        user.credits_reset_date = datetime.utcnow() + timedelta(days=30)
        await db.commit()

    return {'status': 'success'}
```

---

## Credit Purchase Flow

### Frontend

```typescript
const handleCreditsPurchase = async (packageId: 'small' | 'medium' | 'large' | 'team') => {
  try {
    const { url } = await billingApi.purchaseCredits(packageId);
    window.location.href = url;
  } catch (error) {
    toast.error('Failed to purchase credits');
  }
};
```

### Backend Webhook

```python
if event['type'] == 'checkout.session.completed':
    session = event['data']['object']

    if session['metadata'].get('type') == 'credit_purchase':
        # Check idempotency
        payment_intent = session['payment_intent']
        existing = await db.execute(
            select(CreditPurchase)
            .where(CreditPurchase.stripe_payment_intent == payment_intent)
        )
        if existing.scalar_one_or_none():
            return  # Already processed

        # Add credits (to purchased_credits, NOT bundled_credits)
        user.purchased_credits += credits_amount

        # Record purchase
        purchase = CreditPurchase(
            user_id=user.id,
            credits_amount=credits_amount,
            amount_cents=amount_cents,
            stripe_payment_intent=payment_intent,
            status='completed',
        )
        db.add(purchase)
        await db.commit()
```

---

## Testing Billing Components

### Mock Stripe Responses

```typescript
jest.mock('../../lib/api', () => ({
  billingApi: {
    getSubscription: jest.fn().mockResolvedValue({
      tier: 'basic',
      max_projects: 5,
      max_deploys: 2,
      bundled_credits: 800,
      purchased_credits: 200,
      total_credits: 1000,
      byok_enabled: false,
    }),
    getCreditsBalance: jest.fn().mockResolvedValue({
      bundled_credits: 800,
      purchased_credits: 200,
      total_credits: 1000,
    }),
    getCreditsStatus: jest.fn().mockResolvedValue({
      total_credits: 1000,
      is_low: false,
      is_empty: false,
      threshold: 200,
    }),
  },
}));

test('shows upgrade modal when limit reached', async () => {
  billingApi.getSubscription.mockResolvedValue({
    tier: 'basic',
    max_projects: 5,
    projects_count: 5,  // At limit
  });

  render(<CreateProjectButton />);
  fireEvent.click(screen.getByText('New Project'));

  await waitFor(() => {
    expect(screen.getByText(/upgrade/i)).toBeInTheDocument();
  });
});
```

### Test Stripe Redirect

```typescript
test('redirects to Stripe checkout', async () => {
  delete window.location;
  window.location = { href: '' } as Location;

  billingApi.subscribe.mockResolvedValue({
    url: 'https://checkout.stripe.com/session-123',
  });

  render(<UpgradeModal />);
  fireEvent.click(screen.getByText('Upgrade to Pro'));

  await waitFor(() => {
    expect(window.location.href).toBe('https://checkout.stripe.com/session-123');
  });
});
```

---

## Debugging Billing Issues

### Subscription Not Updating After Checkout

**Check**:
1. Stripe webhook endpoint configured: `POST /api/webhooks/stripe`
2. Webhook secret matches `STRIPE_WEBHOOK_SECRET`
3. Backend receives webhook event (check logs)
4. Database update succeeds

**Debug**:
```python
# Add logging to webhook handler
logger.info(f"[Stripe] Received event: {event['type']}")
logger.info(f"[Stripe] Session metadata: {session['metadata']}")
logger.info(f"[Stripe] User ID: {user_id}")
```

### Credits Not Updating

**Check**:
1. Correct credit type updated (bundled vs purchased)
2. Idempotency check not blocking
3. Frontend refreshes after purchase

**Debug**:
```typescript
const debugCredits = async () => {
  const before = await billingApi.getCreditsBalance();
  console.log('[Billing] Credits before:', before);

  await performAction();

  const after = await billingApi.getCreditsBalance();
  console.log('[Billing] Credits after:', after);
};
```

### Upgrade Modal Not Showing

**Check**:
1. Limit check logic is correct
2. Modal state managed properly
3. Subscription data fetched successfully

**Debug**:
```typescript
const checkLimit = async () => {
  const sub = await billingApi.getSubscription();
  console.log('[Billing] Subscription:', sub);
  console.log('[Billing] Projects:', sub.projects_count, '/', sub.max_projects);
  console.log('[Billing] Should show modal:', sub.projects_count >= sub.max_projects);
};
```

### Low Balance Warning Not Showing

**Check**:
1. `is_low` field from `getCreditsStatus()` API
2. Threshold calculation: `totalCredits <= 0.20 * monthlyAllowance`

**Debug**:
```typescript
const status = await billingApi.getCreditsStatus();
console.log('[Billing] Credit status:', status);
console.log('[Billing] Is low:', status.is_low);
console.log('[Billing] Threshold:', status.threshold);
```

---

## Key API Endpoints

```typescript
// Subscription
GET  /api/billing/subscription     → SubscriptionResponse
POST /api/billing/subscribe        → { session_id, url }
POST /api/billing/cancel           → { success, message }
POST /api/billing/renew            → { success, message }
GET  /api/billing/portal           → { url }

// Credits
GET  /api/billing/credits          → CreditBalanceResponse
GET  /api/billing/credits/status   → CreditStatusResponse
POST /api/billing/credits/purchase → { session_id, url }
GET  /api/billing/credits/history  → { purchases: CreditPurchase[] }

// Usage
GET  /api/billing/usage            → UsageSummaryResponse
GET  /api/billing/usage/logs       → { logs: UsageLog[] }

// Config (public)
GET  /api/billing/config           → BillingConfig
```

---

## Environment Variables

Required for Stripe integration:

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

---

## Test Cards

Use Stripe test mode with these cards:

| Card Number | Result |
|-------------|--------|
| `4242 4242 4242 4242` | Succeeds |
| `4000 0000 0000 0002` | Declines |
| `4000 0000 0000 3220` | Requires 3D Secure |

---

**Remember**: Always test billing flows with Stripe test mode before production.
