# Billing Pages

## Overview

All billing functionality is consolidated in `/settings/billing`. The billing system uses a **4-tier subscription model** with a **dual credit system**.

---

## Billing Settings Page (`BillingSettings.tsx`)

**File**: `app/src/pages/settings/BillingSettings.tsx`
**Route**: `/settings/billing`

### Purpose

Central hub for subscription management, credit balance, and billing history. This is the only billing-related page in the application.

### Sections

1. **Current Subscription**
   - Tier badge (Free, Basic, Pro, Ultra)
   - Price and billing period
   - Renewal/cancellation date
   - Manage subscription button → Stripe Customer Portal

2. **Credit Balance**
   - Bundled credits (monthly allowance)
   - Purchased credits (never expire)
   - Total credits
   - Credits reset date
   - Purchase credits button

3. **Usage This Period**
   - AI requests count
   - Tokens used
   - Cost in credits
   - Usage by model/agent breakdown

4. **Subscription Tiers**
   - All 4 tiers as comparison cards
   - Current plan indicator
   - Upgrade buttons

5. **Recent Transactions**
   - Credit purchases
   - Subscription payments
   - Date, amount, status

### State Management

```typescript
const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
const [credits, setCredits] = useState<CreditBalanceResponse | null>(null);
const [creditStatus, setCreditStatus] = useState<CreditStatusResponse | null>(null);
const [transactions, setTransactions] = useState<Transaction[]>([]);
const [creditHistory, setCreditHistory] = useState<CreditPurchase[]>([]);
const [usage, setUsage] = useState<UsageSummaryResponse | null>(null);
const [loading, setLoading] = useState(true);
const [showCreditsPurchase, setShowCreditsPurchase] = useState(false);
```

### Data Loading

```typescript
useEffect(() => {
  loadData();
}, []);

const loadData = async () => {
  try {
    const [subRes, creditsRes, statusRes, usageRes, transRes, historyRes] = await Promise.all([
      billingApi.getSubscription(),
      billingApi.getCreditsBalance(),
      billingApi.getCreditsStatus(),
      billingApi.getUsage(),
      billingApi.getTransactions(10, 0),
      billingApi.getCreditsHistory(10, 0),
    ]);

    setSubscription(subRes);
    setCredits(creditsRes);
    setCreditStatus(statusRes);
    setUsage(usageRes);
    setTransactions(transRes.transactions);
    setCreditHistory(historyRes.purchases);
  } catch (error) {
    toast.error('Failed to load billing data');
  } finally {
    setLoading(false);
  }
};
```

### Subscription Actions

The billing page includes a **monthly/annual billing toggle**. When subscribing, the `billing_interval` parameter (`'monthly'` | `'annual'`) is passed to the subscribe endpoint to select the corresponding Stripe price.

```typescript
// Upgrade subscription
const handleUpgrade = async (tier: string, billingInterval: 'monthly' | 'annual' = 'monthly') => {
  try {
    const { url } = await billingApi.subscribe(tier, billingInterval);
    window.location.href = url;  // Redirect to Stripe Checkout
  } catch (error) {
    toast.error('Failed to initiate upgrade');
  }
};

// Cancel subscription
const handleCancel = async () => {
  if (!confirm('Cancel subscription? Access continues until end of billing period.')) {
    return;
  }

  try {
    await billingApi.cancelSubscription(true);  // at_period_end
    toast.success('Subscription will cancel at end of period');
    loadData();
  } catch (error) {
    toast.error('Failed to cancel subscription');
  }
};

// Renew cancelled subscription
const handleRenew = async () => {
  try {
    await billingApi.renewSubscription();
    toast.success('Subscription renewed!');
    loadData();
  } catch (error) {
    toast.error('Failed to renew subscription');
  }
};

// Open Stripe Customer Portal
const handleManageSubscription = async () => {
  try {
    const { url } = await billingApi.getCustomerPortal();
    window.location.href = url;
  } catch (error) {
    toast.error('Failed to open billing portal');
  }
};
```

### Success Redirect Handling

```typescript
useEffect(() => {
  const params = new URLSearchParams(location.search);

  if (params.get('success') === 'true') {
    toast.success('Payment successful!');
    navigate('/settings/billing', { replace: true });
    loadData();  // Refresh to show updated subscription
  }
}, [location.search]);
```

---

## Subscription Tiers Display

> **Note**: The subscription tiers are now rendered via an inline `PlanSelectionModal` component within `BillingSettings.tsx`, not a separate `SubscriptionPlans` component. The modal is embedded directly in the billing page and displays all four tiers as comparison cards with upgrade/downgrade actions.

### Tier Configuration

