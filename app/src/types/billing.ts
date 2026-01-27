/**
 * Billing and subscription type definitions
 */

// ============================================================================
// Configuration Types
// ============================================================================

export interface TierConfig {
  price_cents: number;
  max_projects: number;
  max_deploys: number;
  bundled_credits: number;
  byok_enabled: boolean;
}

export interface CreditPackageConfig {
  credits: number;
  price_cents: number;
}

export interface BillingConfig {
  stripe_publishable_key: string;
  credit_packages: {
    small: CreditPackageConfig;
    medium: CreditPackageConfig;
  };
  deploy_price: number;
  tiers: {
    free: TierConfig;
    basic: TierConfig;
    pro: TierConfig;
    ultra: TierConfig;
  };
  low_balance_threshold: number;
}

// ============================================================================
// Subscription Types
// ============================================================================

export type SubscriptionTier = 'free' | 'basic' | 'pro' | 'ultra';

export interface SubscriptionResponse {
  tier: SubscriptionTier;
  is_active: boolean;
  subscription_id?: string;
  stripe_customer_id?: string;
  max_projects: number;
  max_deploys: number;
  current_period_start?: string;
  current_period_end?: string;
  cancel_at_period_end?: boolean;
  cancel_at?: string;
  bundled_credits: number;
  purchased_credits: number;
  total_credits: number;
  monthly_allowance: number;
  credits_reset_date?: string;
  byok_enabled: boolean;
}

export interface CheckoutSessionResponse {
  session_id: string;
  url: string;
}

// ============================================================================
// Credits Types
// ============================================================================

export type CreditPackage = 'small' | 'medium';

export interface CreditBalanceResponse {
  bundled_credits: number;
  purchased_credits: number;
  total_credits: number;
  monthly_allowance: number;
  credits_reset_date?: string;
  tier: SubscriptionTier;
}

export interface CreditStatusResponse {
  total_credits: number;
  is_low: boolean;
  is_empty: boolean;
  threshold: number;
  tier: SubscriptionTier;
  monthly_allowance: number;
}

export interface CreditPurchase {
  id: string;
  credits_amount: number;
  status: string;
  created_at: string;
  completed_at?: string;
}

export interface CreditPurchaseHistoryResponse {
  purchases: CreditPurchase[];
}

// ============================================================================
// Usage Types
// ============================================================================

export interface UsageByModel {
  [model: string]: {
    requests: number;
    tokens_input: number;
    tokens_output: number;
    cost_total: number;
  };
}

export interface UsageByAgent {
  [agentId: string]: {
    requests: number;
    tokens_input: number;
    tokens_output: number;
    cost_total: number;
  };
}

export interface UsageSummaryResponse {
  total_cost_cents: number;
  total_cost_usd: number;
  total_tokens_input: number;
  total_tokens_output: number;
  total_requests: number;
  by_model: UsageByModel;
  by_agent: UsageByAgent;
  period_start: string;
  period_end: string;
}

export interface UsageLog {
  id: string;
  model: string;
  tokens_input: number;
  tokens_output: number;
  cost_total_cents: number;
  cost_total_usd: number;
  agent_id?: string;
  project_id?: string;
  billed_status: 'pending' | 'paid' | 'credited';
  created_at: string;
}

export interface UsageLogsResponse {
  logs: UsageLog[];
}

// ============================================================================
// Transaction Types
// ============================================================================

export type TransactionType =
  | 'credit_purchase'
  | 'agent_purchase_onetime'
  | 'agent_purchase_monthly'
  | 'usage_invoice'
  | 'deploy_slot_purchase';

export interface Transaction {
  id: string;
  type: TransactionType;
  amount_cents: number;
  amount_usd: number;
  status: string;
  agent_id?: string;
  created_at: string;
}

export interface TransactionsResponse {
  transactions: Transaction[];
}

// ============================================================================
// Creator Earnings Types
// ============================================================================

export interface EarningsByAgent {
  [agentId: string]: {
    requests: number;
    revenue: number;
  };
}

export interface CreatorEarningsResponse {
  total_revenue_cents: number;
  total_revenue_usd: number;
  pending_revenue_cents: number;
  pending_revenue_usd: number;
  paid_revenue_cents: number;
  paid_revenue_usd: number;
  total_requests: number;
  by_agent: EarningsByAgent;
  period_start: string;
  period_end: string;
}

// ============================================================================
// Deployment Types
// ============================================================================

export interface DeploymentLimitsResponse {
  current_deploys: number;
  max_deploys: number;
  can_deploy: boolean;
  subscription_tier: SubscriptionTier;
  additional_slots_purchased: number;
}

// ============================================================================
// Portal & Connect Types
// ============================================================================

export interface CustomerPortalResponse {
  url: string;
}

export interface StripeConnectResponse {
  url: string;
}

// ============================================================================
// Helper Types & Constants
// ============================================================================

export interface BillingError {
  detail: string;
  status?: number;
}

export const CREDIT_PACKAGE_LABELS: Record<CreditPackage, string> = {
  small: '500 Credits ($5)',
  medium: '1000 Credits ($10)',
};

export const SUBSCRIPTION_TIER_LABELS: Record<SubscriptionTier, string> = {
  free: 'Free',
  basic: 'Basic',
  pro: 'Pro',
  ultra: 'Ultra',
};

export const SUBSCRIPTION_TIER_PRICES: Record<SubscriptionTier, number> = {
  free: 0,
  basic: 8,
  pro: 20,
  ultra: 100,
};

export const SUBSCRIPTION_TIER_CREDITS: Record<SubscriptionTier, number> = {
  free: 1000,
  basic: 1000,
  pro: 2500,
  ultra: 12000,
};

export const SUBSCRIPTION_TIER_PROJECTS: Record<SubscriptionTier, number> = {
  free: 3,
  basic: 5,
  pro: 10,
  ultra: 999,
};

export const SUBSCRIPTION_TIER_DEPLOYS: Record<SubscriptionTier, number> = {
  free: 1,
  basic: 2,
  pro: 5,
  ultra: 20,
};
