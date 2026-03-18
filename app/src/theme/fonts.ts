export const fonts = {
  heading: "'DM Sans', sans-serif",
  body: "'DM Sans', sans-serif",
  // DM Sans Variable font loaded — supports weight 100-1000 + optical size 9-40
  // Base: 12px at weight 500 for readability at small sizes
} as const;

export type FontType = keyof typeof fonts;
