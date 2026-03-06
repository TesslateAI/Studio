/**
 * Theme Type Definitions and Runtime Validation
 *
 * Re-exports types from api.ts and provides runtime validation
 * to prevent malformed themes from crashing the frontend.
 *
 * Keep in sync with: orchestrator/app/schemas_theme.py
 */

// Re-export all theme types from api.ts
export type {
  Theme,
  ThemeColors,
  ThemeTypography,
  ThemeSpacing,
  ThemeAnimation,
  ThemeListItem,
} from '../lib/api';

// Import for use in validation
import type { Theme } from '../lib/api';

// =============================================================================
// Theme Loading State Types
// =============================================================================

export type ThemeLoadingState = 'idle' | 'loading' | 'success' | 'error';

export interface ThemeState {
  themes: Map<string, Theme>;
  loadingState: ThemeLoadingState;
  error: string | null;
  lastUpdated: number | null;
}

// =============================================================================
// Runtime Validation
// =============================================================================

/**
 * Validate that a value is a non-empty string
 */
function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

/**
 * Validate that an object has all required string properties
 */
function hasStringProps(
  obj: unknown,
  props: string[]
): obj is Record<string, string> {
  if (!obj || typeof obj !== 'object') return false;
  const record = obj as Record<string, unknown>;
  return props.every((prop) => isNonEmptyString(record[prop]));
}

/**
 * Validate sidebar colors structure
 */
function isValidSidebarColors(value: unknown): boolean {
  return hasStringProps(value, ['background', 'text', 'border', 'hover', 'active']);
}

/**
 * Validate input colors structure
 */
function isValidInputColors(value: unknown): boolean {
  return hasStringProps(value, [
    'background',
    'border',
    'borderFocus',
    'text',
    'placeholder',
  ]);
}

/**
 * Validate scrollbar colors structure
 */
function isValidScrollbarColors(value: unknown): boolean {
  return hasStringProps(value, ['thumb', 'thumbHover', 'track']);
}

/**
 * Validate code colors structure
 */
function isValidCodeColors(value: unknown): boolean {
  return hasStringProps(value, [
    'inlineBackground',
    'inlineText',
    'blockBackground',
    'blockBorder',
    'blockText',
  ]);
}

/**
 * Validate status colors structure
 */
function isValidStatusColors(value: unknown): boolean {
  return hasStringProps(value, [
    'error',
    'errorRgb',
    'success',
    'successRgb',
    'warning',
    'warningRgb',
    'info',
    'infoRgb',
  ]);
}

/**
 * Validate shadow values structure
 */
function isValidShadowValues(value: unknown): boolean {
  return hasStringProps(value, ['small', 'medium', 'large']);
}

/**
 * Validate the complete colors object
 */
function isValidThemeColors(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false;
  const colors = value as Record<string, unknown>;

  // Check top-level color properties
  const requiredColorProps = [
    'primary',
    'primaryHover',
    'primaryRgb',
    'accent',
    'background',
    'surface',
    'surfaceHover',
    'text',
    'textMuted',
    'textSubtle',
    'border',
    'borderHover',
  ];

  if (!hasStringProps(colors, requiredColorProps)) return false;

  // Check nested objects
  return (
    isValidSidebarColors(colors.sidebar) &&
    isValidInputColors(colors.input) &&
    isValidScrollbarColors(colors.scrollbar) &&
    isValidCodeColors(colors.code) &&
    isValidStatusColors(colors.status) &&
    isValidShadowValues(colors.shadow)
  );
}

/**
 * Validate typography structure
 */
function isValidTypography(value: unknown): boolean {
  return hasStringProps(value, [
    'fontFamily',
    'fontFamilyMono',
    'fontSizeBase',
    'lineHeight',
  ]);
}

/**
 * Validate spacing structure
 */
function isValidSpacing(value: unknown): boolean {
  return hasStringProps(value, [
    'radiusSmall',
    'radiusMedium',
    'radiusLarge',
    'radiusXl',
  ]);
}

/**
 * Validate animation structure
 */
function isValidAnimation(value: unknown): boolean {
  return hasStringProps(value, [
    'durationFast',
    'durationNormal',
    'durationSlow',
    'easing',
  ]);
}

/**
 * Runtime validation for Theme objects.
 * Use this before applying theme CSS variables to prevent crashes
 * from malformed API responses.
 *
 * @param theme - The theme object to validate
 * @returns true if the theme has all required properties with correct types
 *
 * @example
 * ```tsx
 * const theme = await themesApi.get('my-theme');
 * if (isValidTheme(theme)) {
 *   applyThemePreset(theme);
 * } else {
 *   console.error('Invalid theme, using fallback');
 *   applyThemePreset(DEFAULT_FALLBACK_THEME);
 * }
 * ```
 */
export function isValidTheme(theme: unknown): theme is Theme {
  if (!theme || typeof theme !== 'object') return false;

  const t = theme as Record<string, unknown>;

  // Check required top-level fields
  if (!isNonEmptyString(t.id)) return false;
  if (!isNonEmptyString(t.name)) return false;
  if (t.mode !== 'dark' && t.mode !== 'light') return false;

  // Check nested structures
  if (!isValidThemeColors(t.colors)) return false;
  if (!isValidTypography(t.typography)) return false;
  if (!isValidSpacing(t.spacing)) return false;
  if (!isValidAnimation(t.animation)) return false;

  return true;
}

/**
 * Validate a theme and return detailed error information
 *
 * @param theme - The theme object to validate
 * @returns Object with isValid flag and optional error message
 */
export function validateTheme(theme: unknown): {
  isValid: boolean;
  error?: string;
} {
  if (!theme || typeof theme !== 'object') {
    return { isValid: false, error: 'Theme must be an object' };
  }

  const t = theme as Record<string, unknown>;

  if (!isNonEmptyString(t.id)) {
    return { isValid: false, error: 'Theme id is required' };
  }
  if (!isNonEmptyString(t.name)) {
    return { isValid: false, error: 'Theme name is required' };
  }
  if (t.mode !== 'dark' && t.mode !== 'light') {
    return { isValid: false, error: 'Theme mode must be "dark" or "light"' };
  }

  if (!isValidThemeColors(t.colors)) {
    return { isValid: false, error: 'Theme colors structure is invalid' };
  }
  if (!isValidTypography(t.typography)) {
    return { isValid: false, error: 'Theme typography structure is invalid' };
  }
  if (!isValidSpacing(t.spacing)) {
    return { isValid: false, error: 'Theme spacing structure is invalid' };
  }
  if (!isValidAnimation(t.animation)) {
    return { isValid: false, error: 'Theme animation structure is invalid' };
  }

  return { isValid: true };
}

/**
 * Get the default fallback theme (hardcoded, always valid)
 * This should be used when API themes fail to load or validate
 */
export const DEFAULT_FALLBACK_THEME: Theme = {
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
    fontFamily:
      "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
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
