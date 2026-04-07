// ── Monaco cursor → className detection + Tailwind categorization ───
// Used by the Design view's VISUAL tab to detect and edit CSS classes
// at the current cursor position in the Monaco editor.

export interface ClassInfo {
  classes: string[];
  range: {
    lineNumber: number;
    startColumn: number;
    endColumn: number;
  };
  rawValue: string;
  quoteChar: '"' | "'" | '`';
}

/**
 * Detect a className string at the given Monaco cursor position.
 * Supports: className="...", class="...", className={`...`}, cn("..."), clsx("..."), twMerge("...")
 */
export function detectClassesAtCursor(
  model: { getLineContent: (line: number) => string; getLineCount: () => number },
  position: { lineNumber: number; column: number }
): ClassInfo | null {
  const line = model.getLineContent(position.lineNumber);

  // Patterns to match className declarations
  const patterns: { regex: RegExp; quoteGroup: number; valueGroup: number }[] = [
    // className="..." or className='...'
    { regex: /className=["']([^"']*)["']/g, quoteGroup: 0, valueGroup: 1 },
    // class="..." or class='...'
    { regex: /\bclass=["']([^"']*)["']/g, quoteGroup: 0, valueGroup: 1 },
    // className={`...`}
    { regex: /className=\{`([^`]*)`\}/g, quoteGroup: 0, valueGroup: 1 },
    // cn("...") / cn('...')
    { regex: /cn\(\s*["']([^"']*)["']/g, quoteGroup: 0, valueGroup: 1 },
    // clsx("...") / clsx('...')
    { regex: /clsx\(\s*["']([^"']*)["']/g, quoteGroup: 0, valueGroup: 1 },
    // twMerge("...") / twMerge('...')
    { regex: /twMerge\(\s*["']([^"']*)["']/g, quoteGroup: 0, valueGroup: 1 },
    // cva("...") base classes
    { regex: /cva\(\s*["']([^"']*)["']/g, quoteGroup: 0, valueGroup: 1 },
  ];

  for (const { regex, valueGroup } of patterns) {
    regex.lastIndex = 0;
    let match;
    while ((match = regex.exec(line)) !== null) {
      const fullMatch = match[0];
      const value = match[valueGroup];
      // Find where the value string starts in the line
      const fullMatchStart = match.index;
      const valueOffset = fullMatch.indexOf(value);
      const valueStart = fullMatchStart + valueOffset;
      const valueEnd = valueStart + value.length;

      // Check if cursor column is within the value range (1-indexed)
      const col = position.column;
      if (col >= valueStart + 1 && col <= valueEnd + 1) {
        // Determine quote character
        const charBeforeValue = fullMatch[valueOffset - 1];
        const quoteChar = charBeforeValue === "'" ? "'" : charBeforeValue === '`' ? '`' : '"';

        return {
          classes: value.split(/\s+/).filter(Boolean),
          range: {
            lineNumber: position.lineNumber,
            startColumn: valueStart + 1, // Monaco is 1-indexed
            endColumn: valueEnd + 1,
          },
          rawValue: value,
          quoteChar: quoteChar as ClassInfo['quoteChar'],
        };
      }
    }
  }

  // Try multi-line: check if current line is a continuation of a className from a previous line
  // Walk backward to find an opening className=" without a closing "
  return detectMultilineClasses(model, position);
}

function detectMultilineClasses(
  model: { getLineContent: (line: number) => string; getLineCount: () => number },
  position: { lineNumber: number; column: number }
): ClassInfo | null {
  // Walk backward up to 10 lines looking for an unclosed className="
  const maxLookback = 10;
  const startLine = Math.max(1, position.lineNumber - maxLookback);

  let accumulated = '';
  let openLine = -1;
  let openColumn = -1;
  let quoteChar: ClassInfo['quoteChar'] = '"';

  for (let ln = position.lineNumber; ln >= startLine; ln--) {
    const lineContent = model.getLineContent(ln);
    const prefix = ln === position.lineNumber
      ? lineContent.substring(0, position.column - 1)
      : lineContent;

    if (ln === position.lineNumber) {
      accumulated = prefix;
    } else {
      accumulated = lineContent + '\n' + accumulated;
    }

    // Look for className=" or class=" opening
    const openPatterns = [
      /className=["'`]/g,
      /\bclass=["'`]/g,
      /cn\(\s*["'`]/g,
      /clsx\(\s*["'`]/g,
      /twMerge\(\s*["'`]/g,
    ];

    for (const pattern of openPatterns) {
      pattern.lastIndex = 0;
      let m;
      while ((m = pattern.exec(lineContent)) !== null) {
        const q = m[0][m[0].length - 1] as ClassInfo['quoteChar'];
        const afterQuote = lineContent.substring(m.index + m[0].length);
        // Check if this quote is NOT closed on this line
        if (!afterQuote.includes(q) || ln === position.lineNumber) {
          openLine = ln;
          openColumn = m.index + m[0].length + 1; // 1-indexed, after the quote
          quoteChar = q;
        }
      }
    }
  }

  if (openLine === -1) return null;

  // Now find the closing quote on or after the cursor line
  let closeLine = -1;
  let closeColumn = -1;
  let fullValue = '';

  for (let ln = openLine; ln <= Math.min(model.getLineCount(), position.lineNumber + maxLookback); ln++) {
    const lineContent = model.getLineContent(ln);
    const startFrom = ln === openLine ? openColumn - 1 : 0;
    const segment = lineContent.substring(startFrom);

    const closeIdx = segment.indexOf(quoteChar);
    if (closeIdx !== -1) {
      closeLine = ln;
      closeColumn = startFrom + closeIdx + 1;
      fullValue += segment.substring(0, closeIdx);
      break;
    }
    fullValue += segment + ' ';
  }

  if (closeLine === -1) return null;

  // Verify cursor is within the range
  if (
    position.lineNumber < openLine ||
    position.lineNumber > closeLine ||
    (position.lineNumber === openLine && position.column < openColumn) ||
    (position.lineNumber === closeLine && position.column > closeColumn)
  ) {
    return null;
  }

  return {
    classes: fullValue.split(/\s+/).filter(Boolean),
    range: {
      lineNumber: openLine,
      startColumn: openColumn,
      endColumn: closeLine === openLine ? closeColumn : openColumn + fullValue.length,
    },
    rawValue: fullValue.trim(),
    quoteChar,
  };
}

// ── JSX element detection at cursor ─────────────────────────────────

export interface ElementInfo {
  tagName: string;
  props: { name: string; value: string }[];
  isSelfClosing: boolean;
  lineNumber: number;
}

/**
 * Detect the JSX element at the given cursor position.
 * Uses simple regex walking — not a full AST parser.
 */
export function detectElementAtCursor(
  model: { getLineContent: (line: number) => string; getLineCount: () => number },
  position: { lineNumber: number; column: number }
): ElementInfo | null {
  // Walk backward from cursor to find the nearest opening tag
  for (let ln = position.lineNumber; ln >= Math.max(1, position.lineNumber - 20); ln--) {
    const line = model.getLineContent(ln);
    // Match JSX opening tag: <TagName or <tag-name
    const tagPattern = /<([A-Z][A-Za-z0-9.]*|[a-z][a-z0-9-]*)\b/g;
    let match;
    while ((match = tagPattern.exec(line)) !== null) {
      const tagName = match[1];
      // Check if cursor is within or after this tag's scope
      if (ln === position.lineNumber && match.index > position.column - 1) continue;

      // Gather props by reading forward from the tag
      const props = extractProps(model, ln, match.index + match[0].length);

      // Check self-closing
      const restOfTag = getTagContent(model, ln, match.index);
      const isSelfClosing = /\/\s*>/.test(restOfTag);

      return { tagName, props, isSelfClosing, lineNumber: ln };
    }
  }
  return null;
}

function extractProps(
  model: { getLineContent: (line: number) => string; getLineCount: () => number },
  startLine: number,
  startCol: number
): { name: string; value: string }[] {
  const props: { name: string; value: string }[] = [];
  let content = '';

  // Read up to 10 lines forward to get the full tag
  for (let ln = startLine; ln <= Math.min(model.getLineCount(), startLine + 10); ln++) {
    const line = model.getLineContent(ln);
    const start = ln === startLine ? startCol : 0;
    content += line.substring(start) + ' ';
    if (line.includes('>')) break;
  }

  // Extract props: name="value" or name={value} or name (boolean)
  const propPattern = /\b([a-zA-Z_][\w-]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|\{([^}]*)\}))?/g;
  let m;
  while ((m = propPattern.exec(content)) !== null) {
    if (m.index > content.indexOf('>')) break;
    const name = m[1];
    if (name === 'className' || name === 'class') continue; // Handled by classDetection
    const value = m[2] ?? m[3] ?? m[4] ?? 'true';
    props.push({ name, value });
  }

  return props;
}

function getTagContent(
  model: { getLineContent: (line: number) => string; getLineCount: () => number },
  startLine: number,
  startCol: number
): string {
  let content = '';
  for (let ln = startLine; ln <= Math.min(model.getLineCount(), startLine + 10); ln++) {
    const line = model.getLineContent(ln);
    const start = ln === startLine ? startCol : 0;
    content += line.substring(start) + ' ';
    if (line.includes('>')) break;
  }
  return content;
}

// ── Tailwind class categorization ───────────────────────────────────

export interface TailwindCategory {
  name: string;
  color: string;       // Tailwind color class for the left border
  prefixes: string[];
}

const TAILWIND_CATEGORIES: TailwindCategory[] = [
  { name: 'Layout', color: 'border-l-blue-500', prefixes: ['block', 'inline', 'flex', 'grid', 'hidden', 'contents', 'flow', 'table', 'columns', 'break', 'box', 'float', 'clear', 'isolat', 'object', 'overflow', 'overscroll', 'position', 'inset', 'top', 'right', 'bottom', 'left', 'visible', 'invisible', 'z-', 'container'] },
  { name: 'Flexbox', color: 'border-l-indigo-500', prefixes: ['flex-', 'grow', 'shrink', 'order', 'basis', 'justify', 'items-', 'self-', 'place-', 'gap-', 'content-'] },
  { name: 'Grid', color: 'border-l-violet-500', prefixes: ['grid-', 'col-', 'row-', 'auto-cols', 'auto-rows'] },
  { name: 'Spacing', color: 'border-l-green-500', prefixes: ['p-', 'px-', 'py-', 'pt-', 'pr-', 'pb-', 'pl-', 'ps-', 'pe-', 'm-', 'mx-', 'my-', 'mt-', 'mr-', 'mb-', 'ml-', 'ms-', 'me-', 'space-'] },
  { name: 'Sizing', color: 'border-l-teal-500', prefixes: ['w-', 'min-w-', 'max-w-', 'h-', 'min-h-', 'max-h-', 'size-'] },
  { name: 'Typography', color: 'border-l-purple-500', prefixes: ['font-', 'text-xs', 'text-sm', 'text-base', 'text-lg', 'text-xl', 'text-2xl', 'text-3xl', 'text-4xl', 'text-5xl', 'text-6xl', 'text-7xl', 'text-8xl', 'text-9xl', 'tracking-', 'leading-', 'list-', 'decoration-', 'underline', 'overline', 'line-through', 'no-underline', 'uppercase', 'lowercase', 'capitalize', 'normal-case', 'truncate', 'indent-', 'align-', 'whitespace-', 'break-', 'hyphens-', 'content-'] },
  { name: 'Color', color: 'border-l-pink-500', prefixes: ['text-red', 'text-orange', 'text-amber', 'text-yellow', 'text-lime', 'text-green', 'text-emerald', 'text-teal', 'text-cyan', 'text-sky', 'text-blue', 'text-indigo', 'text-violet', 'text-purple', 'text-fuchsia', 'text-pink', 'text-rose', 'text-slate', 'text-gray', 'text-zinc', 'text-neutral', 'text-stone', 'text-white', 'text-black', 'text-transparent', 'text-current', 'text-inherit', 'text-['] },
  { name: 'Background', color: 'border-l-orange-500', prefixes: ['bg-', 'from-', 'via-', 'to-', 'gradient-'] },
  { name: 'Border', color: 'border-l-yellow-500', prefixes: ['border', 'rounded', 'divide-', 'outline-', 'ring-'] },
  { name: 'Effects', color: 'border-l-red-500', prefixes: ['shadow', 'opacity-', 'mix-blend-', 'blur', 'brightness', 'contrast', 'drop-shadow', 'grayscale', 'hue-rotate', 'invert', 'saturate', 'sepia', 'backdrop-'] },
  { name: 'Transition', color: 'border-l-cyan-500', prefixes: ['transition', 'duration-', 'ease-', 'delay-', 'animate-'] },
  { name: 'Transform', color: 'border-l-amber-500', prefixes: ['scale-', 'rotate-', 'translate-', 'skew-', 'origin-', 'transform'] },
  { name: 'Interactivity', color: 'border-l-lime-500', prefixes: ['cursor-', 'caret-', 'pointer-events-', 'resize', 'scroll-', 'snap-', 'touch-', 'select-', 'will-change-', 'appearance-'] },
];

/** Categorize a Tailwind class into its functional group. */
export function categorizeTailwindClass(cls: string): TailwindCategory {
  // Strip responsive/state prefixes (e.g., "md:flex" → "flex", "hover:bg-blue-500" → "bg-blue-500")
  const stripped = cls.replace(/^(?:sm|md|lg|xl|2xl|hover|focus|active|disabled|group-hover|dark|motion-safe|motion-reduce|first|last|odd|even|visited|checked|required|placeholder|selection|marker|before|after|file):/, '');

  for (const category of TAILWIND_CATEGORIES) {
    for (const prefix of category.prefixes) {
      if (stripped.startsWith(prefix) || stripped === prefix) {
        return category;
      }
    }
  }

  return { name: 'Other', color: 'border-l-gray-500', prefixes: [] };
}

/** Get all unique categories present in a list of classes. */
export function getActiveCategories(classes: string[]): TailwindCategory[] {
  const seen = new Set<string>();
  const result: TailwindCategory[] = [];
  for (const cls of classes) {
    const cat = categorizeTailwindClass(cls);
    if (!seen.has(cat.name)) {
      seen.add(cat.name);
      result.push(cat);
    }
  }
  return result;
}
