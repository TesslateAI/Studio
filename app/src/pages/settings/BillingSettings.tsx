import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Coins, Check, AlertTriangle } from 'lucide-react';
import { SettingsSection, SettingsGroup } from '../../components/settings';
import { billingApi } from '../../lib/api';
import toast from 'react-hot-toast';
import type {
  SubscriptionResponse,
  CreditBalanceResponse,
  Transaction,
  UsageSummaryResponse,
  SubscriptionTier,
} from '../../types/billing';
import {
  SUBSCRIPTION_TIER_LABELS,
  SUBSCRIPTION_TIER_PRICES,
  SUBSCRIPTION_TIER_CREDITS,
} from '../../types/billing';

export default function BillingSettings() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
  const [credits, setCredits] = useState<CreditBalanceResponse | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [usage, setUsage] = useState<UsageSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [purchasing, setPurchasing] = useState<string | null>(null);
  const [showPlanModal, setShowPlanModal] = useState(false);

  // Check for success/cancelled params
  useEffect(() => {
    if (searchParams.get('success') === 'true') {
      toast.success('Payment successful! Your plan has been updated.');
      // Clear the params
      navigate('/settings/billing', { replace: true });
    } else if (searchParams.get('cancelled') === 'true') {
      toast('Payment cancelled', { icon: '⚠️' });
      navigate('/settings/billing', { replace: true });
    }
  }, [searchParams, navigate]);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const [subRes, creditsRes, transRes, usageRes] = await Promise.all([
        billingApi.getSubscription(),
        billingApi.getCreditsBalance(),
        billingApi.getTransactions(5, 0),
        billingApi.getUsage(),
      ]);
      setSubscription(subRes);
      setCredits(creditsRes);
      setTransactions(transRes.transactions);
      setUsage(usageRes);
    } catch (err) {
      console.error('Failed to load billing data:', err);
      toast.error('Failed to load billing information');
    } finally {
      setLoading(false);
    }
  };

  const handlePurchaseCredits = async (packageType: 'small' | 'medium') => {
    setPurchasing(packageType);
    try {
      const response = await billingApi.purchaseCredits(packageType);
      if (response.url) {
        window.location.href = response.url;
      }
    } catch (err) {
      console.error('Failed to purchase credits:', err);
      toast.error('Failed to initiate purchase');
    } finally {
      setPurchasing(null);
    }
  };

  const handleUpgrade = async (tier: SubscriptionTier) => {
    if (tier === 'free') return;

    try {
      const response = await billingApi.subscribe(tier);
      if (response.url) {
        window.location.href = response.url;
      }
    } catch (err) {
      console.error('Failed to upgrade:', err);
      toast.error('Failed to initiate upgrade');
    }
  };

  const handleCancelSubscription = async () => {
    if (!subscription || subscription.tier === 'free') return;

    const confirmed = window.confirm(
      'Are you sure you want to cancel your subscription? You will continue to have access until the end of your billing period.'
    );

    if (!confirmed) return;

    try {
      await billingApi.cancelSubscription(true);
      toast.success('Subscription will cancel at end of billing period');
      await loadData();
    } catch (err) {
      console.error('Failed to cancel subscription:', err);
      toast.error('Failed to cancel subscription');
    }
  };

  const formatDate = (dateString?: string) => {
    if (!dateString) return 'N/A';
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const formatCredits = (amount: number) => {
    return amount.toLocaleString();
  };

  if (loading) {
    return (
      <SettingsSection title="Billing" description="Manage your subscription and credits">
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[var(--primary)]"></div>
        </div>
      </SettingsSection>
    );
  }

  const tier = subscription?.tier || 'free';
  const totalCredits = credits?.total_credits || 0;
  const monthlyAllowance = credits?.monthly_allowance || SUBSCRIPTION_TIER_CREDITS[tier];
  const isLowBalance = totalCredits <= monthlyAllowance * 0.2 && totalCredits > 0;
  const isEmpty = totalCredits <= 0;

  return (
    <SettingsSection title="Billing" description="Manage your subscription and credits">
      {/* Plan & Credits */}
      <SettingsGroup title="Plan & Credits">
        <div className="p-4 md:p-6">
          {/* Current Plan */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[var(--text)]/60 text-sm">Current Plan</span>
                {tier !== 'free' && (
                  <span className="px-2 py-0.5 bg-[var(--primary)]/20 text-[var(--primary)] text-xs font-medium rounded-full">
                    Active
                  </span>
                )}
              </div>
              <h3 className="text-2xl font-bold text-[var(--text)]">
                {SUBSCRIPTION_TIER_LABELS[tier]}
                {tier !== 'free' && (
                  <span className="text-lg font-normal text-[var(--text)]/60 ml-2">
                    ${SUBSCRIPTION_TIER_PRICES[tier]}/mo
                  </span>
                )}
              </h3>
              {subscription?.current_period_end && tier !== 'free' && (
                <p className="text-sm text-[var(--text)]/50 mt-1">
                  {subscription.cancel_at_period_end
                    ? `Cancels on ${formatDate(subscription.current_period_end)}`
                    : `Renews on ${formatDate(subscription.current_period_end)}`}
                </p>
              )}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setShowPlanModal(true)}
                className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-sm font-medium text-[var(--text)] hover:bg-white/10 transition-colors min-h-[44px]"
              >
                {tier === 'free' ? 'Upgrade' : 'Change Plan'}
              </button>
              {tier !== 'free' && !subscription?.cancel_at_period_end && (
                <button
                  onClick={handleCancelSubscription}
                  className="px-4 py-2 text-red-400 hover:text-red-300 text-sm font-medium transition-colors min-h-[44px]"
                >
                  Cancel
                </button>
              )}
            </div>
          </div>

          {/* Credits Display */}
          <div className="pt-6 border-t border-white/10">
            <div className="flex items-center gap-2 mb-2">
              <Coins size={20} className="text-[var(--status-warning)]" />
              <span className="text-[var(--text)]/60 text-sm">Credits Balance</span>
            </div>

            <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
              <div>
                <div className="flex items-baseline gap-2">
                  <span
                    className={`text-3xl font-bold ${isEmpty ? 'text-red-400' : isLowBalance ? 'text-[var(--status-warning)]' : 'text-[var(--text)]'}`}
                  >
                    {formatCredits(totalCredits)}
                  </span>
                  <span className="text-[var(--text)]/50 text-sm">credits remaining</span>
                </div>

                {/* Credit breakdown */}
                <div className="flex gap-4 mt-2 text-sm text-[var(--text)]/50">
                  <span>Bundled: {formatCredits(credits?.bundled_credits || 0)}</span>
                  <span>Purchased: {formatCredits(credits?.purchased_credits || 0)}</span>
                </div>

                {credits?.credits_reset_date && (
                  <p className="text-sm text-[var(--text)]/40 mt-2">
                    Bundled credits reset to {formatCredits(monthlyAllowance)} on{' '}
                    {formatDate(credits.credits_reset_date)}
                  </p>
                )}

                {/* Low balance warning */}
                {isLowBalance && (
                  <div className="flex items-center gap-2 mt-3 text-[var(--status-warning)]">
                    <AlertTriangle size={16} />
                    <span className="text-sm">Low balance - consider adding credits</span>
                  </div>
                )}
                {isEmpty && (
                  <div className="flex items-center gap-2 mt-3 text-red-400">
                    <AlertTriangle size={16} />
                    <span className="text-sm">Out of credits</span>
                  </div>
                )}
              </div>

              {/* Add Credits Buttons */}
              <div className="flex gap-2">
                <button
                  onClick={() => handlePurchaseCredits('small')}
                  disabled={purchasing !== null}
                  className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-sm font-medium text-[var(--text)] hover:bg-white/10 transition-colors min-h-[44px] disabled:opacity-50"
                >
                  {purchasing === 'small' ? 'Processing...' : '+500 ($5)'}
                </button>
                <button
                  onClick={() => handlePurchaseCredits('medium')}
                  disabled={purchasing !== null}
                  className="px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-lg text-sm font-medium transition-colors min-h-[44px] disabled:opacity-50"
                >
                  {purchasing === 'medium' ? 'Processing...' : '+1000 ($10)'}
                </button>
              </div>
            </div>
          </div>
        </div>
      </SettingsGroup>

      {/* Usage Summary */}
      <SettingsGroup title="Usage This Month">
        <div className="p-4 md:p-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <div className="text-2xl font-bold text-[var(--text)]">
                {usage?.total_requests.toLocaleString() || 0}
              </div>
              <div className="text-sm text-[var(--text)]/50">Requests</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-[var(--text)]">
                {((usage?.total_tokens_input || 0) / 1000).toFixed(1)}K
              </div>
              <div className="text-sm text-[var(--text)]/50">Input Tokens</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-[var(--text)]">
                {((usage?.total_tokens_output || 0) / 1000).toFixed(1)}K
              </div>
              <div className="text-sm text-[var(--text)]/50">Output Tokens</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-[var(--text)]">
                {usage?.total_cost_cents || 0}
              </div>
              <div className="text-sm text-[var(--text)]/50">Credits Used</div>
            </div>
          </div>
        </div>
      </SettingsGroup>

      {/* Recent Transactions */}
      <SettingsGroup title="Recent Transactions">
        <div className="divide-y divide-white/10">
          {transactions.length === 0 ? (
            <div className="p-6 text-center text-[var(--text)]/50">No transactions yet</div>
          ) : (
            transactions.map((transaction) => (
              <div
                key={transaction.id}
                className="flex items-center justify-between px-4 md:px-6 py-3"
              >
                <div>
                  <div className="text-sm font-medium text-[var(--text)]">
                    {getTransactionLabel(transaction.type)}
                  </div>
                  <div className="text-xs text-[var(--text)]/50">
                    {formatDate(transaction.created_at)}
                  </div>
                </div>
                <div className="text-sm font-medium text-[var(--text)]">
                  {transaction.type === 'credit_purchase' ? '+' : ''}
                  {transaction.amount_cents} credits
                </div>
              </div>
            ))
          )}
        </div>
      </SettingsGroup>

      {/* Plan Selection Modal */}
      {showPlanModal && (
        <PlanSelectionModal
          currentTier={tier}
          onSelect={handleUpgrade}
          onClose={() => setShowPlanModal(false)}
        />
      )}
    </SettingsSection>
  );
}

