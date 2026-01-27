import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Key, Lock, TrendingUp } from 'lucide-react';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';
import { billingApi } from '../../lib/api';
import type { SubscriptionTier } from '../../types/billing';

export default function ApiKeysSettings() {
  const [tier, setTier] = useState<SubscriptionTier>('free');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadSubscription();
  }, []);

  const loadSubscription = async () => {
    try {
      const subscription = await billingApi.getSubscription();
      setTier(subscription.tier as SubscriptionTier);
    } catch (err) {
      console.error('Failed to load subscription:', err);
    } finally {
      setLoading(false);
    }
  };

  const byokEnabled = tier === 'pro' || tier === 'ultra';

  if (loading) {
    return (
      <SettingsSection
        title="API Keys"
        description="Manage your LLM provider API keys (OpenRouter, Anthropic, OpenAI, etc.)"
      >
        <div className="p-8 bg-[var(--surface)] border border-white/10 rounded-xl">
          <div className="animate-pulse flex flex-col items-center gap-4">
            <div className="w-12 h-12 bg-white/10 rounded-full" />
            <div className="h-4 w-48 bg-white/10 rounded" />
            <div className="h-3 w-64 bg-white/10 rounded" />
          </div>
        </div>
      </SettingsSection>
    );
  }

  // Show upgrade prompt for Free and Basic tiers
  if (!byokEnabled) {
    return (
      <SettingsSection
        title="API Keys"
        description="Manage your LLM provider API keys (OpenRouter, Anthropic, OpenAI, etc.)"
      >
        <div className="p-8 bg-[var(--surface)] border border-white/10 rounded-xl">
          <div className="flex flex-col items-center text-center">
            <div className="w-16 h-16 bg-[var(--primary)]/20 rounded-full flex items-center justify-center mb-4">
              <Lock className="w-8 h-8 text-[var(--primary)]" />
            </div>
            <h3 className="text-lg font-semibold text-[var(--text)] mb-2">
              Bring Your Own Key (BYOK)
            </h3>
            <p className="text-[var(--text)]/60 text-sm max-w-md mb-6">
              Use your own API keys from OpenRouter, Anthropic, OpenAI, and other providers. This
              feature is available on Pro and Ultra plans.
            </p>

            {/* Benefits list */}
            <div className="w-full max-w-sm mb-6">
              <div className="space-y-3">
                <div className="flex items-center gap-3 text-left">
                  <div className="w-8 h-8 bg-white/5 rounded-lg flex items-center justify-center flex-shrink-0">
                    <Key className="w-4 h-4 text-[var(--text)]/60" />
                  </div>
                  <div>
                    <div className="text-sm font-medium text-[var(--text)]">
                      Use your own API keys
                    </div>
                    <div className="text-xs text-[var(--text)]/50">
                      OpenRouter, Anthropic, OpenAI, etc.
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3 text-left">
                  <div className="w-8 h-8 bg-white/5 rounded-lg flex items-center justify-center flex-shrink-0">
                    <TrendingUp className="w-4 h-4 text-[var(--text)]/60" />
                  </div>
                  <div>
                    <div className="text-sm font-medium text-[var(--text)]">No credit limits</div>
                    <div className="text-xs text-[var(--text)]/50">
                      Pay directly to your provider
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <Link
              to="/settings/billing"
              className="px-6 py-3 bg-[var(--primary)] text-white font-medium rounded-xl hover:bg-[var(--primary-hover)] transition-colors flex items-center gap-2"
            >
              <TrendingUp className="w-4 h-4" />
              Upgrade to Pro
            </Link>
            <p className="text-xs text-[var(--text)]/40 mt-3">Starting at $20/month</p>
          </div>
        </div>
      </SettingsSection>
    );
  }

  // Show BYOK management for Pro and Ultra tiers
  return (
    <SettingsSection
      title="API Keys"
      description="Manage your LLM provider API keys (OpenRouter, Anthropic, OpenAI, etc.)"
    >
      <SettingsGroup title="Provider Keys">
        <SettingsItem
          label="OpenRouter"
          description="Use OpenRouter for access to multiple AI models"
          control={
            <div className="flex items-center gap-2">
              <input
                type="password"
                placeholder="sk-or-..."
                disabled
                className="px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-[var(--text)] placeholder-[var(--text)]/30 w-64"
              />
              <span className="text-xs text-[var(--text)]/40">Coming soon</span>
            </div>
          }
        />

        <SettingsItem
          label="Anthropic"
          description="Use your Anthropic API key for Claude models"
          control={
            <div className="flex items-center gap-2">
              <input
                type="password"
                placeholder="sk-ant-..."
                disabled
                className="px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-[var(--text)] placeholder-[var(--text)]/30 w-64"
              />
              <span className="text-xs text-[var(--text)]/40">Coming soon</span>
            </div>
          }
        />

        <SettingsItem
          label="OpenAI"
          description="Use your OpenAI API key for GPT models"
          control={
            <div className="flex items-center gap-2">
              <input
                type="password"
                placeholder="sk-..."
                disabled
                className="px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-[var(--text)] placeholder-[var(--text)]/30 w-64"
              />
              <span className="text-xs text-[var(--text)]/40">Coming soon</span>
            </div>
          }
        />
      </SettingsGroup>

      <div className="mt-4 p-4 bg-[var(--primary)]/10 border border-[var(--primary)]/20 rounded-xl">
        <div className="flex items-start gap-3">
          <Key className="w-5 h-5 text-[var(--primary)] flex-shrink-0 mt-0.5" />
          <div>
            <h4 className="text-sm font-medium text-[var(--text)]">BYOK Feature Coming Soon</h4>
            <p className="text-sm text-[var(--text)]/60 mt-1">
              As a {tier === 'ultra' ? 'Ultra' : 'Pro'} subscriber, you'll be able to add your own
              API keys once this feature launches. Your keys will be encrypted and stored securely.
            </p>
          </div>
        </div>
      </div>
    </SettingsSection>
  );
}
