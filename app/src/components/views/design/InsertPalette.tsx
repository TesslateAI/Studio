import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Search, Send, Code, Type, Layout, FormInput, Image, List } from 'lucide-react';
import type { FileTreeEntry } from '../../../utils/buildFileTree';

// ── Framework detection ────────────────────────────────────────────

type Framework =
  | 'react'
  | 'nextjs'
  | 'vue'
  | 'nuxt'
  | 'svelte'
  | 'sveltekit'
  | 'angular'
  | 'astro'
  | 'html';

function detectFramework(fileTree: FileTreeEntry[]): Framework {
  const paths = fileTree.map((f) => f.path.toLowerCase());
  const hasFile = (pattern: string) => paths.some((p) => p.includes(pattern));

  if (hasFile('next.config') || hasFile('.next/') || hasFile('app/layout.tsx') || hasFile('app/page.tsx'))
    return 'nextjs';
  if (hasFile('svelte.config') || hasFile('+page.svelte')) return 'sveltekit';
  if (paths.some((p) => p.endsWith('.svelte')) && !hasFile('svelte.config')) return 'svelte';
  if (hasFile('nuxt.config')) return 'nuxt';
  if (hasFile('vue.config') || paths.some((p) => p.endsWith('.vue'))) return 'vue';
  if (hasFile('angular.json') || hasFile('.angular')) return 'angular';
  if (hasFile('astro.config')) return 'astro';
  if (hasFile('package.json') && paths.some((p) => p.endsWith('.tsx') || p.endsWith('.jsx')))
    return 'react';
  return 'html';
}

// ── Framework-aware snippet helpers ────────────────────────────────

function classAttr(framework: Framework): string {
  return framework === 'react' || framework === 'nextjs' ? 'className' : 'class';
}

function blockSnippet(tag: string, framework: Framework): string {
  return `<${tag} ${classAttr(framework)}="">\n  \n</${tag}>`;
}

function selfClosingSnippet(tag: string, framework: Framework): string {
  return `<${tag} ${classAttr(framework)}="" />`;
}

function headingSnippet(tag: string, framework: Framework): string {
  return `<${tag} ${classAttr(framework)}="">\n  Heading\n</${tag}>`;
}

function inputSnippet(type: string, framework: Framework): string {
  return `<input type="${type}" ${classAttr(framework)}="" />`;
}

// ── Element category types ─────────────────────────────────────────

type ElementCategory = 'layout' | 'text' | 'form' | 'media' | 'list' | 'table' | 'semantic';

interface ElementEntry {
  label: string;
  snippet: string;
  category: ElementCategory;
}

interface ComponentEntry {
  label: string;
  snippet: string;
  importPath: string;
}

interface PatternEntry {
  label: string;
  snippet: string;
}

// ── Category icon & color mapping ──────────────────────────────────

const CATEGORY_META: Record<ElementCategory, { icon: React.ElementType; color: string; label: string }> = {
  layout:   { icon: Layout,    color: 'text-blue-400',   label: 'Layout' },
  text:     { icon: Type,      color: 'text-purple-400', label: 'Text' },
  form:     { icon: FormInput, color: 'text-green-400',  label: 'Form' },
  media:    { icon: Image,     color: 'text-pink-400',   label: 'Media' },
  list:     { icon: List,      color: 'text-amber-400',  label: 'Lists' },
  table:    { icon: Layout,    color: 'text-cyan-400',   label: 'Table' },
  semantic: { icon: Code,      color: 'text-teal-400',   label: 'Semantic' },
};

// ── Element definitions (framework-agnostic structure) ─────────────

interface ElementDef {
  label: string;
  category: ElementCategory;
  build: (fw: Framework) => string;
}

