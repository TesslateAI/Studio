export const fonts = {
  heading: "'Space Grotesk', sans-serif",
  body: "'Inter', sans-serif"
} as const;

export type FontType = keyof typeof fonts;
