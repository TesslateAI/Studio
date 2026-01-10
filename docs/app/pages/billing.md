# Billing Pages

## Billing Dashboard (`BillingDashboard.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/billing/BillingDashboard.tsx`
**Route**: `/billing`

### Purpose
Central hub for subscription management, credit balance, and billing history.

### Features
- **Current Subscription**: Tier, price, renewal date
- **Credit Balance**: Available credits
- **Recent Transactions**: Subscription payments
- **Credit History**: Credit purchases
- **Quick Actions**: Upgrade, cancel, manage subscription

### State
```typescript
const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
const [credits, setCredits] = useState<CreditBalanceResponse | null>(null);
const [transactions, setTransactions] = useState<Transaction[]>([]);
const [creditHistory, setCreditHistory] = useState<CreditPurchase[]>([]);
const [loading, setLoading] = useState(true);
const [cancelling, setCancelling] = useState(false);
```

### Data Flow
```typescript
useEffect(() => {
  loadData();
}, []);

const loadData = async () => {
  const [subRes, creditsRes, transRes, historyRes] = await Promise.all([
    billingApi.getSubscription(),
    billingApi.getCreditsBalance(),
    billingApi.getTransactions(10, 0),
    billingApi.getCreditsHistory(10, 0),
  ]);

  setSubscription(subRes);
  setCredits(creditsRes);
  setTransactions(transRes.transactions);
  setCreditHistory(historyRes.purchases);
};
```

### Subscription Actions
```typescript
// Cancel subscription
const handleCancelSubscription = async () => {
  if (!confirm('Cancel subscription? Access continues until end of billing period.')) {
    return;
  }

  try {
    await billingApi.cancelSubscription(true);
    toast.success('Subscription cancelled');
    loadData();
  } catch (error) {
    toast.error('Failed to cancel subscription');
  }
};

// Manage subscription (Stripe portal)
const handleManageSubscription = async () => {
  try {
    const { url } = await billingApi.getCustomerPortal();
    window.location.href = url;
  } catch (error) {
    // Fallback if portal not configured
    if (confirm('Portal not available. Go to Library to manage?')) {
      navigate('/library?tab=subscriptions');
    }
  }
};
```

---

## Subscription Plans (`SubscriptionPlans.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/billing/SubscriptionPlans.tsx`
**Route**: `/billing/plans`

### Purpose
Compare subscription tiers and upgrade/downgrade.

### Features
- **Plan Comparison**: Free, Pro, Enterprise
- **Feature List**: What's included in each tier
- **Pricing**: Monthly/yearly toggle
- **Current Plan Badge**: Highlight active tier
- **Upgrade/Downgrade Buttons**: Stripe checkout

### State
```typescript
const [plans, setPlans] = useState<Plan[]>([]);
const [currentTier, setCurrentTier] = useState<string>('free');
const [billingCycle, setBillingCycle] = useState<'monthly' | 'yearly'>('monthly');
```

### Data Flow
```typescript
useEffect(() => {
  loadPlans();
  loadCurrentSubscription();
}, []);

const loadPlans = async () => {
  const data = await billingApi.getPlans();
  setPlans(data.plans);
};

const loadCurrentSubscription = async () => {
  const data = await billingApi.getSubscription();
  setCurrentTier(data.tier);
};
```

### Subscription Flow
```typescript
const handleSelectPlan = async (plan: Plan) => {
  if (plan.tier === currentTier) {
    toast('You are already on this plan');
    return;
  }

  try {
    // Create Stripe checkout session
    const { url } = await billingApi.createCheckoutSession(
      plan.stripe_price_id,
      billingCycle
    );

    // Redirect to Stripe
    window.location.href = url;
  } catch (error) {
    toast.error('Failed to start checkout');
  }
};
```

### Plan Card
```typescript
interface PlanCardProps {
  plan: Plan;
  isCurrentPlan: boolean;
  billingCycle: 'monthly' | 'yearly';
  onSelect: () => void;
}

function PlanCard({ plan, isCurrentPlan, billingCycle, onSelect }: PlanCardProps) {
  const price = billingCycle === 'monthly' ? plan.price_monthly : plan.price_yearly;
  const yearlyDiscount = plan.price_yearly ?
    Math.round((1 - (plan.price_yearly * 12) / (plan.price_monthly * 12)) * 100) : 0;

  return (
    <div className={`plan-card ${isCurrentPlan ? 'current' : ''}`}>
      {isCurrentPlan && <div className="badge">Current Plan</div>}

      <h3>{plan.name}</h3>
      <div className="price">
        <span className="amount">${price}</span>
        <span className="period">/{billingCycle === 'monthly' ? 'mo' : 'yr'}</span>
      </div>

      {billingCycle === 'yearly' && yearlyDiscount > 0 && (
        <div className="discount">Save {yearlyDiscount}%</div>
      )}

      <ul className="features">
        {plan.features.map(feature => (
          <li key={feature}>
            <Check /> {feature}
          </li>
        ))}
      </ul>

      <button
        onClick={onSelect}
        disabled={isCurrentPlan}
      >
        {isCurrentPlan ? 'Current Plan' : 'Select Plan'}
      </button>
    </div>
  );
}
```

