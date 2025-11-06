# Frontend Billing Integration Guide

This guide explains how to integrate the billing components into your Tesslate Studio frontend application.

## Components Created

All billing components are located in `app/src/components/billing/`:

### 1. **SubscriptionPlans** (`SubscriptionPlans.tsx`)
Full-featured pricing page showing Free vs Premium tiers with detailed feature comparison.

**Usage:**
```tsx
import { SubscriptionPlans } from '../components/billing';

// In your route
<Route path="/billing/plans" element={<SubscriptionPlans />} />
```

**Features:**
- Shows pricing comparison with feature list
- Handles upgrade button click
- Redirects to Stripe Checkout
- Shows FAQ section

### 2. **SubscriptionStatus** (`SubscriptionStatus.tsx`)
Displays current subscription tier and limits. Can be used in navbar or sidebar.

**Usage:**
```tsx
import { SubscriptionStatus } from '../components/billing';

// Compact version for navbar
<SubscriptionStatus compact={true} showCredits={true} />

// Full version for sidebar
<SubscriptionStatus />
```

**Props:**
- `compact?: boolean` - Use compact layout for navbar
- `showCredits?: boolean` - Show/hide credits balance

### 3. **BillingDashboard** (`BillingDashboard.tsx`)
Main billing page showing subscription, credits, and transactions.

**Usage:**
```tsx
import { BillingDashboard } from '../components/billing';

<Route path="/billing" element={<BillingDashboard />} />
```

**Features:**
- Subscription status card
- Credits balance card
- Recent transactions list
- Cancel subscription button
- Purchase credits button

### 4. **UsageDashboard** (`UsageDashboard.tsx`)
Detailed usage analytics by model and agent.

**Usage:**
```tsx
import { UsageDashboard } from '../components/billing';

<Route path="/billing/usage" element={<UsageDashboard />} />
```

**Features:**
- Date range selector (week/month/all)
- Usage summary cards (cost, requests, tokens)
- Usage breakdown by model
- Usage breakdown by agent
- Manual sync button

### 5. **CreditsPurchaseModal** (`CreditsPurchaseModal.tsx`)
Modal for purchasing credits in different packages.

**Usage:**
```tsx
import { CreditsPurchaseModal } from '../components/billing';

const [showModal, setShowModal] = useState(false);

<CreditsPurchaseModal
  isOpen={showModal}
  onClose={() => setShowModal(false)}
  onSuccess={() => {
    setShowModal(false);
    // Refresh data
  }}
/>
```

**Features:**
- Shows current balance
- Three package options ($5, $10, $50)
- Redirects to Stripe Checkout
- Shows pricing info

### 6. **UpgradeModal** (`UpgradeModal.tsx`)
Modal shown when users hit limits or try to access premium features.

**Usage:**
```tsx
import { UpgradeModal } from '../components/billing';

const [showUpgrade, setShowUpgrade] = useState(false);

<UpgradeModal
  isOpen={showUpgrade}
  onClose={() => setShowUpgrade(false)}
  reason="projects" // or "deploys", "features", "general"
  title="Custom Title" // Optional
  message="Custom Message" // Optional
/>
```

**Reasons:**
- `projects` - Project limit reached
- `deploys` - Deploy limit reached
- `features` - Premium feature access
- `general` - Generic upgrade prompt

### 7. **DeployButton** (`DeployButton.tsx`)
Button for deploying/undeploying projects with limit checking.

**Usage:**
```tsx
import { DeployButton } from '../components/billing';

<DeployButton
  projectSlug={project.slug}
  isDeployed={project.is_deployed}
  onDeploySuccess={() => {
    // Refresh project data
  }}
  onUndeploySuccess={() => {
    // Refresh project data
  }}
  className="mt-4"
/>
```

**Features:**
- Shows deploy status and limits
- Handles deploy/undeploy
- Shows upgrade modal if limit reached
- Shows purchase slot modal for premium users

### 8. **ProjectLimitBanner** (`ProjectLimitBanner.tsx`)
Banner showing project usage and limits.

**Usage:**
```tsx
import { ProjectLimitBanner } from '../components/billing';

// Full banner (shows when near/at limit)
<ProjectLimitBanner currentProjectCount={projects.length} />

// Compact version (always shows)
<ProjectLimitBanner currentProjectCount={projects.length} compact={true} />
```

**Features:**
- Shows usage percentage
- Color-coded (blue/yellow/red based on usage)
- Upgrade button for free users
- Progress bar visualization

### 9. **AgentPurchaseButton** (`AgentPurchaseButton.tsx`)
Button for purchasing marketplace agents with different pricing types.

**Usage:**
```tsx
import { AgentPurchaseButton } from '../components/billing';

<AgentPurchaseButton
  agent={agent} // Agent object with pricing info
  isPurchased={false}
  onPurchaseSuccess={() => {
    // Refresh agent data
  }}
  className="mt-4"
/>
```

**Supported Pricing Types:**
- `free` - Free agents
- `monthly` - Monthly subscription
- `onetime` - One-time purchase
- `api` - Pay-per-use API pricing

## Integration Steps

### Step 1: Add Navbar Component

Update your navbar to show subscription status:

```tsx
// In your Navbar component
import { SubscriptionStatus } from '../components/billing';

<nav>
  {/* Other nav items */}
  <SubscriptionStatus compact={true} showCredits={true} />
</nav>
```

### Step 2: Add Project Limit Enforcement

Update your projects page to show limits and enforce them:

```tsx
// In Dashboard.tsx or Projects page
import { ProjectLimitBanner, UpgradeModal } from '../components/billing';

const [showUpgradeModal, setShowUpgradeModal] = useState(false);
const [projects, setProjects] = useState([]);

// Show limit banner
<ProjectLimitBanner currentProjectCount={projects.length} />

// On create project button click
const handleCreateProject = async () => {
  try {
    await api.post('/api/projects/', projectData);
  } catch (error) {
    if (error.response?.status === 403) {
      // Limit reached
      setShowUpgradeModal(true);
    }
  }
};

// Show upgrade modal
<UpgradeModal
  isOpen={showUpgradeModal}
  onClose={() => setShowUpgradeModal(false)}
  reason="projects"
/>
```

### Step 3: Add Deploy Button to Project Page

Update project detail page to include deploy functionality:

```tsx
// In Project.tsx
import { DeployButton } from '../components/billing';

<DeployButton
  projectSlug={project.slug}
  isDeployed={project.is_deployed}
  onDeploySuccess={() => loadProject()}
  onUndeploySuccess={() => loadProject()}
/>
```

### Step 4: Update Marketplace Agent Display

Update marketplace agent cards to use purchase button:

```tsx
// In Marketplace.tsx
import { AgentPurchaseButton } from '../components/billing';

{agents.map(agent => (
  <div key={agent.id} className="agent-card">
    <h3>{agent.name}</h3>
    <p>{agent.description}</p>

    <AgentPurchaseButton
      agent={agent}
      isPurchased={agent.is_purchased}
      onPurchaseSuccess={() => loadAgents()}
    />
  </div>
))}
```

### Step 5: Add Billing Link to Navigation

Add a link to the billing dashboard in your main navigation:

```tsx
<Link to="/billing">
  <svg>...</svg>
  Billing
</Link>
```

## Testing the Integration

### 1. **Test Stripe Configuration**

Ensure your `.env` file has test keys:
```bash
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

### 2. **Start Stripe CLI**

Forward webhooks to your local server:
```bash
stripe listen --forward-to http://localhost:8000/api/webhooks/stripe
```

### 3. **Test Subscription Flow**

1. Go to `/billing/plans`
2. Click "Upgrade to Premium"
3. Use test card: `4242 4242 4242 4242`
4. Complete checkout
5. Verify redirect to `/billing/success`
6. Check subscription status updates

### 4. **Test Credits Purchase**

1. Go to `/billing`
2. Click "Purchase Credits"
3. Select a package
4. Use test card
5. Verify credits added to balance

### 5. **Test Project Limits**

1. Create maximum projects for free tier (1)
2. Try to create another
3. Verify upgrade modal appears
4. Upgrade to premium
5. Create more projects (up to 5)

### 6. **Test Deploy Limits**

1. Deploy maximum projects for tier
2. Try to deploy another
3. Verify appropriate modal (upgrade or purchase slot)
4. Test purchase additional slot flow

### 7. **Test Agent Purchase**

1. Go to marketplace
2. Click on paid agent
3. Click purchase button
4. Complete checkout
5. Verify agent appears in library

### 8. **Test Usage Dashboard**

1. Use agents to generate usage
2. Go to `/billing/usage`
3. Click "Sync Usage"
4. Verify usage data appears
5. Test date range filters

## Common Issues & Solutions

### Issue: Stripe checkout URL not working
**Solution:**
- Verify `STRIPE_SECRET_KEY` is set correctly
- Check that user has `stripe_customer_id` in database
- Ensure success/cancel URLs are valid

### Issue: Webhooks not received
**Solution:**
- Check Stripe CLI is running
- Verify `STRIPE_WEBHOOK_SECRET` matches CLI output
- Check backend logs for webhook errors

### Issue: Limits not enforced
**Solution:**
- Ensure backend API is checking limits
- Verify subscription tier is correct in database
- Check `/api/billing/subscription` endpoint

### Issue: Components not loading
**Solution:**
- Check all imports are correct
- Verify routing is set up in App.tsx
- Check browser console for errors

## API Endpoints Used

The components interact with these backend endpoints:

### Billing Configuration
- `GET /api/billing/config` - Get public billing config

### Subscriptions
- `GET /api/billing/subscription` - Get current subscription
- `POST /api/billing/subscribe` - Create subscription checkout
- `POST /api/billing/cancel` - Cancel subscription
- `GET /api/billing/portal` - Get customer portal link

### Credits
- `GET /api/billing/credits` - Get credits balance
- `POST /api/billing/credits/purchase` - Purchase credits
- `GET /api/billing/credits/history` - Get purchase history

### Usage
- `GET /api/billing/usage` - Get usage summary
- `POST /api/billing/usage/sync` - Sync from LiteLLM
- `GET /api/billing/usage/logs` - Get detailed logs

### Transactions
- `GET /api/billing/transactions` - Get all transactions

### Deployments
- `GET /api/projects/deployment/limits` - Get limits
- `POST /api/projects/{slug}/deploy` - Deploy project
- `DELETE /api/projects/{slug}/deploy` - Undeploy project
- `POST /api/projects/deployment/purchase-slot` - Buy slot

### Marketplace
- `POST /api/marketplace/agents/{id}/purchase` - Purchase agent

## Next Steps

1. **Customize Styling**: Update component styles to match your design system
2. **Add Analytics**: Track button clicks and conversions
3. **Error Handling**: Add more robust error handling and user feedback
4. **Loading States**: Enhance loading states with skeletons
5. **Accessibility**: Add ARIA labels and keyboard navigation
6. **Mobile Optimization**: Test and optimize for mobile devices

## Support

For issues or questions:
- Check [STRIPE_TESTING.md](./STRIPE_TESTING.md) for backend testing
- Check [STRIPE_IMPLEMENTATION_SUMMARY.md](./STRIPE_IMPLEMENTATION_SUMMARY.md) for architecture details
- Review component source code for inline documentation
