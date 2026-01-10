# Billing Components

**Location**: `app/src/components/billing/`

Billing components handle subscription management, usage tracking, credit purchases, and deployment gating based on user tier.

## Components Overview

### SubscriptionStatus.tsx

**Current Plan Display**: Shows user's subscription tier, limits, and credit balance.

**Props**:
```typescript
interface SubscriptionStatusProps {
  compact?: boolean;     // Show minimal version
  showCredits?: boolean; // Display credit balance
}
```

**Features**:
- **Tiers**: Free, Pro (Premium)
- **Limits**: Projects, deploys
- **Credit balance**: Real-time USD amount
- **Upgrade CTA**: For free users

**Compact Mode**:
```tsx
<Link to="/billing" className="flex items-center space-x-2">
  <div className="text-yellow-600">
    <StarIcon /> Premium
  </div>
  <div className="text-gray-600 border-l pl-2">
    $12.50
  </div>
</Link>
```

**Full Mode**:
```tsx
<div className="bg-white rounded-lg shadow p-4">
  {/* Tier badge */}
  <div className="bg-yellow-100 text-yellow-800 px-3 py-1.5 rounded-full">
    <StarIcon /> Premium
  </div>

  {/* Limits */}
  <div className="grid grid-cols-2 gap-3">
    <div>Projects: {maxProjects}</div>
    <div>Deploys: {maxDeploys}</div>
  </div>

  {/* Credits */}
  <div className="border-t pt-3">
    Credits Balance: ${balance.toFixed(2)}
  </div>
</div>
```

---

### SubscriptionPlans.tsx

**Upgrade UI**: Displays plan cards with features and pricing.

**Features**:
- Free and Pro plan cards
- Feature comparison
- Price display
- Stripe checkout integration
- Current plan indicator

---

### BillingDashboard.tsx

**Full Billing Page**: Comprehensive billing management with subscription, usage, and transaction history.

**Sections**:
- Current subscription status
- Usage charts
- Transaction history
- Update payment method
- Cancel subscription

---

### UsageDashboard.tsx

**Usage Charts**: Visual display of API calls, tokens used, and project counts.

**Features**:
- Line/bar charts for usage over time
- Current vs. limit indicators
- Usage warnings when approaching limits

---

### CreditsPurchaseModal.tsx

**Buy Credits Dialog**: Modal for purchasing credits with Stripe.

**Features**:
- Credit amount selection ($10, $25, $50, $100)
- Price calculation
- Stripe payment form
- Success/error handling

**Usage**:
```typescript
<CreditsPurchaseModal
  isOpen={showCreditsPurchase}
  onClose={() => setShowCreditsPurchase(false)}
  onSuccess={() => {
    toast.success('Credits added!');
    refreshBalance();
  }}
/>
```

---

### TransactionHistory.tsx

**Payment History**: List of past purchases, credits used, and subscriptions.

**Features**:
- Paginated transaction list
- Transaction details (date, amount, type, status)
- Download receipts
- Refund status

---

### UpgradeModal.tsx

**Upgrade Flow**: Modal prompting user to upgrade to Pro.

**Triggers**:
- Hit project limit
- Hit deployment limit
- Accessing premium features

**Usage**:
```typescript
<UpgradeModal
  isOpen={showUpgrade}
  onClose={() => setShowUpgrade(false)}
  reason="You've reached the free plan's 3 project limit"
/>
```

---

### DeployButton.tsx

**Usage-Gated Deploy**: Deploy button that checks usage limits before allowing deployment.

**Features**:
- Checks if user has deploys remaining
- Shows upgrade modal if limit reached
- Displays deployment cost in credits
- Initiates deployment on click

**Props**:
```typescript
interface DeployButtonProps {
  projectId: number;
  onDeploy: () => Promise<void>;
  disabled?: boolean;
}
```

**Usage**:
```typescript
<DeployButton
  projectId={project.id}
  onDeploy={async () => {
    await deployApi.deploy(project.id);
    toast.success('Deployed!');
  }}
/>
```

**Logic**:
```typescript
const handleDeploy = async () => {
  // 1. Check subscription limits
  const subscription = await billingApi.getSubscription();
  if (subscription.deployments_used >= subscription.max_deploys) {
    setShowUpgradeModal(true);
    return;
  }

  // 2. Check credit balance
  const credits = await billingApi.getCreditsBalance();
  if (credits.balance_usd < DEPLOY_COST) {
    toast.error('Insufficient credits');
    setShowCreditsPurchase(true);
    return;
  }

  // 3. Proceed with deployment
  await onDeploy();
};
```

---

### ProjectLimitBanner.tsx

**Limit Warning**: Banner shown when user is approaching or at project/deploy limit.

**Features**:
- Dismissible banner
- Upgrade CTA
- Limit progress indicator

---

### AgentPurchaseButton.tsx

**Marketplace Purchase**: Button to purchase AI agents with credits.

**Features**:
- Price display in credits
- Ownership check (don't show if already owned)
- Credit balance check
- Purchase confirmation
- Success feedback

**Props**:
```typescript
interface AgentPurchaseButtonProps {
  agentId: number;
  price: number;          // USD amount
  onPurchase: () => void;
}
```

**Usage**:
```typescript
<AgentPurchaseButton
  agentId={agent.id}
  price={agent.price}
  onPurchase={() => {
    refreshAgents();
    toast.success(`${agent.name} added to your library!`);
  }}
/>
```

## Stripe Integration

### Subscription Checkout

```typescript
const handleUpgrade = async () => {
  try {
    const { checkout_url } = await billingApi.createCheckoutSession('pro');
    window.location.href = checkout_url;  // Redirect to Stripe
  } catch (error) {
    toast.error('Failed to start checkout');
  }
};
```

### Credits Purchase

```typescript
const handleCreditsPurchase = async (amount: number) => {
  try {
    const { checkout_url } = await billingApi.purchaseCredits(amount);
    window.location.href = checkout_url;
  } catch (error) {
    toast.error('Failed to purchase credits');
  }
};
```

### Webhook Handling

After successful payment, Stripe sends webhook to backend which:
1. Updates subscription status
2. Adds credits to balance
3. Sends confirmation email

Frontend polls or listens for updates:
```typescript
useEffect(() => {
  const interval = setInterval(() => {
    // Re-fetch subscription after returning from Stripe
    billingApi.getSubscription().then(setSubscription);
  }, 5000);

  return () => clearInterval(interval);
}, []);
```

## Usage Limits

### Free Tier
- 3 projects
- 5 deployments/month
- $5 credits/month
- Community agents only

### Pro Tier
- 25 projects
- 50 deployments/month
- $25 credits/month
- All marketplace agents
- Priority support

## Common Patterns

### Check if User Can Perform Action

```typescript
const canCreateProject = async (): Promise<boolean> => {
  const subscription = await billingApi.getSubscription();
  return subscription.projects_count < subscription.max_projects;
};

// Usage
if (!await canCreateProject()) {
  setShowUpgradeModal(true);
  return;
}

createProject();
```

### Deduct Credits

```typescript
const deductCredits = async (amount: number) => {
  const credits = await billingApi.getCreditsBalance();

  if (credits.balance_usd < amount) {
    setShowCreditsPurchase(true);
    return false;
  }

  await billingApi.deductCredits(amount);
  return true;
};
```

---

**See CLAUDE.md for implementation patterns and Stripe setup.**