```typescript
const TIERS = [
  {
    id: 'free',
    name: 'Free',
    price: 0,
    features: [
      '3 projects',
      '1 deployment',
      '5 credits/day',
    ],
  },
  {
    id: 'basic',
    name: 'Basic',
    price: 20,
    features: [
      '7 projects',
      '3 deployments',
      '500 credits/month',
    ],
  },
  {
    id: 'pro',
    name: 'Pro',
    price: 49,
    popular: true,
    features: [
      '15 projects',
      '5 deployments',
      '2,000 credits/month',
      'Bring Your Own API Key',
    ],
  },
  {
    id: 'ultra',
    name: 'Ultra',
    price: 149,
    features: [
      '40 projects',
      '20 deployments',
      '8,000 credits/month',
      'Bring Your Own API Key',
      'Priority support',
    ],
  },
];
```

### Tier Card Component

```typescript
interface TierCardProps {
  tier: Tier;
  isCurrentTier: boolean;
  onSelect: () => void;
}

function TierCard({ tier, isCurrentTier, onSelect }: TierCardProps) {
  return (
    <div className={cn(
      'rounded-xl border p-6',
      isCurrentTier && 'border-primary ring-2 ring-primary/20',
      tier.popular && 'relative'
    )}>
      {tier.popular && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-primary text-white px-3 py-1 rounded-full text-sm">
          Most Popular
        </div>
      )}

      <h3 className="text-xl font-semibold">{tier.name}</h3>

      <div className="mt-4">
        <span className="text-4xl font-bold">${tier.price}</span>
        <span className="text-muted-foreground">/month</span>
      </div>

      <ul className="mt-6 space-y-3">
        {tier.features.map((feature, i) => (
          <li key={i} className="flex items-center gap-2">
            <Check className="h-5 w-5 text-green-500" />
            <span>{feature}</span>
          </li>
        ))}
      </ul>

      <button
        onClick={onSelect}
        disabled={isCurrentTier}
        className={cn(
          'mt-6 w-full py-2 rounded-lg',
          isCurrentTier
            ? 'bg-muted text-muted-foreground'
            : 'bg-primary text-white hover:bg-primary/90'
        )}
      >
        {isCurrentTier ? 'Current Plan' : 'Upgrade'}
      </button>
    </div>
  );
}
```

---

## Credit Balance Display

```typescript
function CreditBalanceCard({ credits, status, onPurchase }: CreditBalanceProps) {
  return (
    <div className="rounded-xl border p-6">
      <h3 className="text-lg font-semibold">Credit Balance</h3>

      <div className="mt-4 space-y-4">
        {/* Total Credits */}
        <div className="flex items-center justify-between">
          <span>Total Credits</span>
          <span className={cn(
            'text-2xl font-bold',
            status.is_empty && 'text-red-500',
            status.is_low && !status.is_empty && 'text-yellow-500',
            !status.is_low && 'text-green-500'
          )}>
            {credits.total_credits.toLocaleString()}
          </span>
        </div>

        {/* Breakdown */}
        <div className="text-sm text-muted-foreground space-y-1">
          <div className="flex justify-between">
            <span>Bundled (monthly)</span>
            <span>{credits.bundled_credits.toLocaleString()}</span>
          </div>
          <div className="flex justify-between">
            <span>Purchased</span>
            <span>{credits.purchased_credits.toLocaleString()}</span>
          </div>
        </div>

        {/* Reset Date */}
        <div className="text-sm text-muted-foreground">
          Bundled credits reset: {formatDate(credits.credits_reset_date)}
        </div>

        {/* Low Balance Warning */}
        {status.is_low && (
          <div className={cn(
            'p-3 rounded-lg text-sm',
            status.is_empty ? 'bg-red-100 text-red-800' : 'bg-yellow-100 text-yellow-800'
          )}>
            {status.is_empty
              ? 'You have no credits remaining. Purchase more to continue using AI features.'
              : 'Your credit balance is running low. Consider purchasing more credits.'
            }
          </div>
        )}

        {/* Purchase Button */}
        <button
          onClick={onPurchase}
          className="w-full py-2 bg-primary text-white rounded-lg"
        >
          Purchase Credits
        </button>
      </div>
    </div>
  );
}
```

---

## Usage Display

