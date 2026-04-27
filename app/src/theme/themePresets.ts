/**
 * Theme System for OpenSail
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
      borderFocus: '#3a3c40',
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
      purple: '#a855f7',
      purpleRgb: '168, 85, 247',
    },
    shadow: {
      small: '0 1px 2px rgba(0, 0, 0, 0.3)',
      medium: '0 4px 6px rgba(0, 0, 0, 0.3)',
      large: '0 10px 15px rgba(0, 0, 0, 0.3)',
    },
  },
  typography: {
    fontFamily:
      "'Instrument Sans', Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    fontFamilyHeading: "'Instrument Sans', -apple-system, BlinkMacSystemFont, sans-serif",
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
 * Safely set a CSS custom property. Skips if value is undefined/null/empty,
 * preserving the previous value rather than setting "undefined" as a string.
 */
function safeSetProperty(el: HTMLElement, prop: string, value: string | undefined | null): void {
  if (value != null && value !== '') {
    el.style.setProperty(prop, value);
  }
}

/**
 * Apply a theme to the document (sets all CSS variables).
 */
export function applyThemePreset(theme: Theme): void {
  const root = document.documentElement;
  const { colors, typography, spacing, animation } = theme;

  // Guard: bail out if the theme object is fundamentally broken
  if (!colors || !typography || !spacing || !animation) {
    console.warn('applyThemePreset: theme is missing required sections, skipping apply');
    return;
  }

  // === CORE COLORS ===
  safeSetProperty(root, '--primary', colors.primary);
  safeSetProperty(root, '--primary-hover', colors.primaryHover);
  safeSetProperty(root, '--primary-rgb', colors.primaryRgb);
  safeSetProperty(root, '--accent', colors.accent);

  // === BACKGROUNDS ===
  safeSetProperty(root, '--bg', colors.background);
  safeSetProperty(root, '--bg-dark', colors.background); // Legacy alias
  safeSetProperty(root, '--surface', colors.surface);
  safeSetProperty(root, '--surface-hover', colors.surfaceHover);

  const cardHover =
    theme.mode === 'dark'
      ? `color-mix(in srgb, ${colors.surface} 92%, white 8%)`
      : `color-mix(in srgb, ${colors.surface} 88%, ${colors.textMuted} 12%)`;
  safeSetProperty(root, '--card-hover', cardHover);

  // === TEXT ===
  safeSetProperty(root, '--text', colors.text);
  safeSetProperty(root, '--text-muted', colors.textMuted);
  safeSetProperty(root, '--text-subtle', colors.textSubtle);

  // === BORDERS ===
  safeSetProperty(root, '--border', colors.border);
  safeSetProperty(root, '--border-hover', colors.borderHover);
  // Legacy alias used by chat/panels (e.g. ChatMessage) — keep in sync with --border
  // so light themes don't bleed the :root dark fallback through.
  safeSetProperty(root, '--border-color', colors.border);

  // === SIDEBAR ===
  if (colors.sidebar) {
    safeSetProperty(root, '--sidebar-bg', colors.sidebar.background);
    safeSetProperty(root, '--sidebar-text', colors.sidebar.text);
    safeSetProperty(root, '--sidebar-border', colors.sidebar.border);
    safeSetProperty(root, '--sidebar-hover', colors.sidebar.hover);
    safeSetProperty(root, '--sidebar-active', colors.sidebar.active);
  }

  // === INPUT ===
  if (colors.input) {
    safeSetProperty(root, '--input-bg', colors.input.background);
    safeSetProperty(root, '--input-border', colors.input.border);
    safeSetProperty(root, '--input-border-focus', colors.input.borderFocus);
    safeSetProperty(root, '--input-text', colors.input.text);
    safeSetProperty(root, '--input-placeholder', colors.input.placeholder);
  }

  // === SCROLLBAR ===
  if (colors.scrollbar) {
    safeSetProperty(root, '--scrollbar-thumb', colors.scrollbar.thumb);
    safeSetProperty(root, '--scrollbar-thumb-hover', colors.scrollbar.thumbHover);
    safeSetProperty(root, '--scrollbar-track', colors.scrollbar.track);
  }

  // === CODE ===
  if (colors.code) {
    safeSetProperty(root, '--code-inline-bg', colors.code.inlineBackground);
    safeSetProperty(root, '--code-inline-text', colors.code.inlineText);
    safeSetProperty(root, '--code-block-bg', colors.code.blockBackground);
    safeSetProperty(root, '--code-block-border', colors.code.blockBorder);
    safeSetProperty(root, '--code-block-text', colors.code.blockText);
  }

  // === STATUS ===
  if (colors.status) {
    safeSetProperty(root, '--status-error', colors.status.error);
    safeSetProperty(root, '--status-error-rgb', colors.status.errorRgb);
    safeSetProperty(root, '--status-success', colors.status.success);
    safeSetProperty(root, '--status-success-rgb', colors.status.successRgb);
    safeSetProperty(root, '--status-warning', colors.status.warning);
    safeSetProperty(root, '--status-warning-rgb', colors.status.warningRgb);
    safeSetProperty(root, '--status-info', colors.status.info);
    safeSetProperty(root, '--status-info-rgb', colors.status.infoRgb);

    // Legacy status variable names
    safeSetProperty(root, '--status-red', colors.status.error);
    safeSetProperty(root, '--status-green', colors.status.success);
    safeSetProperty(root, '--status-yellow', colors.status.warning);
    safeSetProperty(root, '--status-blue', colors.status.info);
    safeSetProperty(root, '--status-purple', colors.status.purple);
    safeSetProperty(root, '--status-purple-rgb', colors.status.purpleRgb);
  }

  // === SHADOWS ===
  if (colors.shadow) {
    safeSetProperty(root, '--shadow-small', colors.shadow.small);
    safeSetProperty(root, '--shadow-medium', colors.shadow.medium);
    safeSetProperty(root, '--shadow-large', colors.shadow.large);
  }

  // === TYPOGRAPHY ===
  safeSetProperty(root, '--font-family', typography.fontFamily);
  safeSetProperty(root, '--font-family-mono', typography.fontFamilyMono);
  safeSetProperty(root, '--font-size-base', typography.fontSizeBase);
  safeSetProperty(root, '--line-height', typography.lineHeight);
  safeSetProperty(root, '--font-family-heading', typography.fontFamilyHeading);

  // === SPACING / RADIUS ===
  safeSetProperty(root, '--radius-small', spacing.radiusSmall);
  safeSetProperty(root, '--radius-medium', spacing.radiusMedium);
  safeSetProperty(root, '--radius-large', spacing.radiusLarge);
  safeSetProperty(root, '--radius-xl', spacing.radiusXl);
  safeSetProperty(root, '--radius', spacing.radiusXl); // Default radius — main content panels
  safeSetProperty(root, '--control-border-radius', spacing.radiusSmall); // Controls use small radius

  // === ANIMATION ===
  safeSetProperty(root, '--duration-fast', animation.durationFast);
  safeSetProperty(root, '--duration-normal', animation.durationNormal);
  safeSetProperty(root, '--duration-slow', animation.durationSlow);
  safeSetProperty(root, '--easing', animation.easing);
  safeSetProperty(root, '--easing-layout', animation.easing); // Layout transitions use same easing
  safeSetProperty(root, '--ease', animation.easing); // Legacy alias

  // === BORDERLESS OVERRIDE ===
  // When the theme opts into borderless mode, force every border CSS
  // variable to transparent. This catches both the canonical names and
  // legacy aliases without requiring a per-component sweep — anything
  // that resolves through one of these vars vanishes. Components that
  // need a divider regardless can fall back to --surface-hover or read
  // [data-borderless="true"] from the root element.
  if (theme.borderless) {
    root.style.setProperty('--border', 'transparent');
    root.style.setProperty('--border-hover', 'transparent');
    root.style.setProperty('--border-color', 'transparent');
    root.style.setProperty('--sidebar-border', 'transparent');
    root.style.setProperty('--input-border', 'transparent');
    root.style.setProperty('--input-border-focus', 'transparent');
    root.style.setProperty('--code-block-border', 'transparent');
    root.setAttribute('data-borderless', 'true');
  } else {
    root.removeAttribute('data-borderless');
  }

  // === MODE CLASS ===
  document.body.classList.remove('light-mode', 'dark-mode');
  document.body.classList.add(`${theme.mode}-mode`);

  // Update body styles directly (these are the authoritative values, not CSS overrides)
  if (colors.background) document.body.style.backgroundColor = colors.background;
  if (colors.text) document.body.style.color = colors.text;
}
