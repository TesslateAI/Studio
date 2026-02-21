/**
 * Theme System for Tesslate Studio
 *
 * Themes are loaded from the API (database) and cached in memory.
 * This file provides the TypeScript interfaces and helper functions
 * to apply themes via CSS variables.
 */

import { themesApi, type Theme, type ThemeListItem } from '../lib/api';

// Re-export types for convenience
export type { Theme, ThemeListItem };

// Also export as ThemePreset for backwards compatibility
export type ThemePreset = Theme;

// ============================================================================
// Theme Cache
// ============================================================================

// In-memory cache of loaded themes
const themesCache: Map<string, Theme> = new Map();
let themesLoaded = false;
let themesLoading: Promise<void> | null = null;

// Default fallback theme (used before API loads)
const DEFAULT_FALLBACK_THEME: Theme = {
  id: 'default-dark',
  name: 'Default Dark',
  mode: 'dark',
  author: 'Tesslate',
  version: '1.0.0',
  description: 'The classic Tesslate dark theme',
  colors: {
    primary: '#F89521',
    primaryHover: '#fa9f35',
    primaryRgb: '248, 149, 33',
    accent: '#00D9FF',
    background: '#111113',
    surface: '#1a1a1c',
    surfaceHover: '#252527',
    text: '#ffffff',
    textMuted: 'rgba(255, 255, 255, 0.6)',
    textSubtle: 'rgba(255, 255, 255, 0.4)',
    border: 'rgba(255, 255, 255, 0.1)',
    borderHover: 'rgba(255, 255, 255, 0.2)',
    sidebar: {
      background: '#0a0a0a',
      text: '#ffffff',
      border: 'rgba(255, 255, 255, 0.1)',
      hover: 'rgba(255, 255, 255, 0.05)',
      active: 'rgba(255, 255, 255, 0.1)',
    },
    input: {
      background: '#1a1a1c',
      border: 'rgba(255, 255, 255, 0.1)',
      borderFocus: '#F89521',
      text: '#ffffff',
      placeholder: 'rgba(255, 255, 255, 0.4)',
    },
    scrollbar: {
      thumb: 'rgba(255, 255, 255, 0.2)',
      thumbHover: 'rgba(255, 255, 255, 0.3)',
      track: 'transparent',
    },
    code: {
      inlineBackground: 'rgba(248, 149, 33, 0.15)',
      inlineText: '#fbbf68',
      blockBackground: 'rgba(0, 0, 0, 0.4)',
      blockBorder: 'rgba(255, 255, 255, 0.1)',
      blockText: '#e2e2e2',
    },
    status: {
      error: '#ef4444',
      errorRgb: '239, 68, 68',
      success: '#22c55e',
      successRgb: '34, 197, 94',
      warning: '#f59e0b',
      warningRgb: '245, 158, 11',
      info: '#3b82f6',
      infoRgb: '59, 130, 246',
    },
    shadow: {
      small: '0 1px 2px rgba(0, 0, 0, 0.3)',
      medium: '0 4px 6px rgba(0, 0, 0, 0.3)',
      large: '0 10px 15px rgba(0, 0, 0, 0.3)',
    },
  },
  typography: {
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    fontFamilyMono: "JetBrains Mono, Menlo, Monaco, 'Courier New', monospace",
    fontSizeBase: '14px',
    lineHeight: '1.5',
  },
  spacing: {
    radiusSmall: '4px',
    radiusMedium: '6px',
    radiusLarge: '8px',
    radiusXl: '12px',
  },
  animation: {
    durationFast: '150ms',
    durationNormal: '200ms',
    durationSlow: '300ms',
    easing: 'cubic-bezier(0.4, 0, 0.2, 1)',
  },
};

// ============================================================================
// Theme Loading
// ============================================================================

/**
 * Load all themes from the API into memory cache.
 * This is called once on app startup.
 */
