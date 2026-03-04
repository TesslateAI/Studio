import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Coins, TrendingUp } from 'lucide-react';
import { billingApi } from '../../lib/api';
import toast from 'react-hot-toast';
import type { SubscriptionTier } from '../../types/billing';
import { SUBSCRIPTION_TIER_CREDITS } from '../../types/billing';

interface OutOfCreditsModalProps {
  open: boolean;
  onClose: () => void;
  tier?: SubscriptionTier;
  creditsResetDate?: string;
}

export function OutOfCreditsModal({
  open,
  onClose,
  tier = 'free',
  creditsResetDate,
}: OutOfCreditsModalProps) {
  const navigate = useNavigate();
  const [purchasing, setPurchasing] = useState<string | null>(null);

  if (!open) return null;

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

  const handleUpgrade = () => {
    onClose();
    navigate('/settings/billing');
  };

  const daysUntilReset = creditsResetDate
    ? Math.ceil((new Date(creditsResetDate).getTime() - Date.now()) / (1000 * 60 * 60 * 24))
    : null;

  const monthlyAllowance = SUBSCRIPTION_TIER_CREDITS[tier];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-[var(--surface)] border border-white/10 rounded-2xl max-w-md w-full overflow-hidden">
        {/* Header */}
        <div className="p-6 text-center border-b border-white/10">
          <div className="w-16 h-16 mx-auto mb-4 bg-red-500/20 rounded-full flex items-center justify-center">
            <Coins className="w-8 h-8 text-red-400" />
          </div>
          <h2 className="text-xl font-bold text-[var(--text)]">Out of Credits</h2>
          <p className="text-sm text-[var(--text)]/60 mt-2">
            You've used all your available credits. Add more to continue using AI features.
          </p>
        </div>

        {/* Options */}
        <div className="p-6 space-y-4">
          {/* Quick Purchase Options */}
          <div>
            <h3 className="text-sm font-medium text-[var(--text)] mb-3">Add Credits</h3>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => handlePurchaseCredits('small')}
                disabled={purchasing !== null}
                className="p-4 bg-white/5 border border-white/10 rounded-xl hover:bg-white/10 transition-colors text-center disabled:opacity-50"
              >
                <div className="text-lg font-bold text-[var(--text)]">+500</div>
                <div className="text-sm text-[var(--text)]/60">$5</div>
              </button>
              <button
                onClick={() => handlePurchaseCredits('medium')}
                disabled={purchasing !== null}
                className="p-4 bg-[var(--primary)]/20 border border-[var(--primary)]/30 rounded-xl hover:bg-[var(--primary)]/30 transition-colors text-center disabled:opacity-50"
              >
                <div className="text-lg font-bold text-[var(--primary)]">+1000</div>
                <div className="text-sm text-[var(--text)]/60">$10</div>
              </button>
            </div>
          </div>

          {/* Upgrade Option */}
          {tier !== 'ultra' && (
            <div>
              <h3 className="text-sm font-medium text-[var(--text)] mb-3">Or Upgrade Your Plan</h3>
              <button
                onClick={handleUpgrade}
                className="w-full p-4 bg-white/5 border border-white/10 rounded-xl hover:bg-white/10 transition-colors flex items-center justify-between"
              >
                <div className="flex items-center gap-3">
                  <TrendingUp className="w-5 h-5 text-[var(--primary)]" />
                  <div className="text-left">
                    <div className="text-sm font-medium text-[var(--text)]">Upgrade Plan</div>
                    <div className="text-xs text-[var(--text)]/60">Get more monthly credits</div>
                  </div>
                </div>
                <span className="text-[var(--text)]/40">→</span>
              </button>
            </div>
          )}

          {/* Wait for Reset */}
          {tier !== 'free' && daysUntilReset !== null && daysUntilReset > 0 && (
            <div className="text-center pt-2 border-t border-white/10">
              <p className="text-sm text-[var(--text)]/50">
                Your bundled credits ({monthlyAllowance.toLocaleString()}) will reset in{' '}
                {daysUntilReset} day{daysUntilReset !== 1 ? 's' : ''}
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-white/10 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-[var(--text)]/60 hover:text-[var(--text)] transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