const ELEMENT_DEFS: ElementDef[] = [
  // Layout
  { label: 'div',        category: 'layout',   build: (fw) => blockSnippet('div', fw) },
  { label: 'section',    category: 'layout',   build: (fw) => blockSnippet('section', fw) },
  { label: 'header',     category: 'layout',   build: (fw) => blockSnippet('header', fw) },
  { label: 'footer',     category: 'layout',   build: (fw) => blockSnippet('footer', fw) },
  { label: 'nav',        category: 'layout',   build: (fw) => blockSnippet('nav', fw) },
  { label: 'main',       category: 'layout',   build: (fw) => blockSnippet('main', fw) },
  { label: 'article',    category: 'layout',   build: (fw) => blockSnippet('article', fw) },
  { label: 'aside',      category: 'layout',   build: (fw) => blockSnippet('aside', fw) },
  // Text
  { label: 'h1',         category: 'text',     build: (fw) => headingSnippet('h1', fw) },
  { label: 'h2',         category: 'text',     build: (fw) => headingSnippet('h2', fw) },
  { label: 'h3',         category: 'text',     build: (fw) => headingSnippet('h3', fw) },
  { label: 'h4',         category: 'text',     build: (fw) => headingSnippet('h4', fw) },
  { label: 'h5',         category: 'text',     build: (fw) => headingSnippet('h5', fw) },
  { label: 'h6',         category: 'text',     build: (fw) => headingSnippet('h6', fw) },
  { label: 'p',          category: 'text',     build: (fw) => blockSnippet('p', fw) },
  { label: 'span',       category: 'text',     build: (fw) => blockSnippet('span', fw) },
  { label: 'a',          category: 'text',     build: (fw) => `<a href="" ${classAttr(fw)}="">\n  \n</a>` },
  { label: 'blockquote', category: 'text',     build: (fw) => blockSnippet('blockquote', fw) },
  // Form
  { label: 'form',       category: 'form',     build: (fw) => blockSnippet('form', fw) },
  { label: 'input',      category: 'form',     build: (fw) => inputSnippet('text', fw) },
  { label: 'textarea',   category: 'form',     build: (fw) => selfClosingSnippet('textarea', fw) },
  { label: 'select',     category: 'form',     build: (fw) => blockSnippet('select', fw) },
  { label: 'button',     category: 'form',     build: (fw) => blockSnippet('button', fw) },
  { label: 'label',      category: 'form',     build: (fw) => blockSnippet('label', fw) },
  { label: 'checkbox',   category: 'form',     build: (fw) => inputSnippet('checkbox', fw) },
  { label: 'radio',      category: 'form',     build: (fw) => inputSnippet('radio', fw) },
  // Media
  { label: 'img',        category: 'media',    build: (fw) => `<img src="" alt="" ${classAttr(fw)}="" />` },
  { label: 'video',      category: 'media',    build: (fw) => `<video src="" ${classAttr(fw)}="" controls />` },
  { label: 'audio',      category: 'media',    build: (fw) => `<audio src="" ${classAttr(fw)}="" controls />` },
  { label: 'canvas',     category: 'media',    build: (fw) => blockSnippet('canvas', fw) },
  { label: 'svg',        category: 'media',    build: (fw) => blockSnippet('svg', fw) },
  // Lists
  { label: 'ul',         category: 'list',     build: (fw) => blockSnippet('ul', fw) },
  { label: 'ol',         category: 'list',     build: (fw) => blockSnippet('ol', fw) },
  { label: 'li',         category: 'list',     build: (fw) => blockSnippet('li', fw) },
  { label: 'dl',         category: 'list',     build: (fw) => blockSnippet('dl', fw) },
  { label: 'dt',         category: 'list',     build: (fw) => blockSnippet('dt', fw) },
  { label: 'dd',         category: 'list',     build: (fw) => blockSnippet('dd', fw) },
  // Table
  { label: 'table',      category: 'table',    build: (fw) => blockSnippet('table', fw) },
  { label: 'thead',      category: 'table',    build: (fw) => blockSnippet('thead', fw) },
  { label: 'tbody',      category: 'table',    build: (fw) => blockSnippet('tbody', fw) },
  { label: 'tr',         category: 'table',    build: (fw) => blockSnippet('tr', fw) },
  { label: 'th',         category: 'table',    build: (fw) => blockSnippet('th', fw) },
  { label: 'td',         category: 'table',    build: (fw) => blockSnippet('td', fw) },
  // Semantic
  { label: 'figure',     category: 'semantic', build: (fw) => blockSnippet('figure', fw) },
  { label: 'figcaption', category: 'semantic', build: (fw) => blockSnippet('figcaption', fw) },
  { label: 'details',    category: 'semantic', build: (fw) => blockSnippet('details', fw) },
  { label: 'summary',    category: 'semantic', build: (fw) => blockSnippet('summary', fw) },
  { label: 'dialog',     category: 'semantic', build: (fw) => blockSnippet('dialog', fw) },
  { label: 'time',       category: 'semantic', build: (fw) => blockSnippet('time', fw) },
];

