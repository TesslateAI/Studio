import { useNavigate } from 'react-router-dom';
import { CreditCard, Receipt, BarChart3, ExternalLink } from 'lucide-react';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';

export default function BillingSettings() {
  const navigate = useNavigate();

  return (
    <SettingsSection
      title="Billing"
      description="Manage your subscription and payment settings"
    >
      <SettingsGroup title="Subscription">
        <SettingsItem
          label="Current plan"
          description="View and manage your subscription"
          control={
            <button
              onClick={() => navigate('/billing')}
              className="flex items-center gap-2 px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-lg text-sm font-medium transition-colors min-h-[44px]"
            >
              <CreditCard size={16} />
              View Plan
              <ExternalLink size={14} />
            </button>
          }
        />
        <SettingsItem
          label="Upgrade plan"
          description="Explore available subscription plans"
          control={
            <button
              onClick={() => navigate('/billing/plans')}
              className="flex items-center gap-2 px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-sm font-medium text-[var(--text)] hover:bg-white/10 transition-colors min-h-[44px]"
            >
              View Plans
              <ExternalLink size={14} />
            </button>
          }
        />
      </SettingsGroup>

      <SettingsGroup title="Usage & History">
        <SettingsItem
          label="Usage dashboard"
          description="View your API usage and credits"
          control={
            <button
              onClick={() => navigate('/billing/usage')}
              className="flex items-center gap-2 px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-sm font-medium text-[var(--text)] hover:bg-white/10 transition-colors min-h-[44px]"
            >
              <BarChart3 size={16} />
              View Usage
              <ExternalLink size={14} />
            </button>
          }
        />
        <SettingsItem
          label="Transaction history"
          description="View your payment history and invoices"
          control={
            <button
              onClick={() => navigate('/billing/transactions')}
              className="flex items-center gap-2 px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-sm font-medium text-[var(--text)] hover:bg-white/10 transition-colors min-h-[44px]"
            >
              <Receipt size={16} />
              View History
              <ExternalLink size={14} />
            </button>
          }
        />
      </SettingsGroup>
    </SettingsSection>
  );
}
