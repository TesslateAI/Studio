# Billing Components

**Location**: `app/src/components/billing/`

Billing components handle subscription management, credit purchases, usage tracking, and tier-based feature gating for OpenSail.

## Component Overview

### Active Components

| Component | Purpose |
|-----------|---------|
| `SubscriptionPlans.tsx` | Tier comparison and upgrade flow |
| `SubscriptionStatus.tsx` | Current plan display in sidebar/navbar |
| `CreditsPurchaseModal.tsx` | Modal for purchasing credit packages |
| `UpgradeModal.tsx` | Shown when hitting tier limits |
| `LowBalanceWarning.tsx` | Warning when credits are low |
| `OutOfCreditsModal.tsx` | Modal when credits are depleted |
| `ProjectLimitBanner.tsx` | Banner when at project limit |
| `DeployButton.tsx` | Deploy button with limit checking |
| `AgentPurchaseButton.tsx` | Marketplace agent purchase |

---

## Subscription Tiers

OpenSail uses a **4-tier subscription model**:

| Tier | Price | Projects | Deploys | Monthly Credits | BYOK |
|------|-------|----------|---------|-----------------|------|
| **Free** | $0/mo | 3 | 1 | 1,000 | No |
| **Basic** | $8/mo | 5 | 2 | 1,000 | No |
| **Pro** | $20/mo | 10 | 5 | 2,500 | Yes |
| **Ultra** | $100/mo | Unlimited | 20 | 12,000 | Yes |

---

## Credit System

**1 credit = $0.01 USD**

### Credit Types

1. **Bundled Credits**: Monthly allowance included with subscription
   - Resets on billing date
   - Consumed first

2. **Purchased Credits**: Additional credits bought separately
   - Never expire
   - Consumed after bundled credits are depleted

### Credit Packages

| Package | Credits | Price |
|---------|---------|-------|
| Small | 500 | $5 |
| Medium | 1,000 | $10 |

---

## Component Details

### SubscriptionStatus.tsx

**Purpose**: Displays current subscription tier and credit balance.

**Props**:
```typescript
interface SubscriptionStatusProps {
  compact?: boolean;     // Minimal version for navbar
  showCredits?: boolean; // Display credit balance
}
```

**Features**:
- Tier badge with color coding
- Credit balance (bundled + purchased)
- Credits reset date
- Upgrade CTA for lower tiers

**Usage**:
```tsx
// In sidebar
<SubscriptionStatus showCredits={true} />

// In navbar (compact)
<SubscriptionStatus compact={true} />
```

---

### SubscriptionPlans.tsx

**Purpose**: Full pricing page with tier comparison.

**Features**:
- All 4 tiers displayed as cards
- Feature comparison list
- Current plan indicator
- Stripe Checkout redirect for upgrades
- BYOK badge for Pro/Ultra

**Tier Card Structure**:
```tsx
<div className={`tier-card ${isCurrentTier ? 'current' : ''}`}>
  {isPopular && <div className="badge">Most Popular</div>}

  <h3>{tier.name}</h3>
  <div className="price">
    <span className="amount">${tier.price}</span>
    <span>/month</span>
  </div>

  <ul className="features">
    <li>{tier.max_projects} projects</li>
    <li>{tier.max_deploys} deployments</li>
    <li>{tier.bundled_credits} credits/month</li>
    {tier.byok_enabled && <li>Bring Your Own API Key</li>}
  </ul>

  <button onClick={() => handleUpgrade(tier.id)}>
    {isCurrentTier ? 'Current Plan' : 'Upgrade'}
  </button>
</div>
```

---

### CreditsPurchaseModal.tsx

**Purpose**: Modal for purchasing additional credits.

**Props**:
```typescript
interface CreditsPurchaseModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}
```

**Features**:
- Package selection (Small: $5/500, Medium: $10/1000)
- Current balance display
- Stripe Checkout redirect
- Success/error handling

**Usage**:
```tsx
<CreditsPurchaseModal
  isOpen={showCreditsPurchase}
  onClose={() => setShowCreditsPurchase(false)}
  onSuccess={() => {
    toast.success('Credits added!');
    refreshCredits();
  }}
/>
```

**Flow**:
```typescript
const handlePurchase = async (packageId: 'small' | 'medium') => {
  try {
    const { url } = await billingApi.purchaseCredits(packageId);
    window.location.href = url;  // Redirect to Stripe
  } catch (error) {
    toast.error('Failed to start checkout');
  }
};
```

---

