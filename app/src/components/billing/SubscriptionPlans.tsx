import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, X, Sparkles, Zap, Crown, Star } from 'lucide-react';
import { billingApi } from '../../lib/api';
import toast from 'react-hot-toast';
import type { SubscriptionTier } from '../../types/billing';
import {
  SUBSCRIPTION_TIER_LABELS,
  SUBSCRIPTION_TIER_PRICES,
  SUBSCRIPTION_TIER_CREDITS,
  SUBSCRIPTION_TIER_PROJECTS,
  SUBSCRIPTION_TIER_DEPLOYS,
} from '../../types/billing';

interface TierFeature {
  name: string;
  free: boolean | string;
  basic: boolean | string;
  pro: boolean | string;
  ultra: boolean | string;
}

const SubscriptionPlans: React.FC = () => {
  const navigate = useNavigate();
  const [currentTier, setCurrentTier] = useState<SubscriptionTier>('free');
  const [loading, setLoading] = useState(true);
  const [subscribing, setSubscribing] = useState<SubscriptionTier | null>(null);

  useEffect(() => {
    loadSubscription();
  }, []);

  const loadSubscription = async () => {
    try {
      setLoading(true);
      const subscription = await billingApi.getSubscription();
      setCurrentTier(subscription.tier as SubscriptionTier);
    } catch (err) {
      console.error('Failed to load subscription:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectTier = async (tier: SubscriptionTier) => {
    if (tier === currentTier || tier === 'free') return;

    try {
      setSubscribing(tier);
      const response = await billingApi.subscribe(tier);
      if (response.url) {
        window.location.href = response.url;
      }
    } catch (err) {
      console.error('Failed to start subscription:', err);
      toast.error('Failed to start subscription');
      setSubscribing(null);
    }
  };

  const handleManageSubscription = async () => {
    try {
      const response = await billingApi.getCustomerPortal();
      if (response.url) {
        window.location.href = response.url;
      }
    } catch (err) {
      console.error('Failed to open customer portal:', err);
      toast.error('Failed to open billing portal');
    }
  };

  const features: TierFeature[] = [
    {
      name: 'Monthly Credits',
      free: `${SUBSCRIPTION_TIER_CREDITS.free.toLocaleString()}`,
      basic: `${SUBSCRIPTION_TIER_CREDITS.basic.toLocaleString()}`,
      pro: `${SUBSCRIPTION_TIER_CREDITS.pro.toLocaleString()}`,
      ultra: `${SUBSCRIPTION_TIER_CREDITS.ultra.toLocaleString()}`,
    },
    {
      name: 'Active Projects',
      free: `${SUBSCRIPTION_TIER_PROJECTS.free}`,
      basic: `${SUBSCRIPTION_TIER_PROJECTS.basic}`,
      pro: `${SUBSCRIPTION_TIER_PROJECTS.pro}`,
      ultra: 'Unlimited',
    },
    {
      name: 'Deploy Slots',
      free: `${SUBSCRIPTION_TIER_DEPLOYS.free}`,
      basic: `${SUBSCRIPTION_TIER_DEPLOYS.basic}`,
      pro: `${SUBSCRIPTION_TIER_DEPLOYS.pro}`,
      ultra: `${SUBSCRIPTION_TIER_DEPLOYS.ultra}`,
    },
    {
      name: 'Bring Your Own Key (BYOK)',
      free: false,
      basic: false,
      pro: true,
      ultra: true,
    },
    {
      name: 'Priority Support',
      free: false,
      basic: false,
      pro: true,
      ultra: true,
    },
    {
      name: 'Marketplace Access',
      free: true,
      basic: true,
      pro: true,
      ultra: true,
    },
    {
      name: 'Agent Creation',
      free: true,
      basic: true,
      pro: true,
      ultra: true,
    },
    {
      name: 'Credit Purchases',
      free: true,
      basic: true,
      pro: true,
      ultra: true,
    },
  ];

  const tierIcons: Record<SubscriptionTier, React.ReactNode> = {
    free: <Zap className="w-6 h-6" />,
    basic: <Star className="w-6 h-6" />,
    pro: <Sparkles className="w-6 h-6" />,
    ultra: <Crown className="w-6 h-6" />,
  };

  const tierColors: Record<SubscriptionTier, string> = {
    free: 'border-white/10',
    basic: 'border-blue-500/50',
    pro: 'border-yellow-500/50',
    ultra: 'border-purple-500/50',
  };

  const tierBadgeColors: Record<SubscriptionTier, string> = {
    free: 'bg-white/10 text-[var(--text)]/60',
    basic: 'bg-blue-500/20 text-blue-400',
    pro: 'bg-yellow-500/20 text-yellow-400',
    ultra: 'bg-purple-500/20 text-purple-400',
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[var(--primary)]"></div>
      </div>
    );
  }

  const tiers: SubscriptionTier[] = ['free', 'basic', 'pro', 'ultra'];

  return (
    <div className="py-8 px-4">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-3xl font-bold text-[var(--text)] mb-4">Choose Your Plan</h1>
          <p className="text-lg text-[var(--text)]/60">
            Start free, upgrade when you need more power
          </p>
        </div>

        {/* Pricing Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
          {tiers.map((tier) => {
            const isCurrentTier = tier === currentTier;
            const isPopular = tier === 'pro';

            return (
              <div
                key={tier}
                className={`relative bg-[var(--surface)] rounded-2xl border-2 ${tierColors[tier]} p-6 ${
                  isPopular ? 'ring-2 ring-[var(--primary)]' : ''
                }`}
              >
                {isPopular && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-[var(--primary)] text-white text-xs font-bold px-3 py-1 rounded-full">
                    POPULAR
                  </div>
                )}

                {/* Tier Header */}
                <div className="text-center mb-6">
                  <div className={`inline-flex p-3 rounded-xl ${tierBadgeColors[tier]} mb-3`}>
                    {tierIcons[tier]}
                  </div>
                  <h2 className="text-xl font-bold text-[var(--text)]">
                    {SUBSCRIPTION_TIER_LABELS[tier]}
                  </h2>
                  <div className="mt-2">
                    <span className="text-3xl font-bold text-[var(--text)]">
                      ${SUBSCRIPTION_TIER_PRICES[tier]}
                    </span>
                    {tier !== 'free' && <span className="text-[var(--text)]/50">/mo</span>}
                  </div>
                  <div className="text-sm text-[var(--text)]/50 mt-1">
                    {SUBSCRIPTION_TIER_CREDITS[tier].toLocaleString()} credits/month
                  </div>
                </div>

                {/* Features */}
                <ul className="space-y-3 mb-6">
                  {features.map((feature, idx) => {
                    const value = feature[tier];
                    const hasFeature = value === true || typeof value === 'string';

                    return (
                      <li key={idx} className="flex items-start gap-2">
                        {hasFeature ? (
                          <Check className="w-4 h-4 text-green-400 mt-0.5 flex-shrink-0" />
                        ) : (
                          <X className="w-4 h-4 text-[var(--text)]/30 mt-0.5 flex-shrink-0" />
                        )}
                        <div>
                          <span
                            className={`text-sm ${hasFeature ? 'text-[var(--text)]' : 'text-[var(--text)]/40'}`}
                          >
                            {feature.name}
                          </span>
                          {typeof value === 'string' && (
                            <span className="text-sm text-[var(--primary)] ml-1">({value})</span>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>

                {/* Action Button */}
                {isCurrentTier ? (
                  tier === 'free' ? (
                    <button
                      disabled
                      className="w-full py-3 px-4 bg-white/5 text-[var(--text)]/50 font-medium rounded-xl cursor-not-allowed"
                    >
                      Current Plan
                    </button>
                  ) : (
                    <button
                      onClick={handleManageSubscription}
                      className="w-full py-3 px-4 bg-white/5 border border-white/10 text-[var(--text)] font-medium rounded-xl hover:bg-white/10 transition-colors"
                    >
                      Manage Subscription
                    </button>
                  )
                ) : tier === 'free' ? (
                  <button
                    disabled
                    className="w-full py-3 px-4 bg-white/5 text-[var(--text)]/50 font-medium rounded-xl cursor-not-allowed"
                  >
                    {currentTier !== 'free' ? 'Contact Support to Downgrade' : 'Current Plan'}
                  </button>
                ) : (
                  <button
                    onClick={() => handleSelectTier(tier)}
                    disabled={subscribing !== null}
                    className={`w-full py-3 px-4 font-medium rounded-xl transition-colors disabled:opacity-50 ${
                      isPopular
                        ? 'bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)]'
                        : 'bg-white/5 border border-white/10 text-[var(--text)] hover:bg-white/10'
                    }`}
                  >
                    {subscribing === tier
                      ? 'Processing...'
                      : `Upgrade to ${SUBSCRIPTION_TIER_LABELS[tier]}`}
                  </button>
                )}
              </div>
            );
          })}
        </div>

        {/* FAQ Section */}
        <div className="bg-[var(--surface)] rounded-2xl border border-white/10 p-8">
          <h3 className="text-xl font-bold text-[var(--text)] mb-6">Frequently Asked Questions</h3>

          <div className="grid md:grid-cols-2 gap-6">
            <div>
              <h4 className="font-semibold text-[var(--text)] mb-2">Can I cancel anytime?</h4>
              <p className="text-sm text-[var(--text)]/60">
                Yes! You can cancel your subscription at any time. Your access will continue until
                the end of your billing period.
              </p>
            </div>

            <div>
              <h4 className="font-semibold text-[var(--text)] mb-2">What are credits?</h4>
              <p className="text-sm text-[var(--text)]/60">
                Credits are used for AI usage. Each plan includes monthly credits that reset. You
                can also purchase additional credits that never expire.
              </p>
            </div>

            <div>
              <h4 className="font-semibold text-[var(--text)] mb-2">What is BYOK?</h4>
              <p className="text-sm text-[var(--text)]/60">
                Bring Your Own Key (BYOK) lets Pro and Ultra users use their own API keys from
                providers like OpenRouter, Anthropic, and OpenAI.
              </p>
            </div>

            <div>
              <h4 className="font-semibold text-[var(--text)] mb-2">
                How do I upgrade or downgrade?
              </h4>
              <p className="text-sm text-[var(--text)]/60">
                You can upgrade anytime from this page. To downgrade, manage your subscription
                through the billing portal or contact support.
              </p>
            </div>
          </div>
        </div>

        {/* Back to Settings */}
        <div className="text-center mt-8">
          <button
            onClick={() => navigate('/settings/billing')}
            className="text-sm text-[var(--text)]/50 hover:text-[var(--text)] transition-colors"
          >
            ← Back to Billing Settings
          </button>
        </div>
      </div>
    </div>
  );
};

export default SubscriptionPlans;
