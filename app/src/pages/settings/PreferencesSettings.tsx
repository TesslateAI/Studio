import { useState, useEffect, useCallback } from 'react';
import toast from 'react-hot-toast';
import { Check } from 'lucide-react';
import { useTheme } from '../../theme/ThemeContext';
import { getThemePresetsByMode } from '../../theme/themePresets';
import type { ThemePreset } from '../../theme/themePresets';
import { usersApi, type UserPreferences } from '../../lib/api';
import { ToggleSwitch } from '../../components/ui/ToggleSwitch';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { useCancellableRequest } from '../../hooks/useCancellableRequest';

function ThemeCard({
  preset,
  isSelected,
  onSelect,
}: {
  preset: ThemePreset;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className={`relative flex flex-col items-start p-3 rounded-xl border transition-all text-left w-full ${
        isSelected
          ? 'border-[var(--primary)] bg-[var(--primary)]/10 ring-2 ring-[var(--primary)]/20'
          : 'border-white/10 bg-white/5 hover:bg-white/10 hover:border-white/20'
      }`}
    >
      {/* Color preview swatches */}
      <div className="flex gap-1.5 mb-2">
        {/* Primary color */}
        <div
          className="w-6 h-6 rounded-md border border-black/20"
          style={{ backgroundColor: preset.colors.primary }}
          title="Primary"
        />
        {/* Background color */}
        <div
          className="w-6 h-6 rounded-md border border-black/20"
          style={{ backgroundColor: preset.colors.background }}
          title="Background"
        />
        {/* Surface color */}
        <div
          className="w-6 h-6 rounded-md border border-black/20"
          style={{ backgroundColor: preset.colors.surface }}
          title="Surface"
        />
        {/* Accent color */}
        <div
          className="w-6 h-6 rounded-md border border-black/20"
          style={{ backgroundColor: preset.colors.accent }}
          title="Accent"
        />
      </div>

      {/* Theme name and description */}
      <div className="flex-1">
        <div className="text-sm font-medium text-[var(--text)]">{preset.name}</div>
        <div className="text-xs text-[var(--text)]/60 mt-0.5">{preset.description}</div>
      </div>

      {/* Border radius preview */}
      <div className="flex items-center gap-1 mt-2">
        <span className="text-[10px] text-[var(--text)]/40">Corners:</span>
        <div
          className="w-4 h-4 border border-[var(--text)]/30"
          style={{ borderRadius: preset.spacing.radiusMedium, backgroundColor: 'transparent' }}
        />
      </div>

      {/* Selected checkmark */}
      {isSelected && (
        <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-[var(--primary)] flex items-center justify-center">
          <Check size={12} className="text-white" />
        </div>
      )}
    </button>
  );
}

export default function PreferencesSettings() {
  const { themePresetId, setThemePreset, isLoading: themeLoading } = useTheme();
  const [loading, setLoading] = useState(true);
  const [diagramModel, setDiagramModel] = useState<string>('');
  const [savingPreference, setSavingPreference] = useState(false);

  const { dark: darkThemes, light: lightThemes } = getThemePresetsByMode();

  // Use cancellable request to prevent memory leaks on unmount
  const { execute: executeLoad } = useCancellableRequest<UserPreferences>();

  const loadPreferences = useCallback(() => {
    executeLoad(() => usersApi.getPreferences(), {
      onSuccess: (prefs) => {
        setDiagramModel(prefs.diagram_model || 'claude-3-5-sonnet-20241022');
      },
      onError: (error) => {
        console.error('Failed to load preferences:', error);
      },
      onFinally: () => setLoading(false),
    });
  }, [executeLoad]);

  useEffect(() => {
    loadPreferences();
  }, [loadPreferences]);

  const handleThemeSelect = (presetId: string) => {
    setThemePreset(presetId);
    toast.success('Theme updated');
  };

  const handleDiagramModelChange = async (model: string) => {
    setSavingPreference(true);
    try {
      await usersApi.updatePreferences({ diagram_model: model });
      setDiagramModel(model);
      toast.success('Diagram model preference updated');
    } catch (error: unknown) {
      console.error('Failed to update diagram model:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to update preference');
    } finally {
      setSavingPreference(false);
    }
  };

  if (loading || themeLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading preferences..." size={60} />
      </div>
    );
  }

  return (
    <SettingsSection title="Preferences" description="Customize your Tesslate Studio experience">
      {/* Theme Selection */}
      <SettingsGroup title="Theme">
        <div className="p-4">
          {/* Dark Themes */}
          <div className="mb-6">
            <h4 className="text-sm font-medium text-[var(--text)]/80 mb-3">Dark themes</h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {darkThemes.map((preset) => (
                <ThemeCard
                  key={preset.id}
                  preset={preset}
                  isSelected={themePresetId === preset.id}
                  onSelect={() => handleThemeSelect(preset.id)}
                />
              ))}
            </div>
          </div>

          {/* Light Themes */}
          <div>
            <h4 className="text-sm font-medium text-[var(--text)]/80 mb-3">Light themes</h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {lightThemes.map((preset) => (
                <ThemeCard
                  key={preset.id}
                  preset={preset}
                  isSelected={themePresetId === preset.id}
                  onSelect={() => handleThemeSelect(preset.id)}
                />
              ))}
            </div>
          </div>

          <p className="text-xs text-[var(--text)]/50 mt-4">
            Theme changes are automatically saved and will persist across sessions.
          </p>
        </div>
      </SettingsGroup>

      {/* AI Settings */}
      <SettingsGroup title="AI Settings">
        <SettingsItem
          label="Architecture diagram model"
          description="The AI model used for generating architecture diagrams"
          control={
            <select
              value={diagramModel}
              onChange={(e) => handleDiagramModelChange(e.target.value)}
              disabled={savingPreference}
              className="w-full sm:w-48 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)] disabled:opacity-50 min-h-[44px]"
            >
              <option value="claude-3-5-sonnet-20241022">Claude 3.5 Sonnet</option>
              <option value="claude-3-opus-20240229">Claude 3 Opus</option>
              <option value="gpt-4o">GPT-4o</option>
              <option value="gpt-4-turbo">GPT-4 Turbo</option>
            </select>
          }
        />
      </SettingsGroup>

      {/* Notifications - Placeholder for future */}
      <SettingsGroup title="Notifications">
        <SettingsItem
          label="Email notifications"
          description="Receive email updates about your projects"
          control={
            <ToggleSwitch
              active={true}
              onChange={() => toast('Email notifications coming soon!')}
              disabled={false}
            />
          }
        />
        <SettingsItem
          label="Marketing emails"
          description="Receive updates about new features and tips"
          control={
            <ToggleSwitch
              active={false}
              onChange={() => toast('Marketing preferences coming soon!')}
              disabled={false}
            />
          }
        />
      </SettingsGroup>
    </SettingsSection>
  );
}