### LowBalanceWarning.tsx

**Purpose**: Warning indicator when credits are running low.

**Props**:
```typescript
interface LowBalanceWarningProps {
  totalCredits: number;
  threshold: number;  // Usually 20% of monthly allowance
  onPurchase?: () => void;
}
```

**Display Logic**:
- Shows when `totalCredits <= threshold`
- Yellow warning for low balance
- Red warning when empty

**Usage**:
```tsx
<LowBalanceWarning
  totalCredits={credits.total_credits}
  threshold={credits.threshold}
  onPurchase={() => setShowCreditsPurchase(true)}
/>
```

---

### OutOfCreditsModal.tsx

**Purpose**: Modal shown when user tries to use AI with zero credits.

**Props**:
```typescript
interface OutOfCreditsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onPurchase: () => void;
  tier: string;
  monthlyAllowance: number;
  resetDate: string;
}
```

**Features**:
- Shows current tier info
- Reset date for bundled credits
- Quick purchase button
- Upgrade option for higher tiers

---

### UpgradeModal.tsx

**Purpose**: Prompts user to upgrade when hitting tier limits.

**Props**:
```typescript
interface UpgradeModalProps {
  isOpen: boolean;
  onClose: () => void;
  reason: 'projects' | 'deploys' | 'byok' | 'credits';
  currentTier: string;
  limit?: number;
}
```

**Trigger Conditions**:
- Hit project limit
- Hit deployment limit
- Trying to use BYOK on Free/Basic
- Need more monthly credits

**Usage**:
```tsx
<UpgradeModal
  isOpen={showUpgrade}
  onClose={() => setShowUpgrade(false)}
  reason="projects"
  currentTier="basic"
  limit={5}
/>
```

---

### ProjectLimitBanner.tsx

**Purpose**: Banner shown on dashboard when at project limit.

**Props**:
```typescript
interface ProjectLimitBannerProps {
  currentCount: number;
  limit: number;
  tier: string;
}
```

**Display**:
- Progress bar showing usage
- Upgrade CTA
- Dismissible

**Usage**:
```tsx
{projects.length >= subscription.max_projects && (
  <ProjectLimitBanner
    currentCount={projects.length}
    limit={subscription.max_projects}
    tier={subscription.tier}
  />
)}
```

---

### DeployButton.tsx

**Purpose**: Deploy button that checks limits and credits before deploying.

**Props**:
```typescript
interface DeployButtonProps {
  projectId: string;
  onDeploy: () => Promise<void>;
  disabled?: boolean;
}
```

**Logic Flow**:
```typescript
const handleDeploy = async () => {
  // 1. Check deployment limit
  const subscription = await billingApi.getSubscription();
  if (subscription.deployments_used >= subscription.max_deploys) {
    setShowUpgradeModal(true);
    return;
  }

  // 2. Check credit balance (deploys cost credits)
  const credits = await billingApi.getCreditsBalance();
  if (credits.total_credits < DEPLOY_COST) {
    setShowCreditsPurchase(true);
    return;
  }

  // 3. Proceed with deployment
  await onDeploy();
};
```

---

### AgentPurchaseButton.tsx

**Purpose**: Button for purchasing marketplace agents.

**Props**:
```typescript
interface AgentPurchaseButtonProps {
  agentSlug: string;
  price: number;           // Price in cents
  pricingType: 'free' | 'one_time' | 'monthly';
  isOwned: boolean;
  onPurchase?: () => void;
}
```

**Features**:
- Shows price or "Owned" status
- Handles all pricing types
- Stripe Checkout for paid agents
- Revenue split info (90% creator / 10% platform)

---

## API Integration

### Billing API Methods

```typescript
import { billingApi } from '../../lib/api';

// Subscription
const subscription = await billingApi.getSubscription();
const { url } = await billingApi.subscribe('pro');
await billingApi.cancelSubscription(true);  // at_period_end
await billingApi.renewSubscription();
const { url } = await billingApi.getCustomerPortal();

// Credits
const credits = await billingApi.getCreditsBalance();
const status = await billingApi.getCreditsStatus();
const { url } = await billingApi.purchaseCredits('small');
const history = await billingApi.getCreditsHistory(50, 0);

// Usage
const usage = await billingApi.getUsage(startDate, endDate);
const logs = await billingApi.getUsageLogs(100, 0);

// Config (public, no auth)
const config = await billingApi.getConfig();
```

### Response Types

