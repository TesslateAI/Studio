import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, X } from 'lucide-react';
import { billingApi } from '../../lib/api';
import type { CreditStatusResponse } from '../../types/billing';

interface LowBalanceWarningProps {
  onDismiss?: () => void;
  showUpgradeOption?: boolean;
}

export function LowBalanceWarning({ onDismiss, showUpgradeOption = true }: LowBalanceWarningProps) {
  const [status, setStatus] = useState<CreditStatusResponse | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    loadStatus();
  }, []);

  const loadStatus = async () => {
    try {
      const response = await billingApi.getCreditStatus();
      setStatus(response);
    } catch (err) {
      console.error('Failed to load credit status:', err);
    }
  };

  const handleDismiss = () => {
    setDismissed(true);
    onDismiss?.();
  };

  // Don't show if dismissed, loading, or not low balance
  if (dismissed || !status || !status.is_low) {
    return null;
  }

  return (
    <div className="bg-[var(--status-warning)]/10 border border-[var(--status-warning)]/30 rounded-xl p-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-[var(--status-warning)] flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <h4 className="text-sm font-medium text-[var(--text)]">Low Credits Balance</h4>
          <p className="text-sm text-[var(--text)]/60 mt-1">
            You have {status.total_credits.toLocaleString()} credits remaining (
            {Math.round((status.total_credits / status.monthly_allowance) * 100)}% of your monthly
            allowance).
          </p>
          <div className="flex gap-2 mt-3">
            <Link
              to="/settings/billing"
              className="px-3 py-1.5 bg-[var(--primary)] text-white text-sm font-medium rounded-lg hover:bg-[var(--primary-hover)] transition-colors"
            >
              Add Credits
            </Link>
            {showUpgradeOption && status.tier !== 'ultra' && (
              <Link
                to="/settings/billing"
                className="px-3 py-1.5 bg-white/5 border border-white/10 text-[var(--text)] text-sm font-medium rounded-lg hover:bg-white/10 transition-colors"
              >
                Upgrade Plan
              </Link>
            )}
          </div>
        </div>
        {onDismiss && (
          <button
            onClick={handleDismiss}
            className="p-1 text-[var(--text)]/40 hover:text-[var(--text)]/60 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  );
}