function buildElements(framework: Framework): ElementEntry[] {
  return ELEMENT_DEFS.map((def) => ({
    label: def.label,
    snippet: def.build(framework),
    category: def.category,
  }));
}

// ── Framework-specific pattern definitions ──────────────────────────

const PATTERN_DEFS: Record<string, PatternEntry[]> = {
  react: [
    { label: 'Conditional render', snippet: '{condition && (\n  <div>\n    \n  </div>\n)}' },
    { label: 'Map / list', snippet: '{items.map((item) => (\n  <div key={item.id}>\n    {item.name}\n  </div>\n))}' },
    { label: 'Fragment', snippet: '<>\n  \n</>' },
    { label: 'Suspense', snippet: '<Suspense fallback={<Loading />}>\n  \n</Suspense>' },
  ],
  nextjs: [
    { label: 'Conditional render', snippet: '{condition && (\n  <div>\n    \n  </div>\n)}' },
    { label: 'Map / list', snippet: '{items.map((item) => (\n  <div key={item.id}>\n    {item.name}\n  </div>\n))}' },
    { label: 'Fragment', snippet: '<>\n  \n</>' },
    { label: 'Suspense', snippet: '<Suspense fallback={<Loading />}>\n  \n</Suspense>' },
    { label: 'Link', snippet: '<Link href="">\n  \n</Link>' },
    { label: 'Image', snippet: '<Image src="" alt="" width={0} height={0} />' },
  ],
  vue: [
    { label: 'v-for', snippet: '<div v-for="item in items" :key="item.id">\n  {{ item.name }}\n</div>' },
    { label: 'v-if', snippet: '<div v-if="condition">\n  \n</div>' },
    { label: 'slot', snippet: '<slot name="default" />' },
    { label: 'component', snippet: '<component :is="currentComponent" />' },
  ],
  nuxt: [
    { label: 'v-for', snippet: '<div v-for="item in items" :key="item.id">\n  {{ item.name }}\n</div>' },
    { label: 'v-if', snippet: '<div v-if="condition">\n  \n</div>' },
    { label: 'NuxtLink', snippet: '<NuxtLink to="">\n  \n</NuxtLink>' },
    { label: 'slot', snippet: '<slot name="default" />' },
  ],
  svelte: [
    { label: 'each', snippet: '{#each items as item}\n  <div>{item.name}</div>\n{/each}' },
    { label: 'if', snippet: '{#if condition}\n  \n{/if}' },
    { label: 'await', snippet: '{#await promise}\n  Loading...\n{:then data}\n  {data}\n{/await}' },
  ],
  sveltekit: [
    { label: 'each', snippet: '{#each items as item}\n  <div>{item.name}</div>\n{/each}' },
    { label: 'if', snippet: '{#if condition}\n  \n{/if}' },
    { label: 'await', snippet: '{#await promise}\n  Loading...\n{:then data}\n  {data}\n{/await}' },
    { label: 'enhance', snippet: '<form method="POST" use:enhance>\n  \n</form>' },
  ],
  angular: [
    { label: '*ngFor', snippet: '<div *ngFor="let item of items">\n  {{ item.name }}\n</div>' },
    { label: '*ngIf', snippet: '<div *ngIf="condition">\n  \n</div>' },
    { label: 'ng-content', snippet: '<ng-content select=""></ng-content>' },
    { label: 'routerLink', snippet: '<a routerLink="">\n  \n</a>' },
  ],
  astro: [
    { label: 'Slot', snippet: '<slot name="default" />' },
    { label: 'Client directive', snippet: '<Component client:load />' },
    { label: 'Frontmatter', snippet: '---\n\n---' },
  ],
  html: [
    { label: 'Link', snippet: '<a href="" target="_blank" rel="noopener">\n  \n</a>' },
    { label: 'Picture', snippet: '<picture>\n  <source srcset="" type="" />\n  <img src="" alt="" />\n</picture>' },
    { label: 'Template', snippet: '<template>\n  \n</template>' },
  ],
};