```typescript
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
  is_low: boolean;      // <= 20% of monthly allowance
  is_empty: boolean;    // = 0
  threshold: number;
  tier: string;
  monthly_allowance: number;
}
```

---

## Stripe Checkout Flow

### Subscription Upgrade

```typescript
const handleUpgrade = async (tier: string) => {
  try {
    setLoading(true);
    const { url } = await billingApi.subscribe(tier);
    window.location.href = url;  // Redirect to Stripe Checkout
  } catch (error) {
    toast.error('Failed to start checkout');
  } finally {
    setLoading(false);
  }
};
```

### Credit Purchase

```typescript
const handlePurchaseCredits = async (packageId: 'small' | 'medium') => {
  try {
    const { url } = await billingApi.purchaseCredits(packageId);
    window.location.href = url;
  } catch (error) {
    toast.error('Failed to purchase credits');
  }
};
```

### Handling Success Redirect

After Stripe checkout, users are redirected to `/settings/billing?success=true`:

```typescript
// In BillingSettings.tsx
useEffect(() => {
  const params = new URLSearchParams(location.search);

  if (params.get('success') === 'true') {
    toast.success('Payment successful!');
    // Remove query param and refresh data
    navigate('/settings/billing', { replace: true });
    loadSubscription();
  }
}, [location.search]);
```

---

## Usage Gating Pattern

### Check Limits Before Action

```typescript
const performAction = async () => {
  // 1. Fetch current subscription
  const subscription = await billingApi.getSubscription();

  // 2. Check limit
  if (subscription.projects_count >= subscription.max_projects) {
    setShowUpgradeModal(true);
    return;
  }

  // 3. Check credits if needed
  const credits = await billingApi.getCreditsBalance();
  if (credits.total_credits < ACTION_COST) {
    setShowCreditsPurchase(true);
    return;
  }

  // 4. Perform action
  await doAction();
};
```

### BYOK Check

```typescript
const checkByokAccess = async () => {
  const subscription = await billingApi.getSubscription();

  if (!subscription.byok_enabled) {
    // Show upgrade modal with BYOK reason
    setUpgradeReason('byok');
    setShowUpgradeModal(true);
    return false;
  }

  return true;
};
```

---

## Testing

### Mock Billing API

```typescript
jest.mock('../../lib/api', () => ({
  billingApi: {
    getSubscription: jest.fn().mockResolvedValue({
      tier: 'basic',
      max_projects: 5,
      max_deploys: 2,
      bundled_credits: 1000,
      purchased_credits: 0,
      total_credits: 1000,
      byok_enabled: false,
    }),
    getCreditsBalance: jest.fn().mockResolvedValue({
      bundled_credits: 500,
      purchased_credits: 200,
      total_credits: 700,
    }),
    getCreditsStatus: jest.fn().mockResolvedValue({
      total_credits: 700,
      is_low: false,
      is_empty: false,
      threshold: 200,
    }),
  },
}));
```

### Test Upgrade Modal Trigger

```typescript
test('shows upgrade modal when project limit reached', async () => {
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
test('redirects to Stripe checkout on upgrade', async () => {
  const originalLocation = window.location;
  delete window.location;
  window.location = { href: '' } as Location;

  billingApi.subscribe.mockResolvedValue({
    url: 'https://checkout.stripe.com/session-123',
  });

  render(<SubscriptionPlans />);
  fireEvent.click(screen.getByText('Upgrade to Pro'));

  await waitFor(() => {
    expect(window.location.href).toBe('https://checkout.stripe.com/session-123');
  });

  window.location = originalLocation;
});
```

---

## Styling

All billing components use Tailwind CSS with the project's design system:

```tsx
// Tier badge colors
const tierColors = {
  free: 'bg-gray-100 text-gray-800',
  basic: 'bg-blue-100 text-blue-800',
  pro: 'bg-purple-100 text-purple-800',
  ultra: 'bg-yellow-100 text-yellow-800',
};

// Credit warning colors
const creditWarningColors = {
  normal: 'text-green-500',
  low: 'text-yellow-500',
  empty: 'text-red-500',
};
```

---

## Related Files

- **Backend Router**: `orchestrator/app/routers/billing.py`
- **Stripe Service**: `orchestrator/app/services/stripe_service.py`
- **API Types**: `app/src/types/billing.ts`
- **API Client**: `app/src/lib/api.ts` → `billingApi`
- **Settings Page**: `app/src/pages/settings/BillingSettings.tsx`

---

**See CLAUDE.md for additional implementation patterns and debugging tips.**
