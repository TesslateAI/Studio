import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { Check } from 'lucide-react';
import { ArrowRight } from '@phosphor-icons/react';
import { useTheme } from '../../theme/ThemeContext';
import { marketplaceApi } from '../../lib/api';
import { ToggleSwitch } from '../../components/ui/ToggleSwitch';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';

interface LibraryThemeItem {
  id: string;
  name: string;
  description: string;
  mode: string;
  is_enabled: boolean;
  color_swatches?: {
    primary?: string;
    accent?: string;
    background?: string;
    surface?: string;
  };
  theme_json?: {
    colors?: Record<string, unknown>;
    spacing?: {
      radiusMedium?: string;
      [key: string]: unknown;
    };
    [key: string]: unknown;
  };
}

function ThemeCard({
  theme,
  isSelected,
  onSelect,
}: {
  theme: LibraryThemeItem;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const colors = theme.color_swatches || (theme.theme_json?.colors as Record<string, string>) || {};
  const radiusMedium = theme.theme_json?.spacing?.radiusMedium || '10px';

  return (
    <button
      onClick={onSelect}
      disabled={!theme.is_enabled}
      className={`relative flex flex-col items-start p-3 rounded-xl border transition-all text-left w-full ${
        isSelected
          ? 'border-[var(--primary)] bg-[var(--primary)]/10 ring-2 ring-[var(--primary)]/20'
          : 'border-white/10 bg-white/5 hover:bg-white/10 hover:border-white/20'
      } ${!theme.is_enabled ? 'opacity-40 cursor-not-allowed' : ''}`}
    >
      {/* Color preview swatches */}
      <div className="flex gap-1.5 mb-2">
        <div
          className="w-6 h-6 rounded-md border border-black/20"
          style={{ backgroundColor: (colors as Record<string, string>).primary || '#6366f1' }}
          title="Primary"
        />
        <div
          className="w-6 h-6 rounded-md border border-black/20"
          style={{ backgroundColor: (colors as Record<string, string>).background || '#0a0a0a' }}
          title="Background"
        />
        <div
          className="w-6 h-6 rounded-md border border-black/20"
          style={{ backgroundColor: (colors as Record<string, string>).surface || '#141414' }}
          title="Surface"
        />
        <div
          className="w-6 h-6 rounded-md border border-black/20"
          style={{ backgroundColor: (colors as Record<string, string>).accent || '#8b5cf6' }}
          title="Accent"
        />
      </div>

      {/* Theme name and description */}
      <div className="flex-1">
        <div className="text-sm font-medium text-[var(--text)]">{theme.name}</div>
        <div className="text-xs text-[var(--text)]/60 mt-0.5">{theme.description || ''}</div>
      </div>

      {/* Border radius preview */}
      <div className="flex items-center gap-1 mt-2">
        <span className="text-[10px] text-[var(--text)]/40">Corners:</span>
        <div
          className="w-4 h-4 border border-[var(--text)]/30"
          style={{ borderRadius: radiusMedium, backgroundColor: 'transparent' }}
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
  const navigate = useNavigate();
  const { themePresetId, setThemePreset, isLoading: themeLoading } = useTheme();
  const [loading, setLoading] = useState(true);
  const [libraryThemes, setLibraryThemes] = useState<LibraryThemeItem[]>([]);

  const loadLibraryThemes = useCallback(async () => {
    try {
      const data = await marketplaceApi.getUserLibraryThemes();
      setLibraryThemes(data.themes || []);
    } catch (error) {
      console.error('Failed to load library themes:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLibraryThemes();
  }, [loadLibraryThemes]);

  const handleThemeSelect = (presetId: string) => {
    setThemePreset(presetId);
    toast.success('Theme updated');
  };

  const darkThemes = libraryThemes.filter((t) => t.mode === 'dark' && t.is_enabled);
  const lightThemes = libraryThemes.filter((t) => t.mode === 'light' && t.is_enabled);

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
          {darkThemes.length > 0 && (
            <div className="mb-6">
              <h4 className="text-sm font-medium text-[var(--text)]/80 mb-3">Dark themes</h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {darkThemes.map((theme) => (
                  <ThemeCard
                    key={theme.id}
                    theme={theme}
                    isSelected={themePresetId === theme.id}
                    onSelect={() => handleThemeSelect(theme.id)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Light Themes */}
          {lightThemes.length > 0 && (
            <div className="mb-4">
              <h4 className="text-sm font-medium text-[var(--text)]/80 mb-3">Light themes</h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {lightThemes.map((theme) => (
                  <ThemeCard
                    key={theme.id}
                    theme={theme}
                    isSelected={themePresetId === theme.id}
                    onSelect={() => handleThemeSelect(theme.id)}
                  />
                ))}
              </div>
            </div>
          )}

          <div className="flex items-center justify-between mt-4">
            <p className="text-xs text-[var(--text)]/50">
              Theme changes are automatically saved and will persist across sessions.
            </p>
            <button
              onClick={() => navigate('/marketplace?type=theme')}
              className="flex items-center gap-1 text-xs text-[var(--primary)] hover:text-[var(--primary-hover)] font-medium transition-colors"
            >
              Browse more themes
              <ArrowRight size={12} />
            </button>
          </div>
        </div>
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
