import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Coins,
  AlertTriangle,
  Zap,
  ArrowUpRight,
  TrendingUp,
  Clock,
  CreditCard,
} from 'lucide-react';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { SettingsSection, SettingsGroup } from '../../components/settings';
import { billingApi } from '../../lib/api';
import { useTeam } from '../../contexts/TeamContext';
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
  SUBSCRIPTION_TIER_PROJECTS,
} from '../../types/billing';

const creditPackages = [
  { key: 'small' as const, credits: 500, price: 5, label: '500', per: '$0.01' },
  { key: 'medium' as const, credits: 2500, price: 25, label: '2,500', per: '$0.01', popular: true },
  { key: 'large' as const, credits: 10000, price: 100, label: '10,000', per: '$0.01' },
  { key: 'team' as const, credits: 50000, price: 500, label: '50,000', per: '$0.01' },
];

export default function BillingSettings() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { can, refreshTeams, teamSwitchKey } = useTeam();
  const canManage = can('billing.manage');

  const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
  const [credits, setCredits] = useState<CreditBalanceResponse | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [usage, setUsage] = useState<UsageSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [purchasing, setPurchasing] = useState<string | null>(null);
  const [showPlanModal, setShowPlanModal] = useState(false);

  useEffect(() => {
    const sessionId = searchParams.get('session_id');
    if (searchParams.get('success') === 'true' && sessionId) {
      billingApi
        .verifyCheckout(sessionId)
        .then((result) => {
          if (result.already_fulfilled) {
            toast.success('Already applied to your account.');
          } else if (result.type === 'credit_purchase' && result.credits_added) {
            toast.success(
              `${result.credits_added.toLocaleString()} credits added to your account!`
            );
          } else if (result.type === 'subscription' && result.tier) {
            const tierLabel = result.tier.charAt(0).toUpperCase() + result.tier.slice(1);
            toast.success(`Upgraded to ${tierLabel} plan!`);
          } else {
            toast.success('Payment successful! Your account has been updated.');
          }
          loadData();
          refreshTeams();
        })
        .catch(() => {
          toast.success('Payment received! Changes may take a moment to apply.');
          refreshTeams();
        })
        .finally(() => {
          navigate('/settings/team/billing', { replace: true });
        });
    } else if (searchParams.get('success') === 'true') {
      toast.success('Payment successful! Your plan has been updated.');
      navigate('/settings/billing', { replace: true });
    } else if (searchParams.get('cancelled') === 'true') {
      toast('Payment cancelled', { icon: '\u26A0\uFE0F' });
      navigate('/settings/billing', { replace: true });
    }
  }, [searchParams, navigate]);

  useEffect(() => {
    loadData();
  }, [teamSwitchKey]);

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

  const handlePurchaseCredits = async (packageType: 'small' | 'medium' | 'large' | 'team') => {
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

  const handleUpgrade = async (
    tier: SubscriptionTier,
    billingInterval: 'monthly' | 'annual' = 'monthly'
  ) => {
    if (tier === 'free') return;

    try {
      const response = await billingApi.subscribe(tier, billingInterval);
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

  const formatCredits = (amount: number) => amount.toLocaleString();

  if (loading) {
    return (
      <div key={teamSwitchKey} style={{ animation: 'fade-in 0.25s ease-out' }}>
        <SettingsSection
          title="Billing"
          description={
            canManage
              ? 'Manage your subscription and credits'
              : 'View your subscription and credits'
          }
        >
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[var(--primary)]"></div>
          </div>
        </SettingsSection>
      </div>
    );
  }

  const tier = subscription?.tier || 'free';
  const totalCredits = credits?.total_credits || 0;
  const monthlyAllowance = credits?.monthly_allowance || 0;
  const tierCreditsLabel = SUBSCRIPTION_TIER_CREDITS[tier];
  const isLowBalance = totalCredits <= Math.max(monthlyAllowance * 0.2, 1) && totalCredits > 0;
  const isEmpty = totalCredits <= 0;

  return (
    <div key={teamSwitchKey} style={{ animation: 'fade-in 0.25s ease-out' }}>
      <SettingsSection
        title="Billing"
        description={
          canManage ? 'Manage your subscription and credits' : 'View your subscription and credits'
        }
      >
        {/* Current Plan Card */}
        <SettingsGroup title="Current Plan">
          <div className="p-5 md:p-6">
            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-2">
                  <h3 className="text-2xl font-bold text-[var(--text)]">
                    {SUBSCRIPTION_TIER_LABELS[tier]}
                  </h3>
                  {tier !== 'free' ? (
                    <span className="px-2.5 py-0.5 bg-emerald-500/15 text-emerald-400 text-xs font-medium rounded-full">
                      Active
                    </span>
                  ) : (
                    <span className="px-2.5 py-0.5 bg-white/5 text-[var(--text)]/50 text-xs font-medium rounded-full">
                      Free
                    </span>
                  )}
                </div>

                {tier !== 'free' && (
                  <p className="text-sm text-[var(--text)]/50">
                    ${SUBSCRIPTION_TIER_PRICES[tier]}/month
                    {subscription?.current_period_end && (
                      <span className="mx-1.5 text-[var(--text)]/20">|</span>
                    )}
                    {subscription?.current_period_end && (
                      <span>
                        {subscription.cancel_at_period_end
                          ? `Cancels ${formatDate(subscription.current_period_end)}`
                          : `Renews ${formatDate(subscription.current_period_end)}`}
                      </span>
                    )}
                  </p>
                )}

                <div className="flex flex-wrap items-center gap-x-5 gap-y-1 mt-3 text-sm text-[var(--text)]/40">
                  <span>{SUBSCRIPTION_TIER_PROJECTS[tier]} projects</span>
                  <span>{tierCreditsLabel} credits</span>
                </div>
              </div>

              {canManage && (
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => setShowPlanModal(true)}
                    className="px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-1.5"
                  >
                    {tier === 'free' ? (
                      <>
                        <Zap size={14} />
                        Upgrade
                      </>
                    ) : (
                      'Change Plan'
                    )}
                  </button>
                  {tier !== 'free' && !subscription?.cancel_at_period_end && (
                    <button
                      onClick={handleCancelSubscription}
                      className="px-4 py-2 text-[var(--text)]/40 hover:text-red-400 text-sm transition-colors"
                    >
                      Cancel
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        </SettingsGroup>

        {/* Credits Balance */}
        <SettingsGroup title="Credits">
          <div className="p-5 md:p-6">
            <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-6">
              {/* Balance display */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2.5 mb-4">
                  <div
                    className={`p-1.5 rounded-lg ${isEmpty ? 'bg-red-500/10' : isLowBalance ? 'bg-amber-500/10' : 'bg-[var(--primary)]/10'}`}
                  >
                    <Coins
                      size={18}
                      className={
                        isEmpty
                          ? 'text-red-400'
                          : isLowBalance
                            ? 'text-amber-400'
                            : 'text-[var(--primary)]'
                      }
                    />
                  </div>
                  <div className="flex items-baseline gap-2">
                    <span
                      className={`text-3xl font-bold tabular-nums ${isEmpty ? 'text-red-400' : isLowBalance ? 'text-amber-400' : 'text-[var(--text)]'}`}
                    >
                      {formatCredits(totalCredits)}
                    </span>
                    <span className="text-sm text-[var(--text)]/40">credits</span>
                  </div>
                </div>

                {/* Segmented credit bar */}
                <CreditUsageBar credits={credits} />

                {credits?.credits_reset_date && (
                  <p className="text-xs text-[var(--text)]/30 mt-3 flex items-center gap-1.5">
                    <Clock size={12} />
                    Resets to {tierCreditsLabel} on {formatDate(credits.credits_reset_date)}
                  </p>
                )}

                {isLowBalance && (
                  <div className="flex items-center gap-2 mt-3 px-3 py-2 bg-amber-500/5 border border-amber-500/10 rounded-lg text-amber-400">
                    <AlertTriangle size={14} />
                    <span className="text-xs">Low balance &mdash; consider topping up</span>
                  </div>
                )}
                {isEmpty && (
                  <div className="flex items-center gap-2 mt-3 px-3 py-2 bg-red-500/5 border border-red-500/10 rounded-lg text-red-400">
                    <AlertTriangle size={14} />
                    <span className="text-xs">No credits remaining</span>
                  </div>
                )}
              </div>

              {/* Top Up packages — admin only */}
              {canManage && (
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4 gap-2 lg:w-auto lg:shrink-0">
                  {creditPackages.map((pkg) => (
                    <button
                      key={pkg.key}
                      onClick={() => handlePurchaseCredits(pkg.key)}
                      disabled={purchasing !== null}
                      className={`relative flex flex-col items-center gap-1 px-4 py-3 rounded-lg text-sm transition-all disabled:opacity-50 min-w-[100px] ${
                        pkg.popular
                          ? 'bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white ring-1 ring-[var(--primary)]'
                          : 'bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.06] text-[var(--text)]'
                      }`}
                    >
                      {pkg.popular && (
                        <span className="absolute -top-2 left-1/2 -translate-x-1/2 px-2 py-px bg-[var(--primary)] text-[9px] font-semibold uppercase tracking-wider rounded-full text-white border border-white/20">
                          Popular
                        </span>
                      )}
                      <span className="font-semibold text-base tabular-nums">
                        {purchasing === pkg.key ? '...' : `+${pkg.label}`}
                      </span>
                      <span
                        className={`text-xs ${pkg.popular ? 'text-white/70' : 'text-[var(--text)]/40'}`}
                      >
                        ${pkg.price}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </SettingsGroup>

        {/* Usage This Month */}
        <SettingsGroup title="Usage This Month">
          <div className="p-5 md:p-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                {
                  label: 'Requests',
                  value: usage?.total_requests.toLocaleString() || '0',
                  icon: <TrendingUp size={14} />,
                },
                {
                  label: 'Input Tokens',
                  value: `${((usage?.total_tokens_input || 0) / 1000).toFixed(1)}K`,
                  icon: <ArrowUpRight size={14} />,
                },
                {
                  label: 'Output Tokens',
                  value: `${((usage?.total_tokens_output || 0) / 1000).toFixed(1)}K`,
                  icon: <ArrowUpRight size={14} />,
                },
                {
                  label: 'Credits Used',
                  value: `${usage?.total_cost_cents || 0}`,
                  icon: <Coins size={14} />,
                },
              ].map((stat) => (
                <div key={stat.label} className="bg-white/[0.02] rounded-lg p-3.5">
                  <div className="flex items-center gap-1.5 text-[var(--text)]/30 mb-1.5">
                    {stat.icon}
                    <span className="text-xs">{stat.label}</span>
                  </div>
                  <div className="text-xl font-bold text-[var(--text)] tabular-nums">
                    {stat.value}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </SettingsGroup>

        {/* Recent Transactions — admin only */}
        {canManage && (
          <SettingsGroup title="Recent Transactions">
            {transactions.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 text-[var(--text)]/30">
                <CreditCard size={24} className="mb-2" />
                <span className="text-sm">No transactions yet</span>
              </div>
            ) : (
              <div className="divide-y divide-white/[0.04]">
                {transactions.map((transaction) => (
                  <div
                    key={transaction.id}
                    className="flex items-center justify-between px-5 md:px-6 py-3.5"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-white/[0.04] flex items-center justify-center shrink-0">
                        {getTransactionIcon(transaction.type)}
                      </div>
                      <div>
                        <div className="text-sm font-medium text-[var(--text)]">
                          {getTransactionLabel(transaction.type)}
                        </div>
                        <div className="text-xs text-[var(--text)]/35">
                          {formatDate(transaction.created_at)}
                        </div>
                      </div>
                    </div>
                    <div
                      className={`text-sm font-medium tabular-nums ${
                        transaction.type === 'credit_purchase'
                          ? 'text-emerald-400'
                          : 'text-[var(--text)]'
                      }`}
                    >
                      {transaction.type === 'credit_purchase' ? '+' : ''}
                      {transaction.amount_cents.toLocaleString()} credits
                    </div>
                  </div>
                ))}
              </div>
            )}
          </SettingsGroup>
        )}

        {/* Plan Selection Modal */}
        {showPlanModal && (
          <PlanSelectionModal
            currentTier={tier}
            onSelect={handleUpgrade}
            onClose={() => setShowPlanModal(false)}
          />
        )}
      </SettingsSection>
    </div>
  );
}

/* ── Credit Usage Bar ── */
// Grey bar = full capacity (your total starting balance).
// Primary color fills from left as you USE credits — different shades per source.
// The grey never grows; the color overtakes it.
const CREDIT_SEGMENTS = [
  { key: 'daily_credits' as const, label: 'Daily', greyShade: 'rgba(255,255,255,0.06)' },
  { key: 'bundled_credits' as const, label: 'Monthly', greyShade: 'rgba(255,255,255,0.10)' },
  { key: 'signup_bonus_credits' as const, label: 'Bonus', greyShade: 'rgba(255,255,255,0.14)' },
];

function CreditUsageBar({
  credits,
  compact = false,
}: {
  credits: CreditBalanceResponse | null;
  compact?: boolean;
}) {
  if (!credits) return null;

  const remaining = credits.total_credits || 0;
  const capacity = Math.max(credits.monthly_allowance || 0, remaining, 1);
  const used = capacity - remaining;
  const usedPct = Math.min((used / capacity) * 100, 100);

  // Remaining segments in grey shades (right side of bar)
  const greySegments = CREDIT_SEGMENTS.map((seg) => ({
    ...seg,
    value: credits[seg.key] || 0,
  })).filter((seg) => seg.value > 0);

  if (compact) {
    return (
      <div className="w-full">
        <div className="flex h-1.5 rounded-full overflow-hidden">
          {/* Used portion — solid primary */}
          <div
            className="h-full bg-[var(--primary)] transition-all duration-500 shrink-0"
            style={{ width: `${usedPct}%` }}
          />
          {/* Remaining segments — grey shades */}
          {greySegments.map((seg) => (
            <div
              key={seg.key}
              className="h-full transition-all duration-500"
              style={{
                width: `${(seg.value / capacity) * 100}%`,
                backgroundColor: seg.greyShade,
              }}
            />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full">
      {/* Bar */}
      <div className="flex h-2.5 rounded-full overflow-hidden">
        {/* Used portion — solid primary */}
        <div
          className="h-full bg-[var(--primary)] transition-all duration-500 shrink-0"
          style={{ width: `${usedPct}%` }}
        />
        {/* Remaining segments — grey shades */}
        {greySegments.map((seg) => (
          <div
            key={seg.key}
            className="h-full transition-all duration-500"
            style={{
              width: `${(seg.value / capacity) * 100}%`,
              backgroundColor: seg.greyShade,
            }}
          />
        ))}
      </div>
      {/* Legend */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2.5">
        {/* Used */}
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-[var(--primary)]" />
          <span className="text-xs text-[var(--text)]/45">Used</span>
          <span className="text-xs font-medium text-[var(--text)]/60 tabular-nums">
            {used.toLocaleString()}
          </span>
        </div>
        {/* Remaining segments */}
        {greySegments.map((seg) => (
          <div key={seg.key} className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: seg.greyShade }} />
            <span className="text-xs text-[var(--text)]/45">{seg.label}</span>
            <span className="text-xs font-medium text-[var(--text)]/60 tabular-nums">
              {seg.value.toLocaleString()}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function getTransactionIcon(type: string) {
  switch (type) {
    case 'credit_purchase':
      return <Coins size={14} className="text-emerald-400" />;
    case 'agent_purchase_onetime':
    case 'agent_purchase_monthly':
      return <Zap size={14} className="text-purple-400" />;
    case 'deploy_slot_purchase':
      return <ArrowUpRight size={14} className="text-blue-400" />;
    default:
      return <CreditCard size={14} className="text-[var(--text)]/40" />;
  }
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

/* ── Plan data for modal ── */
type PlanFeature = { text: string; tip: string };

type PlanDef = {
  tier: SubscriptionTier;
  num: string;
  name: string;
  monthlyPrice: number;
  annualMonthlyPrice: number;
  annualTotal: number;
  period: string;
  description: string;
  highlighted: boolean;
  heading: string;
  features: PlanFeature[];
};

const planDefs: PlanDef[] = [
  {
    tier: 'free',
    num: '01',
    name: 'Free',
    monthlyPrice: SUBSCRIPTION_TIER_PRICES.free,
    annualMonthlyPrice: 0,
    annualTotal: 0,
    period: '/forever',
    description: 'For students and evaluators getting started.',
    highlighted: false,
    heading: 'Included',
    features: [
      {
        text: `${SUBSCRIPTION_TIER_PROJECTS.free} projects`,
        tip: 'Create as many separate development projects as you need',
      },
      {
        text: 'All AI models',
        tip: 'Claude, Gemini, GPT, Qwen, DeepSeek, Llama, Mistral, and more',
      },
      {
        text: `${SUBSCRIPTION_TIER_CREDITS.free} credits`,
        tip: 'Credits reset at the end of each day',
      },
      { text: 'Community support', tip: 'Get help from the community on Discord' },
    ],
  },
  {
    tier: 'basic',
    num: '02',
    name: 'Basic',
    monthlyPrice: SUBSCRIPTION_TIER_PRICES.basic,
    annualMonthlyPrice: Math.round(SUBSCRIPTION_TIER_PRICES.basic * 0.8),
    annualTotal: Math.round(SUBSCRIPTION_TIER_PRICES.basic * 12 * 0.8),
    period: '/mo',
    description: 'For individual developers and freelancers.',
    highlighted: false,
    heading: 'Everything in Free, plus:',
    features: [
      {
        text: `${SUBSCRIPTION_TIER_PROJECTS.basic} projects`,
        tip: 'Enough for client work plus side projects',
      },
      {
        text: `${SUBSCRIPTION_TIER_CREDITS.basic}/mo credits`,
        tip: 'Monthly credits that roll with your billing cycle',
      },
      {
        text: 'Bring your own keys',
        tip: 'Use your own API keys for unlimited AI at provider rates',
      },
      {
        text: 'Custom model providers',
        tip: 'Connect any OpenAI-compatible endpoint or self-hosted model',
      },
      { text: 'OpenRouter support', tip: 'Access 200+ models through your OpenRouter account' },
      { text: 'Email support (48hr)', tip: 'Direct email with 48-hour response time' },
    ],
  },
  {
    tier: 'pro',
    num: '03',
    name: 'Pro',
    monthlyPrice: SUBSCRIPTION_TIER_PRICES.pro,
    annualMonthlyPrice: Math.round(SUBSCRIPTION_TIER_PRICES.pro * 0.8),
    annualTotal: Math.round(SUBSCRIPTION_TIER_PRICES.pro * 12 * 0.8),
    period: '/mo',
    description: 'For professionals and small teams.',
    highlighted: true,
    heading: 'Everything in Basic, plus:',
    features: [
      {
        text: `${SUBSCRIPTION_TIER_PROJECTS.pro} projects`,
        tip: 'Full project portfolio for a small team',
      },
      {
        text: `${SUBSCRIPTION_TIER_CREDITS.pro}/mo credits`,
        tip: 'Monthly credits that roll with your billing cycle',
      },
      { text: 'Email support (24hr)', tip: 'Direct email with 24-hour response time' },
    ],
  },
  {
    tier: 'ultra',
    num: '04',
    name: 'Ultra',
    monthlyPrice: SUBSCRIPTION_TIER_PRICES.ultra,
    annualMonthlyPrice: Math.round(SUBSCRIPTION_TIER_PRICES.ultra * 0.8),
    annualTotal: Math.round(SUBSCRIPTION_TIER_PRICES.ultra * 12 * 0.8),
    period: '/mo',
    description: 'For teams replacing agency spend.',
    highlighted: false,
    heading: 'Everything in Pro, plus:',
    features: [
      {
        text: `${SUBSCRIPTION_TIER_PROJECTS.ultra} projects`,
        tip: 'Full capacity for an entire product portfolio',
      },
      {
        text: `${SUBSCRIPTION_TIER_CREDITS.ultra}/mo credits`,
        tip: 'Monthly credits that roll with your billing cycle',
      },
      { text: 'Priority support + chat', tip: 'Priority email within 12 hours plus live chat' },
    ],
  },
];

/* ── InfoTip tooltip ── */
function InfoTip({ tip, highlighted }: { tip: string; highlighted: boolean }) {
  return (
    <span className="relative group/tip shrink-0 cursor-pointer z-20">
      <svg
        className={`w-3.5 h-3.5 transition-colors ${
          highlighted
            ? 'text-white/40 group-hover/tip:text-white/80'
            : 'text-[var(--text)]/30 group-hover/tip:text-[var(--text)]/60'
        }`}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="12" cy="12" r="10" />
        <path d="M12 16v-4" />
        <path d="M12 8h.01" />
      </svg>
      <span className="pointer-events-none opacity-0 group-hover/tip:opacity-100 group-hover/tip:pointer-events-auto group-hover/tip:translate-y-0 translate-y-1 transition-all duration-200 absolute bottom-[calc(100%+10px)] right-0 sm:left-1/2 sm:right-auto sm:-translate-x-1/2 bg-[var(--surface)] border border-[var(--primary)] text-[var(--text)] text-[11px] leading-snug px-2.5 py-2 rounded-md shadow-lg shadow-black/30 whitespace-normal w-48 z-[999]">
        {tip}
        <span className="absolute top-full right-3 sm:right-auto sm:left-1/2 sm:-translate-x-1/2 border-[5px] border-transparent border-t-[var(--primary)]" />
      </span>
    </span>
  );
}

/* ── Animation variants ── */
const modalOverlay: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.2 } },
  exit: { opacity: 0, transition: { duration: 0.15 } },
};

const modalContent: Variants = {
  hidden: { opacity: 0, y: 20, scale: 0.98 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] },
  },
  exit: { opacity: 0, y: 10, scale: 0.98, transition: { duration: 0.15 } },
};

const stagger: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.07, delayChildren: 0.15 } },
};

const cardUp: Variants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] } },
};

/* ── Plan Selection Modal ── */
interface PlanSelectionModalProps {
  currentTier: SubscriptionTier;
  onSelect: (tier: SubscriptionTier, billingInterval: 'monthly' | 'annual') => void;
  onClose: () => void;
}

function PlanSelectionModal({ currentTier, onSelect, onClose }: PlanSelectionModalProps) {
  const [isAnnual, setIsAnnual] = useState(false);
  const tierOrder = { free: 0, basic: 1, pro: 2, ultra: 3 };

  return (
    <AnimatePresence>
      <motion.div
        key="plan-modal-overlay"
        variants={modalOverlay}
        initial="hidden"
        animate="visible"
        exit="exit"
        className="fixed inset-0 z-50 flex items-start sm:items-center justify-center bg-black/60 backdrop-blur-sm overflow-y-auto"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
      >
        <motion.div
          variants={modalContent}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="bg-[var(--bg-dark,var(--surface))] border border-[var(--border-color)] rounded-[10px] w-full max-w-5xl mx-2 sm:mx-4 my-4 sm:my-8"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 sm:px-6 pt-5 sm:pt-6 pb-4">
            <div>
              <p className="text-[11px] text-[var(--text)]/40 uppercase tracking-widest mb-1">
                Choose Your Plan
              </p>
              <h2 className="text-xl sm:text-2xl font-medium text-[var(--text)]">
                Tesslate Pricing
              </h2>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-white/10 rounded-lg transition-colors"
              aria-label="Close"
            >
              <svg
                className="w-5 h-5 text-[var(--text)]/60"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Billing toggle */}
          <div className="flex items-center justify-center gap-3 px-5 sm:px-6 pb-5">
            <span
              className={`text-sm font-medium ${!isAnnual ? 'text-[var(--text)]' : 'text-[var(--text)]/50'}`}
            >
              Monthly
            </span>
            <button
              onClick={() => setIsAnnual((prev) => !prev)}
              className={`relative w-11 h-[22px] rounded-full transition-colors ${isAnnual ? 'bg-[var(--primary)]' : 'bg-white/20'}`}
              aria-label="Toggle annual billing"
            >
              <span
                className={`absolute top-[2px] left-[2px] w-[18px] h-[18px] rounded-full bg-white transition-transform ${isAnnual ? 'translate-x-[22px]' : ''}`}
              />
            </button>
            <span
              className={`text-sm font-medium ${isAnnual ? 'text-[var(--text)]' : 'text-[var(--text)]/50'}`}
            >
              Annual
              <span className="ml-1.5 text-[var(--primary)] text-xs font-semibold">Save 20%</span>
            </span>
          </div>

          {/* Cards grid */}
          <div className="px-3 sm:px-6 pb-5 sm:pb-6">
            <motion.div
              variants={stagger}
              initial="hidden"
              animate="visible"
              className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3 items-stretch"
            >
              {planDefs.map((plan) => {
                const price = isAnnual ? plan.annualMonthlyPrice : plan.monthlyPrice;
                const isFree = plan.monthlyPrice === 0;
                const isCurrent = plan.tier === currentTier;
                const isDowngrade = tierOrder[plan.tier] < tierOrder[currentTier];
                const isUpgrade = tierOrder[plan.tier] > tierOrder[currentTier];

                return (
                  <motion.div
                    key={plan.tier}
                    variants={cardUp}
                    className={`relative rounded-[10px] overflow-visible grid grid-rows-[auto_1fr_auto] min-h-[380px] sm:min-h-[420px] ${
                      plan.highlighted
                        ? 'bg-[var(--primary)] text-white'
                        : isCurrent
                          ? 'bg-[var(--surface)] border-2 border-[var(--primary)]'
                          : 'bg-[var(--surface)] border border-[var(--border-color)]'
                    }`}
                  >
                    {/* Current plan badge */}
                    {isCurrent && (
                      <div className="absolute -top-2.5 left-1/2 -translate-x-1/2 px-2.5 py-0.5 bg-[var(--primary)] text-white text-[10px] font-semibold uppercase tracking-wider rounded-full whitespace-nowrap">
                        Current
                      </div>
                    )}

                    {/* ── Top ── */}
                    <div
                      className={`px-4 pt-4 pb-3 border-b ${plan.highlighted ? 'border-dashed border-white/30' : 'border-dashed border-[var(--border-color)]'}`}
                    >
                      <span
                        className={`block text-[10px] font-mono tracking-widest mb-2 ${plan.highlighted ? 'text-white/50' : 'text-[var(--primary)]'}`}
                      >
                        {plan.num}
                      </span>

                      <div className="flex items-baseline justify-between gap-2">
                        <h3 className="text-2xl sm:text-[28px] font-medium leading-none">
                          {plan.name}
                        </h3>
                        <div className="flex items-baseline gap-1 whitespace-nowrap">
                          <span className="text-2xl sm:text-[28px] font-medium leading-none">
                            {isFree ? '$0' : `$${price}`}
                          </span>
                          <span
                            className={`text-[10px] uppercase ${plan.highlighted ? 'text-white/50' : 'text-[var(--text)]/40'}`}
                          >
                            {isFree ? '/forever' : '/mo'}
                          </span>
                        </div>
                      </div>

                      <p
                        className={`text-xs mt-1.5 min-h-[32px] leading-relaxed ${plan.highlighted ? 'text-white/70' : 'text-[var(--text)]/50'}`}
                      >
                        {plan.description}
                      </p>

                      <p
                        className={`h-3.5 text-[10px] ${plan.highlighted ? 'text-white/40' : 'text-[var(--text)]/25'}`}
                      >
                        {isAnnual && !isFree
                          ? `$${plan.annualTotal}/yr billed annually`
                          : !isAnnual && !isFree
                            ? 'Save 20% with annual billing'
                            : isFree
                              ? 'Free forever'
                              : '\u00A0'}
                      </p>
                    </div>

                    {/* ── Body ── */}
                    <div className="px-4 py-3">
                      <p
                        className={`text-[10px] font-semibold uppercase tracking-wider mb-2 ${plan.highlighted ? 'text-white/50' : 'text-[var(--text)]/30'}`}
                      >
                        {plan.heading}
                      </p>
                      <ul className="space-y-1.5">
                        {plan.features.map((f) => (
                          <li
                            key={f.text}
                            className="flex items-center justify-between gap-2 text-[12px] leading-snug"
                          >
                            <span
                              className={plan.highlighted ? 'text-white' : 'text-[var(--text)]/80'}
                            >
                              {f.text}
                            </span>
                            <InfoTip tip={f.tip} highlighted={plan.highlighted} />
                          </li>
                        ))}
                      </ul>
                    </div>

                    {/* ── Foot ── */}
                    <div className="px-4 pb-4 pt-1">
                      {isCurrent ? (
                        <button
                          disabled
                          className={`w-full py-2.5 rounded-lg font-medium text-center text-[11px] uppercase tracking-[0.1em] ${
                            plan.highlighted
                              ? 'bg-white/20 text-white/60 cursor-not-allowed'
                              : 'bg-white/10 text-[var(--text)]/40 cursor-not-allowed'
                          }`}
                        >
                          Current Plan
                        </button>
                      ) : isDowngrade || plan.tier === 'free' ? (
                        <button
                          disabled
                          className="w-full py-2.5 rounded-lg font-medium text-center text-[11px] uppercase tracking-[0.1em] bg-white/5 text-[var(--text)]/25 cursor-not-allowed"
                        >
                          {isDowngrade ? 'Contact Support' : 'Free Tier'}
                        </button>
                      ) : (
                        <button
                          onClick={() => {
                            onSelect(plan.tier, isAnnual ? 'annual' : 'monthly');
                            onClose();
                          }}
                          className={`w-full py-2.5 rounded-lg font-medium text-center text-[11px] uppercase tracking-[0.1em] transition-all duration-200 ${
                            plan.highlighted
                              ? 'bg-white text-[var(--primary)] hover:bg-white/90'
                              : 'bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)]'
                          }`}
                        >
                          {isUpgrade ? 'Upgrade' : 'Select'}
                        </button>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </motion.div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
