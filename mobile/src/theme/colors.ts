// Tesslate Studio Color Palette
// Based on the web app's CSS variables

export const colors = {
  light: {
    // Primary colors
    primary: '#3B82F6',      // Blue-500
    primaryDark: '#2563EB',  // Blue-600
    primaryLight: '#60A5FA', // Blue-400

    // Background colors
    background: '#FFFFFF',
    backgroundSecondary: '#F8FAFC', // Slate-50
    backgroundTertiary: '#F1F5F9',  // Slate-100

    // Text colors
    text: '#0F172A',         // Slate-900
    textSecondary: '#475569', // Slate-600
    textTertiary: '#94A3B8',  // Slate-400
    textInverse: '#FFFFFF',

    // Border colors
    border: '#E2E8F0',       // Slate-200
    borderDark: '#CBD5E1',   // Slate-300

    // Status colors
    success: '#10B981',      // Green-500
    successLight: '#D1FAE5', // Green-100
    error: '#EF4444',        // Red-500
    errorLight: '#FEE2E2',   // Red-100
    warning: '#F59E0B',      // Amber-500
    warningLight: '#FEF3C7', // Amber-100
    info: '#3B82F6',         // Blue-500
    infoLight: '#DBEAFE',    // Blue-100

    // UI elements
    card: '#FFFFFF',
    cardShadow: 'rgba(0, 0, 0, 0.1)',
    overlay: 'rgba(0, 0, 0, 0.5)',

    // Code editor colors
    codeBackground: '#1E293B', // Slate-800
    codeText: '#E2E8F0',       // Slate-200
  },

  dark: {
    // Primary colors
    primary: '#3B82F6',      // Blue-500
    primaryDark: '#60A5FA',  // Blue-400
    primaryLight: '#2563EB', // Blue-600

    // Background colors
    background: '#0F172A',    // Slate-900
    backgroundSecondary: '#1E293B', // Slate-800
    backgroundTertiary: '#334155',  // Slate-700

    // Text colors
    text: '#F8FAFC',         // Slate-50
    textSecondary: '#CBD5E1', // Slate-300
    textTertiary: '#64748B',  // Slate-500
    textInverse: '#0F172A',

    // Border colors
    border: '#334155',       // Slate-700
    borderDark: '#475569',   // Slate-600

    // Status colors
    success: '#10B981',      // Green-500
    successLight: '#064E3B', // Green-900
    error: '#EF4444',        // Red-500
    errorLight: '#7F1D1D',   // Red-900
    warning: '#F59E0B',      // Amber-500
    warningLight: '#78350F', // Amber-900
    info: '#3B82F6',         // Blue-500
    infoLight: '#1E3A8A',    // Blue-900

    // UI elements
    card: '#1E293B',
    cardShadow: 'rgba(0, 0, 0, 0.3)',
    overlay: 'rgba(0, 0, 0, 0.7)',

    // Code editor colors
    codeBackground: '#0F172A', // Slate-900
    codeText: '#E2E8F0',       // Slate-200
  },
};

export type ColorTheme = typeof colors.light;