function getTransactionLabel(type: string): string {
  const labels: Record<string, string> = {
    credit_purchase: 'Credit Purchase',
    agent_purchase_onetime: 'Agent Purchase',
    agent_purchase_monthly: 'Agent Subscription',
    usage_invoice: 'Usage',
    deploy_slot_purchase: 'Deploy Slot',
  };
  return labels[type] || type;
}

interface PlanSelectionModalProps {
  currentTier: SubscriptionTier;
  onSelect: (tier: SubscriptionTier) => void;
  onClose: () => void;
}

function PlanSelectionModal({ currentTier, onSelect, onClose }: PlanSelectionModalProps) {
  const tiers: SubscriptionTier[] = ['free', 'basic', 'pro', 'ultra'];
  const tierOrder = { free: 0, basic: 1, pro: 2, ultra: 3 };

  const tierFeatures: Record<SubscriptionTier, string[]> = {
    free: ['3 projects', '1 deploy', '1,000 credits/mo'],
    basic: ['5 projects', '2 deploys', '1,000 credits/mo'],
    pro: ['10 projects', '5 deploys', '2,500 credits/mo', 'BYOK (Bring Your Own Key)'],
    ultra: [
      'Unlimited projects',
      '20 deploys',
      '12,000 credits/mo',
      'BYOK (Bring Your Own Key)',
      'Priority support',
    ],
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-[var(--surface)] border border-white/10 rounded-2xl max-w-4xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6 border-b border-white/10">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-bold text-[var(--text)]">Choose Your Plan</h2>
            <button
              onClick={onClose}
              className="p-2 hover:bg-white/10 rounded-lg transition-colors"
            >
              <span className="sr-only">Close</span>
              <svg
                className="w-5 h-5 text-[var(--text)]"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>
        </div>

        <div className="p-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {tiers.map((tier) => {
              const isCurrent = tier === currentTier;
              const isDowngrade = tierOrder[tier] < tierOrder[currentTier];
              const isUpgrade = tierOrder[tier] > tierOrder[currentTier];
              const isPopular = tier === 'pro';

              return (
                <div
                  key={tier}
                  className={`relative p-4 rounded-xl border transition-colors ${
                    isCurrent
                      ? 'border-[var(--primary)] bg-[var(--primary)]/10'
                      : isPopular
                        ? 'border-[var(--primary)]/50 bg-white/5'
                        : 'border-white/10 bg-white/5 hover:border-white/20'
                  }`}
                >
                  {isPopular && (
                    <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 bg-[var(--primary)] text-white text-xs font-medium rounded-full">
                      Popular
                    </div>
                  )}

                  <div className="text-center mb-4">
                    <h3 className="text-lg font-bold text-[var(--text)]">
                      {SUBSCRIPTION_TIER_LABELS[tier]}
                    </h3>
                    <div className="mt-2">
                      <span className="text-3xl font-bold text-[var(--text)]">
                        ${SUBSCRIPTION_TIER_PRICES[tier]}
                      </span>
                      {tier !== 'free' && <span className="text-[var(--text)]/50">/mo</span>}
                    </div>
                  </div>

                  <ul className="space-y-2 mb-4">
                    {tierFeatures[tier].map((feature, idx) => (
                      <li
                        key={idx}
                        className="flex items-center gap-2 text-sm text-[var(--text)]/70"
                      >
                        <Check size={14} className="text-green-400 flex-shrink-0" />
                        {feature}
                      </li>
                    ))}
                  </ul>

                  {isCurrent ? (
                    <button
                      disabled
                      className="w-full py-2 px-4 bg-white/10 text-[var(--text)]/50 rounded-lg text-sm font-medium"
                    >
                      Current Plan
                    </button>
                  ) : isDowngrade ? (
                    <button
                      disabled
                      className="w-full py-2 px-4 bg-white/5 text-[var(--text)]/30 rounded-lg text-sm font-medium"
                    >
                      Contact Support
                    </button>
                  ) : tier === 'free' ? null : (
                    <button
                      onClick={() => {
                        onSelect(tier);
                        onClose();
                      }}
                      className={`w-full py-2 px-4 rounded-lg text-sm font-medium transition-colors ${
                        isPopular
                          ? 'bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white'
                          : 'bg-white/10 hover:bg-white/20 text-[var(--text)]'
                      }`}
                    >
                      {isUpgrade ? 'Upgrade' : 'Select'}
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          <p className="mt-6 text-center text-sm text-[var(--text)]/50">
            All plans include access to the marketplace. Purchased credits never expire.
          </p>
        </div>
      </div>
    </div>
  );
}
