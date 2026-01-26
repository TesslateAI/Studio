import { Warning } from '@phosphor-icons/react';
import { SettingsSection } from '../../components/settings';

export default function ApiKeysSettings() {
  return (
    <SettingsSection
      title="API Keys"
      description="Manage your LLM provider API keys (OpenRouter, Anthropic, OpenAI, etc.)"
    >
      <div className="p-8 bg-[var(--surface)] border border-white/10 rounded-xl text-center">
        <Warning size={48} className="text-yellow-400 mx-auto mb-4" />
        <h3 className="text-lg font-semibold text-[var(--text)] mb-2">Coming Soon</h3>
        <p className="text-[var(--text)]/60 text-sm max-w-md mx-auto">
          API key management is coming soon! You'll be able to add your own OpenRouter,
          Anthropic, and OpenAI API keys to use with your projects.
        </p>
      </div>
    </SettingsSection>
  );
}
