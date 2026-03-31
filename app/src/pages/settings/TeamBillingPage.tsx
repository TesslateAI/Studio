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
  free: 'text-[var(--text-muted)] bg-[var(--surface)]',
  basic: 'text-[var(--text)] bg-[var(--surface)]',
  pro: 'text-[var(--primary)] bg-[var(--primary)]/10',
  ultra: 'text-[var(--primary)] bg-[var(--primary)]/10',
  enterprise: 'text-[var(--status-success)] bg-[var(--status-success)]/10',
};

export default function TeamBillingPage() {
  const { activeTeam, can, loading: teamLoading, teamSwitchKey } = useTeam();
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
  const tierColor = TIER_COLORS[billing.subscription_tier] || 'text-[var(--text)] bg-[var(--surface)]';

  return (
    <div key={teamSwitchKey} style={{ animation: 'fade-in 0.25s ease-out' }}>
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
            <span className={`px-4 py-1.5 rounded-[var(--radius-small)] text-xs font-medium ${tierColor}`}>
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
              className="btn btn-filled flex items-center gap-2"
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
          <div className="flex items-center gap-3 p-4 bg-[var(--primary)]/5 border border-[var(--primary)]/20 rounded-[var(--radius)]">
            <div className="w-10 h-10 rounded-[var(--radius-medium)] bg-[var(--primary)]/10 flex items-center justify-center flex-shrink-0">
              <Coins size={20} className="text-[var(--primary)]" />
            </div>
            <div>
              <p className="text-lg font-semibold text-[var(--text)]">
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
              <TrendingUp size={14} className="text-[var(--status-success)]" />
              <span className="text-sm font-medium text-[var(--text)]">
                {billing.daily_credits.toLocaleString()}
              </span>
            </div>
          }
        />
        {canManageBilling && (
          <>
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
            <div className="px-4 py-3">
              <button
                onClick={() => toast('Credit purchase flow coming soon')}
                className="btn flex items-center gap-2"
              >
                <CreditCard size={16} />
                Purchase Credits
              </button>
            </div>
          </>
        )}
      </SettingsGroup>

      {/* Usage Chart Placeholder */}
      <SettingsGroup title="Usage Overview">
        <div className="px-4 py-8 text-center">
          <div className="w-12 h-12 rounded-[var(--radius)] bg-[var(--surface)] flex items-center justify-center mx-auto mb-3">
            <TrendingUp size={28} className="text-[var(--text-muted)]" />
          </div>
          <p className="text-sm text-[var(--text-muted)]">
            Usage charts coming soon
          </p>
          <p className="text-xs text-[var(--text-subtle)] mt-1">
            Track credit consumption, agent usage, and deployment hours
          </p>
        </div>
      </SettingsGroup>
    </SettingsSection>
    </div>
  );
}
