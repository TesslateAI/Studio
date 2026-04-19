import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { X, Check, Sparkles, Star, Crown } from 'lucide-react';
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

interface UpgradeModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentTier?: SubscriptionTier;
  reason?: 'projects' | 'deploys' | 'features' | 'credits' | 'byok' | 'general';
  title?: string;
  message?: string;
  suggestedTier?: SubscriptionTier;
}

const UpgradeModal: React.FC<UpgradeModalProps> = ({
  isOpen,
  onClose,
  currentTier = 'free',
  reason = 'general',
  title,
  message,
  suggestedTier,
}) => {
  const [selectedTier, setSelectedTier] = useState<SubscriptionTier>(suggestedTier || 'pro');
  const [upgrading, setUpgrading] = useState(false);

  if (!isOpen) return null;

  const handleUpgrade = async () => {
    if (selectedTier === 'free' || selectedTier === currentTier) return;

    try {
      setUpgrading(true);
      const response = await billingApi.subscribe(selectedTier);

      if (response.url) {
        window.location.href = response.url;
      } else {
        throw new Error('No checkout URL received');
      }
    } catch (err) {
      console.error('Failed to start subscription:', err);
      toast.error('Failed to start subscription');
      setUpgrading(false);
    }
  };

  // Reason-specific content
  const getContent = () => {
    switch (reason) {
      case 'projects':
        return {
          defaultTitle: 'Project Limit Reached',
          defaultMessage: `You've reached your project limit. Upgrade to create more projects.`,
        };
      case 'deploys':
        return {
          defaultTitle: 'Deploy Limit Reached',
          defaultMessage: `You've reached your deploy limit. Upgrade to deploy more projects.`,
        };
      case 'credits':
        return {
          defaultTitle: 'More Credits Needed',
          defaultMessage: 'Upgrade your plan for more monthly credits.',
        };
      case 'byok':
        return {
          defaultTitle: 'BYOK Requires a Paid Plan',
          defaultMessage:
            'Bring Your Own Key (BYOK) is available on all paid plans (Basic, Pro, and Ultra).',
        };
      case 'features':
        return {
          defaultTitle: 'Premium Feature',
          defaultMessage: 'This feature requires a higher tier subscription.',
        };
      default:
        return {
          defaultTitle: 'Upgrade Your Plan',
          defaultMessage: 'Unlock more projects, credits, and premium features.',
        };
    }
  };

  const content = getContent();
  const displayTitle = title || content.defaultTitle;
  const displayMessage = message || content.defaultMessage;

  // Available tiers to upgrade to (exclude current and free)
  const upgradeTiers: SubscriptionTier[] = ['basic', 'pro', 'ultra'].filter(
    (t) => t !== currentTier
  ) as SubscriptionTier[];

  const tierIcons: Record<SubscriptionTier, React.ReactNode> = {
    free: null,
    basic: <Star className="w-5 h-5" />,
    pro: <Sparkles className="w-5 h-5" />,
    ultra: <Crown className="w-5 h-5" />,
  };

  const tierColors: Record<SubscriptionTier, string> = {
    free: '',
    basic: 'border-blue-500/50 bg-blue-500/10',
    pro: 'border-yellow-500/50 bg-yellow-500/10',
    ultra: 'border-purple-500/50 bg-purple-500/10',
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-[var(--surface)] border border-white/10 rounded-2xl max-w-lg w-full overflow-hidden">
        {/* Header */}
        <div className="p-6 border-b border-white/10">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-bold text-[var(--text)]">{displayTitle}</h2>
              <p className="text-sm text-[var(--text)]/60 mt-1">{displayMessage}</p>
            </div>
            <button
              onClick={onClose}
              className="p-2 text-[var(--text)]/40 hover:text-[var(--text)]/60 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Tier Selection */}
        <div className="p-6">
          <div className="space-y-3 mb-6">
            {upgradeTiers.map((tier) => {
              const isSelected = selectedTier === tier;
              const isRecommended = tier === 'pro';

              return (
                <button
                  key={tier}
                  onClick={() => setSelectedTier(tier)}
                  className={`relative w-full p-4 rounded-xl border-2 transition-all text-left ${
                    isSelected
                      ? tierColors[tier]
                      : 'border-white/10 bg-white/5 hover:border-white/20'
                  }`}
                >
                  {isRecommended && (
                    <div className="absolute -top-2 right-4 bg-[var(--primary)] text-white text-xs font-bold px-2 py-0.5 rounded">
                      RECOMMENDED
                    </div>
                  )}

                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div
                        className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                          isSelected
                            ? 'border-[var(--primary)] bg-[var(--primary)]'
                            : 'border-white/30'
                        }`}
                      >
                        {isSelected && <div className="w-2 h-2 bg-white rounded-full" />}
                      </div>
                      <div className="flex items-center gap-2">
                        {tierIcons[tier]}
                        <span className="font-semibold text-[var(--text)]">
                          {SUBSCRIPTION_TIER_LABELS[tier]}
                        </span>
                      </div>
                    </div>
                    <div className="text-right">
                      <span className="text-xl font-bold text-[var(--text)]">
                        ${SUBSCRIPTION_TIER_PRICES[tier]}
                      </span>
                      <span className="text-[var(--text)]/50">/mo</span>
                    </div>
                  </div>

                  {/* Tier benefits */}
                  <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
                    <div className="flex items-center gap-1 text-[var(--text)]/60">
                      <Check className="w-3 h-3 text-green-400" />
                      {SUBSCRIPTION_TIER_CREDITS[tier].toLocaleString()} credits/mo
                    </div>
                    <div className="flex items-center gap-1 text-[var(--text)]/60">
                      <Check className="w-3 h-3 text-green-400" />
                      {SUBSCRIPTION_TIER_PROJECTS[tier]} projects
                    </div>
                    <div className="flex items-center gap-1 text-[var(--text)]/60">
                      <Check className="w-3 h-3 text-green-400" />
                      {SUBSCRIPTION_TIER_DEPLOYS[tier]} deploys
                    </div>
                    <div className="flex items-center gap-1 text-[var(--text)]/60">
                      <Check className="w-3 h-3 text-green-400" />
                      BYOK enabled
                    </div>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <button
              onClick={handleUpgrade}
              disabled={upgrading || selectedTier === currentTier}
              className="flex-1 py-3 px-6 bg-[var(--primary)] text-white font-semibold rounded-xl hover:bg-[var(--primary-hover)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {upgrading ? (
                <span className="flex items-center justify-center gap-2">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                  Processing...
                </span>
              ) : (
                `Upgrade to ${SUBSCRIPTION_TIER_LABELS[selectedTier]}`
              )}
            </button>

            <Link
              to="/settings/billing"
              onClick={onClose}
              className="py-3 px-6 bg-white/5 border border-white/10 text-[var(--text)] font-medium rounded-xl hover:bg-white/10 transition-colors text-center"
            >
              View All Plans
            </Link>
          </div>

          <p className="text-xs text-center text-[var(--text)]/40 mt-4">
            Secure checkout powered by Stripe. Cancel anytime.
          </p>
        </div>
      </div>
    </div>
  );
};

export default UpgradeModal;
