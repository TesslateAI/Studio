import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { billingApi } from '../../lib/api';
import type {
  SubscriptionResponse,
  CreditBalanceResponse,
  SubscriptionTier,
} from '../../types/billing';
import { SUBSCRIPTION_TIER_LABELS, isUnlimitedProjects } from '../../types/billing';

interface SubscriptionStatusProps {
  compact?: boolean;
  showCredits?: boolean;
}

const SubscriptionStatus: React.FC<SubscriptionStatusProps> = ({
  compact = false,
  showCredits = true,
}) => {
  const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
  const [credits, setCredits] = useState<CreditBalanceResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);

      const [subRes, creditsRes] = await Promise.all([
        billingApi.getSubscription(),
        showCredits ? billingApi.getCreditsBalance() : Promise.resolve(null),
      ]);

      setSubscription(subRes);
      if (showCredits && creditsRes) {
        setCredits(creditsRes);
      }
    } catch (err) {
      console.error('Failed to load subscription status:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center space-x-2">
        <div className="animate-pulse bg-white/10 h-6 w-20 rounded"></div>
      </div>
    );
  }

  if (!subscription) {
    return null;
  }

  const tier = subscription.tier as SubscriptionTier;
  const isPaid = tier !== 'free';
  const totalCredits = credits?.total_credits || 0;

  // Tier badge colors
  const tierColors: Record<SubscriptionTier, string> = {
    free: 'text-[var(--text)]/60',
    basic: 'text-blue-400',
    pro: 'text-yellow-400',
    ultra: 'text-purple-400',
  };

  if (compact) {
    return (
      <Link
        to="/settings/billing"
        className="flex items-center space-x-2 px-3 py-1.5 rounded-lg hover:bg-white/5 transition"
      >
        <div className={`flex items-center space-x-1.5 ${tierColors[tier]}`}>
          {isPaid ? (
            <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
              <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
            </svg>
          ) : (
            <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
              <path
                fillRule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-11a1 1 0 10-2 0v2H7a1 1 0 100 2h2v2a1 1 0 102 0v-2h2a1 1 0 100-2h-2V7z"
                clipRule="evenodd"
              />
            </svg>
          )}
          <span className="text-sm font-medium">{SUBSCRIPTION_TIER_LABELS[tier]}</span>
        </div>

        {showCredits && credits && (
          <div className="text-sm text-[var(--text)]/60 border-l border-white/10 pl-2">
            🎫 {totalCredits.toLocaleString()}
          </div>
        )}
      </Link>
    );
  }

  return (
    <div className="bg-[var(--surface)] rounded-xl border border-white/10 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold text-[var(--text)]">Subscription</h3>
        <Link
          to="/settings/billing"
          className="text-sm text-[var(--primary)] hover:text-[var(--primary-hover)] font-medium"
        >
          Manage
        </Link>
      </div>

      <div className="space-y-3">
        {/* Tier Badge */}
        <div className="flex items-center space-x-2">
          <div
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-full ${
              isPaid
                ? 'bg-[var(--primary)]/20 text-[var(--primary)]'
                : 'bg-white/5 text-[var(--text)]/60'
            }`}
          >
            {isPaid ? (
              <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
              </svg>
            ) : (
              <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-11a1 1 0 10-2 0v2H7a1 1 0 100 2h2v2a1 1 0 102 0v-2h2a1 1 0 100-2h-2V7z"
                  clipRule="evenodd"
                />
              </svg>
            )}
            <span className="font-semibold">{SUBSCRIPTION_TIER_LABELS[tier]}</span>
          </div>
        </div>

        {/* Limits */}
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="bg-white/5 rounded-lg p-2">
            <div className="text-[var(--text)]/50 text-xs">Projects</div>
            <div className="font-semibold text-[var(--text)]">
              {isUnlimitedProjects(subscription.max_projects) ? '∞' : subscription.max_projects}
            </div>
          </div>
          <div className="bg-white/5 rounded-lg p-2">
            <div className="text-[var(--text)]/50 text-xs">Deploys</div>
            <div className="font-semibold text-[var(--text)]">{subscription.max_deploys}</div>
          </div>
        </div>

        {/* Credits */}
        {showCredits && credits && (
          <div className="border-t border-white/10 pt-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-[var(--text)]/60">Credits</span>
              <span className="text-lg font-semibold text-[var(--text)]">
                {totalCredits.toLocaleString()}
              </span>
            </div>
            <Link
              to="/settings/billing"
              className="mt-2 block text-center text-sm text-[var(--primary)] hover:text-[var(--primary-hover)] font-medium"
            >
              Add Credits
            </Link>
          </div>
        )}

        {/* Upgrade CTA */}
        {!isPaid && (
          <Link
            to="/settings/billing"
            className="block w-full py-2 px-4 bg-[var(--primary)] text-white text-center rounded-lg hover:bg-[var(--primary-hover)] transition font-medium text-sm"
          >
            Upgrade Plan
          </Link>
        )}
      </div>
    </div>
  );
};

export default SubscriptionStatus;