export async function loadThemes(): Promise<void> {
  // If already loaded, return
  if (themesLoaded) return;

  // If currently loading, wait for that
  if (themesLoading) {
    await themesLoading;
    return;
  }

  // Start loading
  themesLoading = (async () => {
    try {
      const themes = await themesApi.listFull();
      themesCache.clear();
      for (const theme of themes) {
        themesCache.set(theme.id, theme);
      }
      themesLoaded = true;
      console.debug(`Loaded ${themes.length} themes from API`);
    } catch (error) {
      console.warn('Failed to load themes from API, using fallback:', error);
      // Add fallback theme so app still works
      themesCache.set(DEFAULT_FALLBACK_THEME.id, DEFAULT_FALLBACK_THEME);
      themesLoaded = true;
    }
  })();

  await themesLoading;
  themesLoading = null;
}

/**
 * Force reload themes from the API.
 */
export async function reloadThemes(): Promise<void> {
  themesLoaded = false;
  await loadThemes();
}

// ============================================================================
// Theme Access (Backwards Compatible)
// ============================================================================

/**
 * Get all themes as a record (for backwards compatibility).
 * Note: Returns current cache state, may be empty before loadThemes() is called.
 */
export function getThemePresets(): Record<string, Theme> {
  const result: Record<string, Theme> = {};
  for (const [id, theme] of themesCache) {
    result[id] = theme;
  }
  // Always include fallback if cache is empty
  if (themesCache.size === 0) {
    result[DEFAULT_FALLBACK_THEME.id] = DEFAULT_FALLBACK_THEME;
  }
  return result;
}

// Legacy export for backwards compatibility
export const themePresets: Record<string, Theme> = new Proxy({} as Record<string, Theme>, {
  get(_, prop: string) {
    return themesCache.get(prop) || DEFAULT_FALLBACK_THEME;
  },
  has(_, prop: string) {
    return themesCache.has(prop);
  },
  ownKeys() {
    return Array.from(themesCache.keys());
  },
  getOwnPropertyDescriptor(_, prop: string) {
    if (themesCache.has(prop)) {
      return { enumerable: true, configurable: true, value: themesCache.get(prop) };
    }
    return undefined;
  },
});

/**
 * Get a theme by ID, with fallback to default.
 */
export function getThemePreset(id: string): Theme {
  return themesCache.get(id) || themesCache.get('default-dark') || DEFAULT_FALLBACK_THEME;
}

/**
 * Get all themes grouped by mode.
 */
export function getThemePresetsByMode(): { dark: Theme[]; light: Theme[] } {
  const themes = Array.from(themesCache.values());
  return {
    dark: themes.filter((t) => t.mode === 'dark'),
    light: themes.filter((t) => t.mode === 'light'),
  };
}

/**
 * Get list of available theme IDs.
 */
export function getAvailableThemeIds(): string[] {
  return Array.from(themesCache.keys());
}

/**
 * Check if themes have been loaded.
 */
export function areThemesLoaded(): boolean {
  return themesLoaded;
}

// ============================================================================
// Theme Application
// ============================================================================

/**
 * Apply a theme to the document (sets all CSS variables).
 */