```typescript
function UsageCard({ usage }: { usage: UsageSummaryResponse }) {
  return (
    <div className="rounded-xl border p-6">
      <h3 className="text-lg font-semibold">Usage This Period</h3>

      <div className="mt-4 grid grid-cols-2 gap-4">
        <div>
          <div className="text-2xl font-bold">{usage.total_requests}</div>
          <div className="text-sm text-muted-foreground">AI Requests</div>
        </div>
        <div>
          <div className="text-2xl font-bold">
            {(usage.total_tokens_input + usage.total_tokens_output).toLocaleString()}
          </div>
          <div className="text-sm text-muted-foreground">Tokens Used</div>
        </div>
        <div>
          <div className="text-2xl font-bold">{usage.total_cost_cents}</div>
          <div className="text-sm text-muted-foreground">Credits Used</div>
        </div>
        <div>
          <div className="text-2xl font-bold">${(usage.total_cost_cents / 100).toFixed(2)}</div>
          <div className="text-sm text-muted-foreground">Cost (USD)</div>
        </div>
      </div>

      {/* By Model Breakdown */}
      {Object.keys(usage.by_model).length > 0 && (
        <div className="mt-6">
          <h4 className="text-sm font-medium mb-2">By Model</h4>
          <div className="space-y-2">
            {Object.entries(usage.by_model).map(([model, data]) => (
              <div key={model} className="flex justify-between text-sm">
                <span className="truncate">{model}</span>
                <span>{data.cost_cents} credits</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

---

## Transaction History

```typescript
function TransactionsTable({ transactions }: { transactions: Transaction[] }) {
  return (
    <div className="rounded-xl border overflow-hidden">
      <table className="w-full">
        <thead className="bg-muted/50">
          <tr>
            <th className="px-4 py-3 text-left text-sm font-medium">Date</th>
            <th className="px-4 py-3 text-left text-sm font-medium">Type</th>
            <th className="px-4 py-3 text-left text-sm font-medium">Amount</th>
            <th className="px-4 py-3 text-left text-sm font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((txn) => (
            <tr key={txn.id} className="border-t">
              <td className="px-4 py-3 text-sm">
                {formatDate(txn.created_at)}
              </td>
              <td className="px-4 py-3 text-sm capitalize">
                {txn.type.replace('_', ' ')}
              </td>
              <td className="px-4 py-3 text-sm">
                ${(txn.amount_cents / 100).toFixed(2)}
              </td>
              <td className="px-4 py-3">
                <span className={cn(
                  'px-2 py-1 rounded-full text-xs',
                  txn.status === 'completed' && 'bg-green-100 text-green-800',
                  txn.status === 'pending' && 'bg-yellow-100 text-yellow-800',
                  txn.status === 'failed' && 'bg-red-100 text-red-800'
                )}>
                  {txn.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

---

## API Endpoints Used

```typescript
// Subscription
GET  /api/billing/subscription     → Subscription status and limits
POST /api/billing/subscribe        → Create Stripe checkout for upgrade
POST /api/billing/cancel           → Cancel subscription
POST /api/billing/renew            → Renew cancelled subscription
GET  /api/billing/portal           → Stripe Customer Portal URL

// Credits
GET  /api/billing/credits          → Credit balance breakdown
GET  /api/billing/credits/status   → Low balance status
POST /api/billing/credits/purchase → Create Stripe checkout for credits
GET  /api/billing/credits/history  → Purchase history

// Usage
GET  /api/billing/usage            → Usage summary
GET  /api/billing/usage/logs       → Detailed usage logs

// Transactions
GET  /api/billing/transactions     → Combined transaction history

// Config (public)
GET  /api/billing/config           → Billing configuration (tiers, packages)
```

---

## Related Files

- **Settings Layout**: `app/src/layouts/SettingsLayout.tsx`
- **Billing Components**: `app/src/components/billing/`
- **API Client**: `app/src/lib/api.ts` → `billingApi`
- **Types**: `app/src/types/billing.ts`
- **Backend Router**: `orchestrator/app/routers/billing.py`

---

## Best Practices

### 1. Always Refresh After Stripe Redirect

```typescript
useEffect(() => {
  const params = new URLSearchParams(location.search);
  if (params.get('success') === 'true') {
    loadData();  // Refresh to get updated subscription
    navigate(location.pathname, { replace: true });  // Remove query params
  }
}, [location.search]);
```

### 2. Show Loading States

```typescript
if (loading) {
  return <BillingSettingsSkeleton />;
}
```

### 3. Handle Errors Gracefully

```typescript
try {
  await billingApi.subscribe(tier);
} catch (error) {
  if (error.response?.status === 400) {
    toast.error(error.response.data.detail);
  } else {
    toast.error('Failed to start checkout. Please try again.');
  }
}
```

### 4. Cache Billing Config

```typescript
// Billing config rarely changes, cache it
const [config, setConfig] = useState(() => {
  const cached = sessionStorage.getItem('billing_config');
  return cached ? JSON.parse(cached) : null;
});

useEffect(() => {
  if (!config) {
    billingApi.getConfig().then(data => {
      setConfig(data);
      sessionStorage.setItem('billing_config', JSON.stringify(data));
    });
  }
}, [config]);
```

---

## Troubleshooting

**Issue**: Subscription not updating after checkout
- Check Stripe webhook events in dashboard
- Verify webhook endpoint is reachable
- Check backend logs for webhook processing

**Issue**: Credits not deducting
- Backend deducts credits during AI usage
- Frontend should refresh balance after AI operations
- Check `credits_reset_date` for bundled credit resets

**Issue**: Upgrade button not working
- Verify Stripe price IDs are configured
- Check `STRIPE_BASIC_PRICE_ID`, `STRIPE_PRO_PRICE_ID`, `STRIPE_ULTRA_PRICE_ID` env vars
- Check browser console for errors
