/**
 * Billing and subscription type definitions
 */

// ============================================================================
// Configuration Types
// ============================================================================

export interface BillingConfig {
  stripe_publishable_key: string;
  credit_packages: {
    small: number;
    medium: number;
    large: number;
  };
  premium_price: number;
  deploy_price: number;
  free_limits: {
    max_projects: number;
    max_deploys: number;
  };
  premium_limits: {
    max_projects: number;
    max_deploys: number;
  };
}

// ============================================================================
// Subscription Types
// ============================================================================

export type SubscriptionTier = 'free' | 'pro';

export interface SubscriptionResponse {
  tier: SubscriptionTier;
  is_active: boolean;
  subscription_id?: string;
  stripe_customer_id?: string;
  max_projects: number;
  max_deploys: number;
}

export interface CheckoutSessionResponse {
  session_id: string;
  url: string;
}

// ============================================================================
// Credits Types
// ============================================================================

export type CreditPackage = 'small' | 'medium' | 'large';

export interface CreditBalanceResponse {
  balance_cents: number;
  balance_usd: number;
}

export interface CreditPurchase {
  id: string;
  amount_cents: number;
  amount_usd: number;
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
// Helper Types
// ============================================================================

export interface BillingError {
  detail: string;
  status?: number;
}

export const CREDIT_PACKAGE_LABELS: Record<CreditPackage, string> = {
  small: '$5 Credits',
  medium: '$10 Credits',
  large: '$50 Credits',
};

export const SUBSCRIPTION_TIER_LABELS: Record<SubscriptionTier, string> = {
  free: 'Free',
  pro: 'Premium',
};