export function applyThemePreset(theme: Theme): void {
  const root = document.documentElement;
  const { colors, typography, spacing, animation } = theme;

  // === CORE COLORS ===
  root.style.setProperty('--primary', colors.primary);
  root.style.setProperty('--primary-hover', colors.primaryHover);
  root.style.setProperty('--primary-rgb', colors.primaryRgb);
  root.style.setProperty('--accent', colors.accent);

  // === BACKGROUNDS ===
  root.style.setProperty('--bg', colors.background);
  root.style.setProperty('--bg-dark', colors.background); // Legacy alias
  root.style.setProperty('--surface', colors.surface);
  root.style.setProperty('--surface-hover', colors.surfaceHover);

  // === TEXT ===
  root.style.setProperty('--text', colors.text);
  root.style.setProperty('--text-muted', colors.textMuted);
  root.style.setProperty('--text-subtle', colors.textSubtle);

  // === BORDERS ===
  root.style.setProperty('--border', colors.border);
  root.style.setProperty('--border-hover', colors.borderHover);

  // === SIDEBAR ===
  root.style.setProperty('--sidebar-bg', colors.sidebar.background);
  root.style.setProperty('--sidebar-text', colors.sidebar.text);
  root.style.setProperty('--sidebar-border', colors.sidebar.border);
  root.style.setProperty('--sidebar-hover', colors.sidebar.hover);
  root.style.setProperty('--sidebar-active', colors.sidebar.active);

  // === INPUT ===
  root.style.setProperty('--input-bg', colors.input.background);
  root.style.setProperty('--input-border', colors.input.border);
  root.style.setProperty('--input-border-focus', colors.input.borderFocus);
  root.style.setProperty('--input-text', colors.input.text);
  root.style.setProperty('--input-placeholder', colors.input.placeholder);

  // === SCROLLBAR ===
  root.style.setProperty('--scrollbar-thumb', colors.scrollbar.thumb);
  root.style.setProperty('--scrollbar-thumb-hover', colors.scrollbar.thumbHover);
  root.style.setProperty('--scrollbar-track', colors.scrollbar.track);

  // === CODE ===
  root.style.setProperty('--code-inline-bg', colors.code.inlineBackground);
  root.style.setProperty('--code-inline-text', colors.code.inlineText);
  root.style.setProperty('--code-block-bg', colors.code.blockBackground);
  root.style.setProperty('--code-block-border', colors.code.blockBorder);
  root.style.setProperty('--code-block-text', colors.code.blockText);

  // === STATUS ===
  root.style.setProperty('--status-error', colors.status.error);
  root.style.setProperty('--status-error-rgb', colors.status.errorRgb);
  root.style.setProperty('--status-success', colors.status.success);
  root.style.setProperty('--status-success-rgb', colors.status.successRgb);
  root.style.setProperty('--status-warning', colors.status.warning);
  root.style.setProperty('--status-warning-rgb', colors.status.warningRgb);
  root.style.setProperty('--status-info', colors.status.info);
  root.style.setProperty('--status-info-rgb', colors.status.infoRgb);

  // Legacy status variable names
  root.style.setProperty('--status-red', colors.status.error);
  root.style.setProperty('--status-green', colors.status.success);
  root.style.setProperty('--status-yellow', colors.status.warning);
  root.style.setProperty('--status-blue', colors.status.info);

  // === SHADOWS ===
  root.style.setProperty('--shadow-small', colors.shadow.small);
  root.style.setProperty('--shadow-medium', colors.shadow.medium);
  root.style.setProperty('--shadow-large', colors.shadow.large);

  // === TYPOGRAPHY ===
  root.style.setProperty('--font-family', typography.fontFamily);
  root.style.setProperty('--font-family-mono', typography.fontFamilyMono);
  root.style.setProperty('--font-size-base', typography.fontSizeBase);
  root.style.setProperty('--line-height', typography.lineHeight);

  // === SPACING / RADIUS ===
  root.style.setProperty('--radius-small', spacing.radiusSmall);
  root.style.setProperty('--radius-medium', spacing.radiusMedium);
  root.style.setProperty('--radius-large', spacing.radiusLarge);
  root.style.setProperty('--radius-xl', spacing.radiusXl);
  root.style.setProperty('--radius', spacing.radiusXl); // Default radius

  // === ANIMATION ===
  root.style.setProperty('--duration-fast', animation.durationFast);
  root.style.setProperty('--duration-normal', animation.durationNormal);
  root.style.setProperty('--duration-slow', animation.durationSlow);
  root.style.setProperty('--easing', animation.easing);

  // === MODE CLASS ===
  document.body.classList.remove('light-mode', 'dark-mode');
  document.body.classList.add(`${theme.mode}-mode`);

  // Update body styles
  document.body.style.backgroundColor = colors.background;
  document.body.style.color = colors.text;
}
