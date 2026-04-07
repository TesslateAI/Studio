import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import {
  loadThemes,
  reloadThemes,
  getThemePreset,
  applyThemePreset,
  getThemePresetsByMode,
} from './themePresets';
import type { Theme } from './themePresets';
import { usersApi } from '../lib/api';
import { isValidTheme, DEFAULT_FALLBACK_THEME } from '../types/theme';

export type ThemeLoadingState = 'idle' | 'loading' | 'success' | 'error';

interface ThemeContextType {
  theme: 'light' | 'dark';
  themePresetId: string;
  themePreset: Theme;
  toggleTheme: () => void;
  setThemePreset: (presetId: string) => void;
  refreshUserTheme: () => Promise<void>;
  availablePresets: Theme[];
  isLoading: boolean;
  /** Detailed loading state for advanced use cases */
  loadingState: ThemeLoadingState;
  /** Error message if loading failed */
  error: string | null;
  /** True when themes are ready (loaded or fallback available) */
  isReady: boolean;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

interface ThemeProviderProps {
  children: ReactNode;
}

const DEFAULT_THEME = 'default-dark';

export function ThemeProvider({ children }: ThemeProviderProps) {
  const [themePresetId, setThemePresetIdState] = useState<string>(DEFAULT_THEME);
  const [availablePresets, setAvailablePresets] = useState<Theme[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadingState, setLoadingState] = useState<ThemeLoadingState>('idle');
  const [error, setError] = useState<string | null>(null);

  // Get current theme with validation
  const themePreset = (() => {
    const preset = getThemePreset(themePresetId);
    // Runtime validation before use
    if (isValidTheme(preset)) {
      return preset;
    }
    console.warn(`Theme ${themePresetId} failed validation, using fallback`);
    return DEFAULT_FALLBACK_THEME as Theme;
  })();

  const theme = themePreset.mode;

  // Derived ready state - true when we have usable themes
  const isReady =
    loadingState === 'success' ||
    (loadingState === 'error' && availablePresets.length > 0) ||
    (loadingState === 'idle' && availablePresets.length > 0);

  // Load themes from API on mount, then load user preference
  useEffect(() => {
    const init = async () => {
      setLoadingState('loading');
      setError(null);

      try {
        // First, load all themes from the API
        await loadThemes();

        // Update available presets with validation
        const byMode = getThemePresetsByMode();
        const allPresets = [...byMode.dark, ...byMode.light];

        // Filter out invalid themes
        const validPresets = allPresets.filter(isValidTheme);
        if (validPresets.length < allPresets.length) {
          console.warn(`Filtered ${allPresets.length - validPresets.length} invalid themes`);
        }

        setAvailablePresets(
          validPresets.length > 0 ? validPresets : [DEFAULT_FALLBACK_THEME as Theme]
        );

        // Then load user's saved theme preference
        try {
          const prefs = await usersApi.getPreferences();
          if (prefs.theme_preset) {
            // Verify the theme exists and is valid before setting
            const loadedTheme = getThemePreset(prefs.theme_preset);
            if (isValidTheme(loadedTheme) && loadedTheme.id === prefs.theme_preset) {
              setThemePresetIdState(prefs.theme_preset);
            }
          }
        } catch {
          // If API fails (not authenticated or network error), use default theme silently
          console.debug('Could not load theme preference from API, using default');
        }

        setLoadingState('success');
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to load themes';
        console.warn('Failed to initialize themes:', message);
        setError(message);
        setLoadingState('error');

        // Ensure fallback is available even on error
        setAvailablePresets([DEFAULT_FALLBACK_THEME as Theme]);
      } finally {
        setIsLoading(false);
      }
    };

    init();
  }, []);

  // Apply the team's theme when switching teams
  useEffect(() => {
    const onTeamTheme = (e: Event) => {
      const presetId = (e as CustomEvent).detail as string;
      if (presetId) {
        setThemePresetIdState(presetId);
      }
    };
    window.addEventListener('team-theme-changed', onTeamTheme);
    return () => window.removeEventListener('team-theme-changed', onTeamTheme);
  }, []);

  // Apply theme whenever it changes
  useEffect(() => {
    applyThemePreset(themePreset);
  }, [themePresetId, themePreset]);

  // Toggle between dark and light variant of current theme color
  const toggleTheme = useCallback(() => {
    const currentPreset = getThemePreset(themePresetId);
    const baseName = themePresetId.replace(/-dark$|-light$/, '');

    // Try to find the opposite mode variant
    const targetMode = currentPreset.mode === 'dark' ? 'light' : 'dark';
    const targetId = `${baseName}-${targetMode}`;

    // Check if the target theme exists
    const targetTheme = getThemePreset(targetId);
    if (targetTheme.id === targetId) {
      setThemePreset(targetId);
    } else {
      // Fallback to default variant of target mode
      setThemePreset(targetMode === 'dark' ? 'default-dark' : 'default-light');
    }
  }, [themePresetId]);

  // Set a specific theme preset
  const setThemePreset = useCallback(async (presetId: string) => {
    // Verify the theme exists in cache
    let theme = getThemePreset(presetId);
    if (theme.id !== presetId) {
      // Theme not in cache — reload from API (handles newly created/forked themes)
      await reloadThemes();
      theme = getThemePreset(presetId);
      if (theme.id !== presetId) {
        console.warn(`Unknown theme preset: ${presetId}`);
        return;
      }
      // Update available presets after reload
      const byMode = getThemePresetsByMode();
      setAvailablePresets([...byMode.dark, ...byMode.light]);
    }

    setThemePresetIdState(presetId);

    // Save to API (non-blocking) - works with both token and cookie-based auth
    try {
      await usersApi.updatePreferences({ theme_preset: presetId });
    } catch {
      // Don't block on API errors (will fail silently if not authenticated)
      console.debug('Could not save theme to API');
    }
  }, []);

  // Refresh theme from API (call after login - assumes user is authenticated)
  const refreshUserTheme = useCallback(async () => {
    try {
      // Reload themes in case new ones were added
      await loadThemes();
      const byMode = getThemePresetsByMode();
      setAvailablePresets([...byMode.dark, ...byMode.light]);

      // Load user preference
      const prefs = await usersApi.getPreferences();
      if (prefs.theme_preset) {
        const loadedTheme = getThemePreset(prefs.theme_preset);
        if (loadedTheme.id === prefs.theme_preset) {
          setThemePresetIdState(prefs.theme_preset);
        }
      }
    } catch {
      console.debug('Could not refresh theme from API');
    }
  }, []);

  return (
    <ThemeContext.Provider
      value={{
        theme,
        themePresetId,
        themePreset,
        toggleTheme,
        setThemePreset,
        refreshUserTheme,
        availablePresets,
        isLoading,
        loadingState,
        error,
        isReady,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}

/**
 * Hook that returns theme context with safe fallbacks while loading.
 * Use this in components that need themes but should render immediately.
 *
 * @returns ThemeContextType with guaranteed availablePresets (fallback if loading)
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useThemeWhenReady() {
  const context = useTheme();

  // If not ready, return context with fallback presets
  if (!context.isReady) {
    return {
      ...context,
      availablePresets: [DEFAULT_FALLBACK_THEME as Theme],
    };
  }

  return context;
}