---

## Usage Dashboard (`UsageDashboard.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/billing/UsageDashboard.tsx`
**Route**: `/billing/usage`

### Purpose
Track resource usage against subscription limits.

### Features
- **Charts**: Usage over time (Chart.js)
- **Current Usage**: Projects, API calls, storage
- **Limits**: Subscription tier limits
- **Progress Bars**: Visual usage indicators
- **Upgrade Prompts**: When near limits

### State
```typescript
const [usage, setUsage] = useState<UsageData | null>(null);
const [limits, setLimits] = useState<LimitsData | null>(null);
const [chartData, setChartData] = useState<ChartData | null>(null);
```

### Data Flow
```typescript
useEffect(() => {
  loadUsage();
}, []);

const loadUsage = async () => {
  const [usageRes, limitsRes, historyRes] = await Promise.all([
    billingApi.getCurrentUsage(),
    billingApi.getLimits(),
    billingApi.getUsageHistory(30), // Last 30 days
  ]);

  setUsage(usageRes);
  setLimits(limitsRes);

  // Prepare chart data
  setChartData({
    labels: historyRes.map(d => d.date),
    datasets: [
      {
        label: 'API Calls',
        data: historyRes.map(d => d.api_calls),
        borderColor: '#ff6b00',
      },
      {
        label: 'Projects',
        data: historyRes.map(d => d.projects),
        borderColor: '#10b981',
      },
    ],
  });
};
```

### Usage Charts
```typescript
import { Line } from 'react-chartjs-2';

<Line
  data={chartData}
  options={{
    responsive: true,
    plugins: {
      legend: {
        position: 'top',
      },
      title: {
        display: true,
        text: 'Usage Over Time',
      },
    },
  }}
/>
```

### Usage Indicators
```typescript
function UsageIndicator({ label, current, limit }: UsageIndicatorProps) {
  const percentage = (current / limit) * 100;
  const isNearLimit = percentage > 80;
  const isOverLimit = percentage > 100;

  return (
    <div className="usage-indicator">
      <div className="label">
        <span>{label}</span>
        <span>{current} / {limit}</span>
      </div>

      <div className="progress-bar">
        <div
          className={`progress-fill ${isOverLimit ? 'over' : isNearLimit ? 'near' : ''}`}
          style={{ width: `${Math.min(percentage, 100)}%` }}
        />
      </div>

      {isNearLimit && (
        <div className="warning">
          {isOverLimit ? 'Limit exceeded' : 'Near limit'}
        </div>
      )}
    </div>
  );
}

<UsageIndicator
  label="Projects"
  current={usage.projects}
  limit={limits.projects}
/>

<UsageIndicator
  label="API Calls"
  current={usage.api_calls}
  limit={limits.api_calls_per_month}
/>

<UsageIndicator
  label="Storage"
  current={usage.storage_mb}
  limit={limits.storage_mb}
/>
```

---

## Transaction History (`TransactionHistory.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/billing/TransactionHistory.tsx`
**Route**: `/billing/transactions`

### Purpose
View all past payments and credit purchases.

### Features
- **Transaction List**: Date, type, amount, status
- **Filters**: Type (subscription, credits), status (succeeded, failed)
- **Pagination**: Load more
- **Receipt Links**: Download Stripe receipts

### State
```typescript
const [transactions, setTransactions] = useState<Transaction[]>([]);
const [filter, setFilter] = useState<'all' | 'subscription' | 'credits'>('all');
const [loading, setLoading] = useState(true);
const [hasMore, setHasMore] = useState(true);
const [offset, setOffset] = useState(0);
```

### Data Flow
```typescript
useEffect(() => {
  loadTransactions();
}, [filter, offset]);

const loadTransactions = async () => {
  const data = await billingApi.getTransactions(20, offset, filter);

  if (offset === 0) {
    setTransactions(data.transactions);
  } else {
    setTransactions(prev => [...prev, ...data.transactions]);
  }

  setHasMore(data.has_more);
};

const loadMore = () => {
  setOffset(prev => prev + 20);
};
```

### Transaction Table
```typescript
<table className="transactions-table">
  <thead>
    <tr>
      <th>Date</th>
      <th>Type</th>
      <th>Description</th>
      <th>Amount</th>
      <th>Status</th>
      <th>Receipt</th>
    </tr>
  </thead>
  <tbody>
    {transactions.map(txn => (
      <tr key={txn.id}>
        <td>{formatDate(txn.created_at)}</td>
        <td>{txn.type}</td>
        <td>{txn.description}</td>
        <td>${txn.amount}</td>
        <td>
          <StatusBadge status={txn.status} />
        </td>
        <td>
          {txn.receipt_url && (
            <a href={txn.receipt_url} target="_blank" rel="noopener">
              Download
            </a>
          )}
        </td>
      </tr>
    ))}
  </tbody>
</table>

{hasMore && (
  <button onClick={loadMore}>
    Load More
  </button>
)}
```

