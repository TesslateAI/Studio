# Billing Components - AI Agent Context

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

  // 3. Perform action
  await doAction();

  // 4. Increment usage (backend handles this)
};
```

## Stripe Checkout Flow

### 1. Create Checkout Session (Backend)

```python
# orchestrator/app/routers/billing.py
@router.post("/checkout/subscription")
async def create_subscription_checkout(tier: str):
    stripe.api_key = settings.stripe_secret_key

    session = stripe.checkout.Session.create(
        mode='subscription',
        line_items=[{
            'price': get_price_id(tier),
            'quantity': 1,
        }],
        success_url=f'{settings.frontend_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}',
        cancel_url=f'{settings.frontend_url}/billing',
        client_reference_id=str(user.id),
    )

    return {'checkout_url': session.url}
```

### 2. Redirect to Stripe (Frontend)

```typescript
const handleUpgrade = async () => {
  try {
    setLoading(true);
    const { checkout_url } = await billingApi.createCheckoutSession('pro');
    window.location.href = checkout_url;
  } catch (error) {
    toast.error('Failed to start checkout');
  } finally {
    setLoading(false);
  }
};
```

### 3. Handle Success (Frontend)

```typescript
// BillingSuccessPage.tsx
const BillingSuccess = () => {
  const [searchParams] = useSearchParams();
  const sessionId = searchParams.get('session_id');

  useEffect(() => {
    if (sessionId) {
      // Poll backend to confirm subscription updated
      const checkStatus = async () => {
        const sub = await billingApi.getSubscription();
        if (sub.tier === 'pro') {
          toast.success('Upgraded to Pro!');
          navigate('/dashboard');
        }
      };

      const interval = setInterval(checkStatus, 2000);
      setTimeout(() => clearInterval(interval), 30000);  // Stop after 30s

      return () => clearInterval(interval);
    }
  }, [sessionId]);

  return <div>Processing your subscription...</div>;
};
```

### 4. Webhook Handler (Backend)

```python
# orchestrator/app/routers/billing.py
@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')

    event = stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session['client_reference_id']

        # Update user subscription
        user = await db.get(User, user_id)
        user.subscription_tier = 'pro'
        user.subscription_status = 'active'
        await db.commit()

    return {'status': 'success'}
```

## Testing Billing Components

### Mock Stripe Responses

```typescript
// Mock billingApi for tests
jest.mock('../../lib/api', () => ({
  billingApi: {
    getSubscription: jest.fn().mockResolvedValue({
      tier: 'free',
      max_projects: 3,
      projects_count: 2,
      max_deploys: 5,
      deployments_used: 3,
    }),
    getCreditsBalance: jest.fn().mockResolvedValue({
      balance_usd: 10.50,
    }),
  }
}));

test('shows upgrade modal when limit reached', async () => {
  billingApi.getSubscription.mockResolvedValue({
    tier: 'free',
    max_projects: 3,
    projects_count: 3,  // At limit
  });

  render(<CreateProjectButton />);

  fireEvent.click(screen.getByText('New Project'));

  await waitFor(() => {
    expect(screen.getByText(/upgrade to pro/i)).toBeInTheDocument();
  });
});
```

### Test Stripe Redirect

```typescript
test('redirects to Stripe checkout', async () => {
  delete window.location;  // Allow mocking
  window.location = { href: '' };

  billingApi.createCheckoutSession.mockResolvedValue({
    checkout_url: 'https://checkout.stripe.com/session-123'
  });

  render(<UpgradeModal />);
  fireEvent.click(screen.getByText('Upgrade to Pro'));

  await waitFor(() => {
    expect(window.location.href).toBe('https://checkout.stripe.com/session-123');
  });
});
```

## Debugging Billing Issues

### Subscription Not Updating After Checkout

**Check**:
1. Stripe webhook endpoint configured
2. Webhook secret matches
3. Backend receives webhook event
4. Database update succeeds

**Debug**:
```python
# Add logging to webhook handler
logger.info(f"[Stripe] Received event: {event['type']}")
logger.info(f"[Stripe] Session: {session}")
logger.info(f"[Stripe] User ID: {user_id}")
```

### Credits Not Deducting

**Check**:
1. Backend deducts credits on action
2. Frontend refreshes balance after action
3. Credit balance returned correctly from API

**Debug**:
```typescript
const performAction = async () => {
  console.log('[Billing] Credits before:', await billingApi.getCreditsBalance());
  await api.performAction();
  console.log('[Billing] Credits after:', await billingApi.getCreditsBalance());
};
```

### Upgrade Modal Not Showing

**Check**:
1. Limit check logic correct
2. Modal state managed properly
3. Subscription data fetched

**Debug**:
```typescript
const checkLimit = async () => {
  const sub = await billingApi.getSubscription();
  console.log('[Billing] Subscription:', sub);
  console.log('[Billing] Projects:', sub.projects_count, '/', sub.max_projects);

  if (sub.projects_count >= sub.max_projects) {
    console.log('[Billing] Showing upgrade modal');
    setShowUpgradeModal(true);
  }
};
```

---

**Remember**: Always test billing flows with Stripe test mode before production. Use test cards like `4242 4242 4242 4242`.
