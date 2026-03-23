import { useState, useEffect, useCallback } from 'react';
import toast from 'react-hot-toast';
import { Coins, CreditCard, TrendingUp, Zap } from 'lucide-react';
import { teamsApi } from '../../lib/api';
import { useTeam } from '../../contexts/TeamContext';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';

interface TeamBilling {
  subscription_tier: string;
  total_credits: number;
  daily_credits: number;
  bundled_credits: number;
  purchased_credits: number;
  signup_bonus_credits: number;
  credits_reset_date: string | null;
  daily_credits_reset_date: string | null;
  total_spend: number;
  deployed_projects_count: number;
  support_tier: string;
}

const TIER_LABELS: Record<string, string> = {
  free: 'Free',
  basic: 'Basic',
  pro: 'Pro',
  ultra: 'Ultra',
  enterprise: 'Enterprise',
};

const TIER_COLORS: Record<string, string> = {
  free: 'text-gray-400 bg-gray-400/10',
  basic: 'text-blue-400 bg-blue-400/10',
  pro: 'text-purple-400 bg-purple-400/10',
  ultra: 'text-amber-400 bg-amber-400/10',
  enterprise: 'text-emerald-400 bg-emerald-400/10',
};

export default function TeamBillingPage() {
  const { activeTeam, can, loading: teamLoading } = useTeam();
  const [loading, setLoading] = useState(true);
  const [billing, setBilling] = useState<TeamBilling | null>(null);

  const loadBilling = useCallback(async () => {
    if (!activeTeam) return;
    try {
      const data = await teamsApi.getTeamBilling(activeTeam.slug);
      setBilling(data);
    } catch (error) {
      console.error('Failed to load billing:', error);
      toast.error('Failed to load billing information');
    } finally {
      setLoading(false);
    }
  }, [activeTeam]);

  useEffect(() => {
    if (!teamLoading && activeTeam) {
      loadBilling();
    } else if (!teamLoading && !activeTeam) {
      setLoading(false);
    }
  }, [teamLoading, activeTeam, loadBilling]);

  const canViewBilling = can('billing.view');
  const canManageBilling = can('billing.manage');

  if (loading || teamLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading billing..." size={60} />
      </div>
    );
  }

  if (!activeTeam) {
    return (
      <SettingsSection title="Team Billing" description="No team selected">
        <div className="text-center py-12 text-[var(--text-muted)]">
          <p>Select a team to view billing.</p>
        </div>
      </SettingsSection>
    );
  }

  if (!canViewBilling) {
    return (
      <SettingsSection title="Team Billing" description="Billing information for your team">
        <div className="text-center py-12 text-[var(--text-muted)]">
          <p>You do not have permission to view billing information.</p>
        </div>
      </SettingsSection>
    );
  }

  if (!billing) {
    return (
      <SettingsSection title="Team Billing" description="Billing information for your team">
        <div className="text-center py-12 text-[var(--text-muted)]">
          <p>Failed to load billing data.</p>
        </div>
      </SettingsSection>
    );
  }

  const tierLabel = TIER_LABELS[billing.subscription_tier] || billing.subscription_tier;
  const tierColor = TIER_COLORS[billing.subscription_tier] || 'text-[var(--text)] bg-white/5';

  return (
    <SettingsSection
      title="Team Billing"
      description="Manage your team's subscription and credit balance"
    >
      {/* Subscription */}
      <SettingsGroup title="Subscription">
        <SettingsItem
          label="Current Plan"
          description="Your team's active subscription tier"
          control={
            <span className={`px-4 py-1.5 rounded-lg text-sm font-semibold ${tierColor}`}>
              {tierLabel}
            </span>
          }
        />
        <SettingsItem
          label="Support Tier"
          description="Level of support included with your plan"
          control={
            <span className="text-sm text-[var(--text)] capitalize">
              {billing.support_tier}
            </span>
          }
        />
        <SettingsItem
          label="Deployed Projects"
          description="Number of currently deployed projects"
          control={
            <span className="text-sm text-[var(--text)]">
              {billing.deployed_projects_count}
            </span>
          }
        />
        {canManageBilling && (
          <div className="px-4 py-3">
            <button
              onClick={() => toast('Upgrade flow coming soon')}
              className="px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-lg text-sm font-medium transition-all flex items-center gap-2"
            >
              <Zap size={16} />
              Upgrade Plan
            </button>
          </div>
        )}
      </SettingsGroup>

      {/* Credit Balance */}
      <SettingsGroup title="Credit Balance">
        {/* Total credits card */}
        <div className="px-4 py-4">
          <div className="flex items-center gap-3 p-4 bg-[var(--primary)]/5 border border-[var(--primary)]/20 rounded-xl">
            <div className="w-12 h-12 rounded-full bg-[var(--primary)]/20 flex items-center justify-center flex-shrink-0">
              <Coins size={24} className="text-[var(--primary)]" />
            </div>
            <div>
              <p className="text-2xl font-bold text-[var(--text)]">
                {billing.total_credits.toLocaleString()}
              </p>
              <p className="text-xs text-[var(--text-muted)]">Total credits available</p>
            </div>
          </div>
        </div>

        {/* Credit breakdown */}
        <SettingsItem
          label="Daily Credits"
          description={
            billing.daily_credits_reset_date
              ? `Resets ${new Date(billing.daily_credits_reset_date).toLocaleDateString()}`
              : 'Refreshed daily'
          }
          control={
            <div className="flex items-center gap-2">
              <TrendingUp size={14} className="text-green-400" />
              <span className="text-sm font-medium text-[var(--text)]">
                {billing.daily_credits.toLocaleString()}
              </span>
            </div>
          }
        />
        <SettingsItem
          label="Bundled Credits"
          description="Included with your subscription plan"
          control={
            <span className="text-sm font-medium text-[var(--text)]">
              {billing.bundled_credits.toLocaleString()}
            </span>
          }
        />
        <SettingsItem
          label="Purchased Credits"
          description="Credits bought separately"
          control={
            <span className="text-sm font-medium text-[var(--text)]">
              {billing.purchased_credits.toLocaleString()}
            </span>
          }
        />
        <SettingsItem
          label="Bonus Credits"
          description="Signup and promotional credits"
          control={
            <span className="text-sm font-medium text-[var(--text)]">
              {billing.signup_bonus_credits.toLocaleString()}
            </span>
          }
        />

        {canManageBilling && (
          <div className="px-4 py-3">
            <button
              onClick={() => toast('Credit purchase flow coming soon')}
              className="px-4 py-2 bg-white/5 hover:bg-white/10 text-[var(--text)] border border-white/10 rounded-lg text-sm font-medium transition-all flex items-center gap-2"
            >
              <CreditCard size={16} />
              Purchase Credits
            </button>
          </div>
        )}
      </SettingsGroup>

      {/* Usage Chart Placeholder */}
      <SettingsGroup title="Usage Overview">
        <div className="px-4 py-8 text-center">
          <div className="w-16 h-16 rounded-full bg-white/5 flex items-center justify-center mx-auto mb-3">
            <TrendingUp size={28} className="text-[var(--text-muted)]" />
          </div>
          <p className="text-sm text-[var(--text-muted)]">
            Usage charts coming soon
          </p>
          <p className="text-xs text-[var(--text)]/40 mt-1">
            Track credit consumption, agent usage, and deployment hours
          </p>
        </div>
      </SettingsGroup>
    </SettingsSection>
  );
}
