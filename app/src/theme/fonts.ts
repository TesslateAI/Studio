export const fonts = {
  heading: "'Instrument Sans', -apple-system, sans-serif",
  body: "'Instrument Sans', 'Inter', -apple-system, sans-serif"
} as const;

export type FontType = keyof typeof fonts;
