import React from 'react';

/**
 * Parse ANSI escape codes into styled React elements.
 * Supports: reset, bold, dim, italic, underline, standard/bright colors (fg & bg),
 * 256-color (38;5;N / 48;5;N), and RGB (38;2;R;G;B / 48;2;R;G;B).
 */

const STANDARD_COLORS: Record<number, string> = {
  30: '#1e1e1e', // black
  31: '#cd3131', // red
  32: '#0dbc79', // green
  33: '#e5e510', // yellow
  34: '#2472c8', // blue
  35: '#bc3fbc', // magenta
  36: '#11a8cd', // cyan
  37: '#e5e5e5', // white
  90: '#666666', // bright black
  91: '#f14c4c', // bright red
  92: '#23d18b', // bright green
  93: '#f5f543', // bright yellow
  94: '#3b8eea', // bright blue
  95: '#d670d6', // bright magenta
  96: '#29b8db', // bright cyan
  97: '#ffffff', // bright white
};

const BG_COLORS: Record<number, string> = {
  40: '#1e1e1e',
  41: '#cd3131',
  42: '#0dbc79',
  43: '#e5e510',
  44: '#2472c8',
  45: '#bc3fbc',
  46: '#11a8cd',
  47: '#e5e5e5',
  100: '#666666',
  101: '#f14c4c',
  102: '#23d18b',
  103: '#f5f543',
  104: '#3b8eea',
  105: '#d670d6',
  106: '#29b8db',
  107: '#ffffff',
};

// 256-color palette (indices 0-255)
function color256(n: number): string {
  if (n < 0 || n > 255) return 'inherit';
  // 0-7: standard colors
  if (n < 8) {
    const map = [30, 31, 32, 33, 34, 35, 36, 37];
    return STANDARD_COLORS[map[n]];
  }
  // 8-15: bright colors
  if (n < 16) {
    const map = [90, 91, 92, 93, 94, 95, 96, 97];
    return STANDARD_COLORS[map[n - 8]];
  }
  // 16-231: 6x6x6 color cube
  if (n < 232) {
    const idx = n - 16;
    const r = Math.floor(idx / 36);
    const g = Math.floor((idx % 36) / 6);
    const b = idx % 6;
    const toVal = (c: number) => (c === 0 ? 0 : 55 + c * 40);
    return `rgb(${toVal(r)},${toVal(g)},${toVal(b)})`;
  }
  // 232-255: grayscale
  const level = 8 + (n - 232) * 10;
  return `rgb(${level},${level},${level})`;
}

interface AnsiStyle {
  color?: string;
  backgroundColor?: string;
  fontWeight?: string;
  opacity?: number;
  fontStyle?: string;
  textDecoration?: string;
}

function applyCode(codes: number[], style: AnsiStyle): AnsiStyle {
  let next = { ...style };
  let i = 0;
  while (i < codes.length) {
    const c = codes[i];
    if (c === 0) {
      // reset — clear all styles but keep processing remaining codes (e.g. \x1b[0;32m)
      next = {};
    } else if (c === 1) {
      next.fontWeight = 'bold';
    } else if (c === 2) {
      next.opacity = 0.6;
    } else if (c === 3) {
      next.fontStyle = 'italic';
    } else if (c === 4) {
      next.textDecoration = 'underline';
    } else if (c === 22) {
      delete next.fontWeight;
      delete next.opacity;
    } else if (c === 23) {
      delete next.fontStyle;
    } else if (c === 24) {
      delete next.textDecoration;
    } else if (c === 39) {
      delete next.color;
    } else if (c === 49) {
      delete next.backgroundColor;
    } else if (c >= 30 && c <= 37) {
      next.color = STANDARD_COLORS[c];
    } else if (c >= 90 && c <= 97) {
      next.color = STANDARD_COLORS[c];
    } else if (c >= 40 && c <= 47) {
      next.backgroundColor = BG_COLORS[c];
    } else if (c >= 100 && c <= 107) {
      next.backgroundColor = BG_COLORS[c];
    } else if (c === 38) {
      // extended foreground
      if (codes[i + 1] === 5 && codes[i + 2] !== undefined) {
        next.color = color256(codes[i + 2]);
        i += 2;
      } else if (codes[i + 1] === 2 && codes[i + 4] !== undefined) {
        next.color = `rgb(${codes[i + 2]},${codes[i + 3]},${codes[i + 4]})`;
        i += 4;
      }
    } else if (c === 48) {
      // extended background
      if (codes[i + 1] === 5 && codes[i + 2] !== undefined) {
        next.backgroundColor = color256(codes[i + 2]);
        i += 2;
      } else if (codes[i + 1] === 2 && codes[i + 4] !== undefined) {
        next.backgroundColor = `rgb(${codes[i + 2]},${codes[i + 3]},${codes[i + 4]})`;
        i += 4;
      }
    }
    i++;
  }
  return next;
}

// Match non-SGR escape sequences (cursor movement, etc.) to strip them
// eslint-disable-next-line no-control-regex
const ALL_ESCAPE_RE = /\x1b\[[0-9;]*[A-Za-z]/g;

interface AnsiSpan {
  text: string;
  style: AnsiStyle;
}

function parseAnsiString(input: string): AnsiSpan[] {
  const spans: AnsiSpan[] = [];
  let currentStyle: AnsiStyle = {};
  let lastIndex = 0;

  // First, strip non-SGR escape sequences (cursor movement, etc.)
  const cleaned = input.replace(ALL_ESCAPE_RE, (match) => {
    // Keep SGR sequences (ending in 'm'), strip everything else
    if (match.endsWith('m')) return match;
    return '';
  });

  // Create regex per call to avoid shared lastIndex state
  // eslint-disable-next-line no-control-regex
  const sgrRe = /\x1b\[([0-9;]*)m/g;
  let match: RegExpExecArray | null;

  while ((match = sgrRe.exec(cleaned)) !== null) {
    // Text before this escape sequence
    if (match.index > lastIndex) {
      const text = cleaned.slice(lastIndex, match.index);
      if (text) {
        spans.push({ text, style: { ...currentStyle } });
      }
    }
    // Parse the codes
    const codeStr = match[1];
    const codes = codeStr ? codeStr.split(';').map(Number) : [0];
    currentStyle = applyCode(codes, currentStyle);
    lastIndex = match.index + match[0].length;
  }

  // Remaining text after last escape
  if (lastIndex < cleaned.length) {
    const text = cleaned.slice(lastIndex);
    if (text) {
      spans.push({ text, style: { ...currentStyle } });
    }
  }

  return spans;
}

/**
 * Renders a string with ANSI escape codes as styled React elements.
 */
export function AnsiLine({ text }: { text: string }): React.ReactElement {
  // Fast path: no escape sequences at all
  if (!text.includes('\x1b')) {
    return <>{text}</>;
  }

  const spans = parseAnsiString(text);
  return (
    <>
      {spans.map((span, i) => {
        if (Object.keys(span.style).length === 0) {
          return <React.Fragment key={i}>{span.text}</React.Fragment>;
        }
        return (
          <span key={i} style={span.style}>
            {span.text}
          </span>
        );
      })}
    </>
  );
}