---

## Billing Components

### UpgradeModal
Prompts user to upgrade when hitting limits:

```typescript
interface UpgradeModalProps {
  show: boolean;
  onClose: () => void;
  reason: string;
  currentTier: string;
}

export function UpgradeModal({ show, onClose, reason, currentTier }: UpgradeModalProps) {
  if (!show) return null;

  return (
    <div className="modal-overlay">
      <div className="modal">
        <h2>Upgrade Required</h2>
        <p>{reason}</p>

        <div className="current-tier">
          <span>Current plan: {currentTier}</span>
        </div>

        <div className="actions">
          <button onClick={() => navigate('/billing/plans')}>
            View Plans
          </button>
          <button onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
```

### CreditsPurchaseModal
Quick credit purchase:

```typescript
export function CreditsPurchaseModal({ show, onClose }: CreditsPurchaseModalProps) {
  const [amount, setAmount] = useState(100);
  const price = amount * 0.01; // $0.01 per credit

  const handlePurchase = async () => {
    try {
      const { url } = await billingApi.createCreditsPurchase(amount);
      window.location.href = url; // Redirect to Stripe
    } catch (error) {
      toast.error('Failed to start checkout');
    }
  };

  return (
    <Modal show={show} onClose={onClose}>
      <h2>Purchase Credits</h2>

      <div className="amount-selector">
        <button onClick={() => setAmount(100)}>100 credits ($1)</button>
        <button onClick={() => setAmount(500)}>500 credits ($5)</button>
        <button onClick={() => setAmount(1000)}>1000 credits ($10)</button>
        <input
          type="number"
          value={amount}
          onChange={(e) => setAmount(Number(e.target.value))}
          min={10}
        />
      </div>

      <div className="total">
        Total: ${price.toFixed(2)}
      </div>

      <button onClick={handlePurchase}>
        Purchase {amount} Credits
      </button>
    </Modal>
  );
}
```

### ProjectLimitBanner
Shown on dashboard when at project limit:

```typescript
export function ProjectLimitBanner({ currentCount, limit }: ProjectLimitBannerProps) {
  if (currentCount < limit) return null;

  return (
    <div className="limit-banner">
      <WarningCircle size={20} />
      <span>
        You've reached your project limit ({limit}).
        <Link to="/billing/plans">Upgrade</Link> to create more.
      </span>
    </div>
  );
}
```

## API Endpoints

```typescript
// Get subscription
GET /api/billing/subscription

// Get plans
GET /api/billing/plans

// Create checkout session
POST /api/billing/checkout
{ price_id: string, billing_cycle: 'monthly' | 'yearly' }

// Cancel subscription
POST /api/billing/subscription/cancel
{ at_period_end: boolean }

// Get customer portal URL
GET /api/billing/portal

// Get credit balance
GET /api/billing/credits/balance

// Purchase credits
POST /api/billing/credits/purchase
{ amount: number }

// Get transactions
GET /api/billing/transactions?limit=20&offset=0&filter=all

// Get credits history
GET /api/billing/credits/history?limit=20&offset=0

// Get current usage
GET /api/billing/usage/current

// Get usage limits
GET /api/billing/usage/limits

// Get usage history
GET /api/billing/usage/history?days=30
```

## Best Practices

### 1. Cache Subscription Data
```typescript
const subscriptionCache = useRef<SubscriptionResponse | null>(null);

const loadSubscription = async () => {
  if (subscriptionCache.current) {
    return subscriptionCache.current;
  }

  const data = await billingApi.getSubscription();
  subscriptionCache.current = data;
  return data;
};
```

### 2. Handle Stripe Redirects
```typescript
// Success redirect: /billing/success?session_id={CHECKOUT_SESSION_ID}
// Cancel redirect: /billing/cancel

useEffect(() => {
  const sessionId = searchParams.get('session_id');
  if (sessionId) {
    // Verify session
    verifyCheckoutSession(sessionId);
  }
}, [searchParams]);
```

### 3. Show Loading States
```typescript
if (loading) {
  return <BillingDashboardSkeleton />;
}
```

## Troubleshooting

**Issue**: Checkout not working
- Verify Stripe keys are set
- Check webhook is configured
- Test with Stripe test cards

**Issue**: Subscription not updating
- Check webhook events in Stripe dashboard
- Verify subscription_id matches

**Issue**: Usage limits not enforced
- Backend must check limits on operations
- Frontend shows warnings only
