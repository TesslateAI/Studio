# Billing Components

Subscription, credit, and usage UI in `app/src/components/billing/`.

## File Index

| File | Purpose |
|------|---------|
| `billing/index.ts` | Barrel export |
| `billing/SubscriptionStatus.tsx` | Current-plan badge with tier name, expiry, manage-subscription link |
| `billing/UpgradeModal.tsx` | Plan-upgrade modal listing the four tiers (Free / Basic / Pro / Ultra) with feature comparison; opens Stripe Checkout via `billingApi.subscribe(tier)` |
| `billing/OutOfCreditsModal.tsx` | Modal shown when a user attempts an action but has zero credits; offers subscription upgrade or credit purchase |
| `billing/CreditsPurchaseModal.tsx` | Credit packages (Small 500/$5, Medium 2500/$25, Large 10000/$100, Team 50000/$500); loading spinner during Stripe session creation |
| `billing/LowBalanceWarning.tsx` | Inline banner when `billingApi.getCreditsStatus().is_low` is true (default threshold 20% of monthly allowance) |
| `billing/ProjectLimitBanner.tsx` | Top-of-dashboard banner when `projects_count >= max_projects`; links to upgrade modal |
| `billing/AgentPurchaseButton.tsx` | Wraps marketplace purchase: checks subscription+credits, opens Stripe if needed, handles success |
| `billing/DeployButton.tsx` | Deploy button with pre-flight usage check; opens `UpgradeModal` if deploy quota is exhausted |

## 4-Tier System

| Tier | Price | Projects | Deploys | Monthly Credits | BYOK |
|------|-------|----------|---------|-----------------|------|
| Free | $0 | 3 | 1 | 5/day | No |
| Basic | $20 | 7 | 3 | 500 | No |
| Pro | $49 | 15 | 5 | 2000 | Yes |
| Ultra | $149 | 40 | 20 | 8000 | Yes |

## Credit Rules

- 1 credit = $0.01 USD
- Bundled credits (monthly allowance) reset on billing date
- Purchased credits never expire; consumed after bundled credits

## Usage Gating Pattern

```tsx
const { subscription } = await billingApi.getSubscription();
if (subscription.projects_count >= subscription.max_projects) {
  setShowUpgradeModal(true);
  return;
}
const { total_credits } = await billingApi.getCreditsBalance();
if (total_credits < COST) {
  setShowCreditsPurchase(true);
  return;
}
await doAction();
```

## Related Docs

- `docs/app/pages/billing.md` – `BillingSettings.tsx` page composition
- `docs/orchestrator/services/credit-system.md` – backend credit accounting
- `docs/guides/stripe-payments-rebuild.md` – Stripe integration
