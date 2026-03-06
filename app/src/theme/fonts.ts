export const fonts = {
  heading: "'DM Sans', sans-serif",
  body: "'DM Sans', sans-serif"
} as const;

export type FontType = keyof typeof fonts;