function getPatterns(framework: Framework): PatternEntry[] {
  return PATTERN_DEFS[framework] ?? [];
}

// ── Component detection ────────────────────────────────────────────

/** Convert a filename to PascalCase component name. */
function filenameToComponentName(filename: string): string {
  const base = filename.replace(/\.(tsx|jsx|vue|svelte|component\.ts)$/, '');
  return base
    .split(/[-_.]/)
    .map((seg) => seg.charAt(0).toUpperCase() + seg.slice(1))
    .join('');
}

/** Files/directories to exclude from component scanning. */
const EXCLUDED_PATTERNS = [
  /\/(pages|routes|layouts?|__tests__|__mocks__|stories|hooks|use[A-Z]|utils|lib|types|config|styles|assets)\//i,
  /\.(test|spec|stories|story|d)\.[^/]+$/,
  /^index\./,
];

function isComponentFile(path: string, name: string, framework: Framework): boolean {
  // Must not match any exclude pattern
  if (EXCLUDED_PATTERNS.some((re) => re.test(path) || re.test(name))) return false;

  switch (framework) {
    case 'react':
    case 'nextjs':
      return /\.(tsx|jsx)$/.test(name) && /^[A-Z]/.test(name);
    case 'vue':
    case 'nuxt':
      return /\.vue$/.test(name);
    case 'svelte':
    case 'sveltekit':
      return /\.svelte$/.test(name) && /^[A-Z]/.test(name);
    case 'angular':
      return /\.component\.ts$/.test(name);
    default:
      return false;
  }
}

/**
 * Compute a short import path from a file path.
 * Strips common root prefixes (src/, app/, lib/) and the extension.
 */
function computeImportPath(filePath: string): string {
  let rel = filePath.replace(/^\/?(src|app|lib)\//, '');
  // Remove file extension
  rel = rel.replace(/\.(tsx|jsx|vue|svelte|component\.ts)$/, '');
  return `@/${rel}`;
}

function detectComponents(fileTree: FileTreeEntry[], framework: Framework): ComponentEntry[] {
  const seen = new Set<string>();
  const entries: ComponentEntry[] = [];

  for (const entry of fileTree) {
    if (entry.is_dir) continue;
    if (!isComponentFile(entry.path, entry.name, framework)) continue;

    const name = filenameToComponentName(entry.name);
    if (seen.has(name)) continue;
    seen.add(name);

    const importPath = computeImportPath(entry.path);

    let snippet: string;
    switch (framework) {
      case 'vue':
      case 'nuxt':
        snippet = `<!-- import ${name} from '${importPath}' -->\n<${name} />`;
        break;
      case 'svelte':
      case 'sveltekit':
        snippet = `<!-- import ${name} from '${importPath}' -->\n<${name} />`;
        break;
      case 'angular':
        snippet = `<!-- ${name} from '${importPath}' -->\n<app-${name.replace(/([A-Z])/g, (_, c, i) => (i ? '-' : '') + c.toLowerCase()).replace(/^-/, '')} />`;
        break;
      default:
        snippet = `{/* import { ${name} } from '${importPath}' */}\n<${name} />`;
        break;
    }

    entries.push({ label: name, snippet, importPath });
  }

  return entries.sort((a, b) => a.label.localeCompare(b.label));
}

// ── Framework display name ─────────────────────────────────────────

const FRAMEWORK_LABELS: Record<Framework, string> = {
  react: 'React',
  nextjs: 'Next.js',
  vue: 'Vue',
  nuxt: 'Nuxt',
  svelte: 'Svelte',
  sveltekit: 'SvelteKit',
  angular: 'Angular',
  astro: 'Astro',
  html: 'HTML',
};

// ── InsertPalette component ────────────────────────────────────────

interface InsertPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onInsert: (snippet: string) => void;
  onAIAssist: (prompt: string) => void;
  fileTree: FileTreeEntry[];
}

