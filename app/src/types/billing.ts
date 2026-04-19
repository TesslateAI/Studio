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
  daily_credits: number;
  support_tier: string;
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
    large: CreditPackageConfig;
    team: CreditPackageConfig;
  };
  deploy_price: number;
  tiers: {
    free: TierConfig;
    basic: TierConfig;
    pro: TierConfig;
    ultra: TierConfig;
  };
  signup_bonus_credits: number;
  signup_bonus_expiry_days: number;
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
  support_tier: string;
  current_period_start?: string;
  current_period_end?: string;
  cancel_at_period_end?: boolean;
  cancel_at?: string;
  bundled_credits: number;
  purchased_credits: number;
  signup_bonus_credits: number;
  daily_credits: number;
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

export type CreditPackage = 'small' | 'medium' | 'large' | 'team';

export interface CreditBalanceResponse {
  bundled_credits: number;
  purchased_credits: number;
  signup_bonus_credits: number;
  daily_credits: number;
  total_credits: number;
  monthly_allowance: number;
  credits_reset_date?: string;
  signup_bonus_expires_at?: string;
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

export interface CreditsUsedEvent {
  cost_total: number;
  credits_deducted: number;
  new_balance: number;
  usage_log_id: string;
  is_byok: boolean;
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
// Verify Checkout Types
// ============================================================================

export interface VerifyCheckoutResponse {
  status: 'ok' | 'pending';
  type?: 'credit_purchase' | 'subscription' | 'unknown';
  credits_added?: number;
  tier?: string;
  already_fulfilled?: boolean;
  message?: string;
}

// ============================================================================
// Helper Types & Constants
// ============================================================================

export interface BillingError {
  detail: string;
  status?: number;
}

/**
 * SYNC REQUIREMENT: These labels must match the credit_package_* values in
 * orchestrator/app/config.py. The canonical source is the backend config.
 * Consider fetching dynamically from /api/billing/config if packages change frequently.
 */
export const CREDIT_PACKAGE_LABELS: Record<CreditPackage, string> = {
  small: '500 Credits ($5)',
  medium: '2,500 Credits ($25)',
  large: '10,000 Credits ($100)',
  team: '50,000 Credits ($500)',
};

export const SUBSCRIPTION_TIER_LABELS: Record<SubscriptionTier, string> = {
  free: 'Free',
  basic: 'Basic',
  pro: 'Pro',
  ultra: 'Ultra',
};

/** SYNC REQUIREMENT: Must match tier_price_* values in orchestrator/app/config.py (in dollars, not cents). */
export const SUBSCRIPTION_TIER_PRICES: Record<SubscriptionTier, number> = {
  free: 0,
  basic: 20,
  pro: 49,
  ultra: 149,
};

export const SUBSCRIPTION_TIER_CREDITS: Record<SubscriptionTier, string> = {
  free: '5/day',
  basic: '500',
  pro: '2,000',
  ultra: '8,000',
};

export const SUBSCRIPTION_TIER_PROJECTS: Record<SubscriptionTier, string> = {
  free: 'Unlimited',
  basic: 'Unlimited',
  pro: 'Unlimited',
  ultra: 'Unlimited',
};

export const SUBSCRIPTION_TIER_DEPLOYS: Record<SubscriptionTier, number> = {
  free: 1,
  basic: 3,
  pro: 5,
  ultra: 20,
};