export function InsertPalette({
  isOpen,
  onClose,
  onInsert,
  onAIAssist,
  fileTree,
}: InsertPaletteProps) {
  const [filter, setFilter] = useState('');
  const [aiPrompt, setAiPrompt] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);
  const filterInputRef = useRef<HTMLInputElement>(null);

  // Detect framework once when file tree changes
  const framework = useMemo(() => detectFramework(fileTree), [fileTree]);

  // Build elements for the detected framework
  const elements = useMemo(() => buildElements(framework), [framework]);

  // Get framework-specific patterns
  const patterns = useMemo(() => getPatterns(framework), [framework]);

  // Detect project components
  const components = useMemo(() => detectComponents(fileTree, framework), [fileTree, framework]);

  const lowerFilter = filter.toLowerCase();

  // Filter each section
  const filteredPatterns = useMemo(
    () =>
      lowerFilter
        ? patterns.filter((p) => p.label.toLowerCase().includes(lowerFilter))
        : patterns,
    [lowerFilter, patterns],
  );

  const filteredComponents = useMemo(
    () =>
      lowerFilter
        ? components.filter((c) => c.label.toLowerCase().includes(lowerFilter))
        : components,
    [lowerFilter, components],
  );

  const filteredElements = useMemo(
    () =>
      lowerFilter
        ? elements.filter((e) => e.label.toLowerCase().includes(lowerFilter))
        : elements,
    [lowerFilter, elements],
  );

  // Group filtered elements by category, preserving category order
  const groupedElements = useMemo(() => {
    const groups: { category: ElementCategory; items: ElementEntry[] }[] = [];
    const categoryOrder: ElementCategory[] = ['layout', 'text', 'form', 'media', 'list', 'table', 'semantic'];

    for (const cat of categoryOrder) {
      const items = filteredElements.filter((e) => e.category === cat);
      if (items.length > 0) {
        groups.push({ category: cat, items });
      }
    }
    return groups;
  }, [filteredElements]);

  const hasAnyResults =
    filteredPatterns.length > 0 || filteredComponents.length > 0 || filteredElements.length > 0;

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return;

    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        onClose();
      }
    }

    const id = requestAnimationFrame(() => {
      document.addEventListener('mousedown', handleClickOutside);
    });

    return () => {
      cancelAnimationFrame(id);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen, onClose]);

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        onClose();
      }
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Focus filter input on open
  useEffect(() => {
    if (isOpen) {
      setFilter('');
      setAiPrompt('');
      requestAnimationFrame(() => filterInputRef.current?.focus());
    }
  }, [isOpen]);

  const handleAISubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = aiPrompt.trim();
      if (!trimmed) return;
      onAIAssist(trimmed);
      setAiPrompt('');
      onClose();
    },
    [aiPrompt, onAIAssist, onClose],
  );

  if (!isOpen) return null;

  return (
    <div
      ref={containerRef}
      className="absolute top-full left-0 mt-1 z-50 w-80 max-h-[28rem] overflow-y-auto bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius)] shadow-xl"
    >
      {/* Search / filter (sticky) */}
      <div className="sticky top-0 z-10 bg-[var(--surface)] border-b border-[var(--border)] px-3 py-2 flex items-center gap-2">
        <Search size={12} className="text-[var(--text-subtle)] flex-shrink-0" />
        <input
          ref={filterInputRef}
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter elements..."
          className="flex-1 bg-transparent text-xs text-[var(--text)] placeholder:text-[var(--text-subtle)] outline-none"
        />
        <span className="text-[9px] px-1 py-0.5 rounded bg-[var(--primary)]/10 text-[var(--primary)] flex-shrink-0">
          {FRAMEWORK_LABELS[framework]}
        </span>
      </div>

      {/* Patterns */}
      {filteredPatterns.length > 0 && (
        <div>
          <div className="text-[10px] font-medium text-[var(--text-subtle)] uppercase tracking-wider px-3 py-2">
            Patterns
          </div>
          <div>
            {filteredPatterns.map((pat) => (
              <button
                key={pat.label}
                onClick={() => onInsert(pat.snippet)}
                className="w-full px-3 py-1.5 text-left text-xs text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] flex items-center gap-2 transition-colors"
              >
                <Code size={10} className="text-[var(--primary)] flex-shrink-0" />
                <span className="truncate">{pat.label}</span>
                <span className="ml-auto text-[9px] px-1 py-0.5 rounded bg-[var(--primary)]/10 text-[var(--primary)] flex-shrink-0">
                  {FRAMEWORK_LABELS[framework]}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Divider after patterns */}
      {filteredPatterns.length > 0 && (filteredComponents.length > 0 || filteredElements.length > 0) && (
        <div className="h-px bg-[var(--border)] my-1" />
      )}

      {/* Components */}
      {filteredComponents.length > 0 && (
        <div>
          <div className="text-[10px] font-medium text-[var(--text-subtle)] uppercase tracking-wider px-3 py-2">
            Components
          </div>
          <div>
            {filteredComponents.map((comp) => (
              <button
                key={comp.label}
                onClick={() => onInsert(comp.snippet)}
                className="w-full px-3 py-1.5 text-left text-xs text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] flex items-center gap-2 transition-colors"
              >
                <span className="text-[var(--primary)] font-mono text-[10px] flex-shrink-0">&lt;/&gt;</span>
                <span className="truncate">{comp.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Divider before elements */}
      {filteredComponents.length > 0 && filteredElements.length > 0 && (
        <div className="h-px bg-[var(--border)] my-1" />
      )}

      {/* Elements grouped by category */}
      {groupedElements.map((group) => {
        const meta = CATEGORY_META[group.category];
        const Icon = meta.icon;
        return (
          <div key={group.category}>
            <div className="text-[10px] font-medium text-[var(--text-subtle)] uppercase tracking-wider px-3 py-2">
              {meta.label}
            </div>
            <div>
              {group.items.map((el) => (
                <button
                  key={el.label}
                  onClick={() => onInsert(el.snippet)}
                  className="w-full px-3 py-1.5 text-left text-xs text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] flex items-center gap-2 transition-colors"
                >
                  <Icon size={10} className={`${meta.color} flex-shrink-0`} />
                  <span>{el.label}</span>
                </button>
              ))}
            </div>
          </div>
        );
      })}

      {/* Divider before AI */}
      <div className="h-px bg-[var(--border)] my-1" />

      {/* AI Assist */}
      <div>
        <div className="text-[10px] font-medium text-[var(--text-subtle)] uppercase tracking-wider px-3 py-2">
          AI Assist
        </div>
        <form onSubmit={handleAISubmit} className="px-3 pb-3 flex items-center gap-2">
          <input
            type="text"
            value={aiPrompt}
            onChange={(e) => setAiPrompt(e.target.value)}
            placeholder="Describe what you want..."
            className="flex-1 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] px-2 py-1.5 text-xs text-[var(--text)] placeholder:text-[var(--text-subtle)] outline-none focus:border-[var(--primary)]"
          />
          <button
            type="submit"
            disabled={!aiPrompt.trim()}
            className="p-1.5 rounded-[var(--radius-small)] text-[var(--text-subtle)] hover:text-[var(--primary)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <Send size={14} />
          </button>
        </form>
      </div>

      {/* Empty state */}
      {!hasAnyResults && filter && (
        <div className="px-3 py-4 text-center text-xs text-[var(--text-subtle)]">
          No matches for &ldquo;{filter}&rdquo;
        </div>
      )}
    </div>
  );
}
