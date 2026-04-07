import React, { useState, useMemo, useRef, useCallback, useEffect } from 'react';
import { Info, ChevronDown, ChevronRight, ExternalLink, Plus, X } from 'lucide-react';
import type { ElementData } from './DesignBridge';
import type { ElementInfo } from '../../../utils/classDetection';

// ── Props ──────────────────────────────────────────────────────────────

interface InspectorTabProps {
  selectedElement: ElementData | null;
  cursorElement: ElementInfo | null;
  onStyleUpdate?: (designId: string, property: string, value: string) => void;
  onStyleRemove?: (designId: string, property: string) => void;
  onSwitchToVisual?: () => void;
}

// ── CSS Value Options for Smart Dropdowns ─────────────────────────────

const CSS_VALUE_OPTIONS: Record<string, string[]> = {
  'display': ['block', 'inline', 'inline-block', 'flex', 'inline-flex', 'grid', 'inline-grid', 'none', 'contents', 'table', 'list-item'],
  'position': ['static', 'relative', 'absolute', 'fixed', 'sticky'],
  'overflow': ['visible', 'hidden', 'scroll', 'auto', 'clip'],
  'overflow-x': ['visible', 'hidden', 'scroll', 'auto', 'clip'],
  'overflow-y': ['visible', 'hidden', 'scroll', 'auto', 'clip'],
  'float': ['none', 'left', 'right', 'inline-start', 'inline-end'],
  'clear': ['none', 'left', 'right', 'both'],
  'text-align': ['left', 'center', 'right', 'justify', 'start', 'end'],
  'text-decoration': ['none', 'underline', 'overline', 'line-through'],
  'text-transform': ['none', 'uppercase', 'lowercase', 'capitalize'],
  'font-style': ['normal', 'italic', 'oblique'],
  'font-weight': ['100', '200', '300', '400', '500', '600', '700', '800', '900', 'normal', 'bold', 'lighter', 'bolder'],
  'white-space': ['normal', 'nowrap', 'pre', 'pre-wrap', 'pre-line', 'break-spaces'],
  'word-break': ['normal', 'break-all', 'keep-all', 'break-word'],
  'flex-direction': ['row', 'row-reverse', 'column', 'column-reverse'],
  'flex-wrap': ['nowrap', 'wrap', 'wrap-reverse'],
  'justify-content': ['flex-start', 'flex-end', 'center', 'space-between', 'space-around', 'space-evenly', 'start', 'end'],
  'align-items': ['stretch', 'flex-start', 'flex-end', 'center', 'baseline', 'start', 'end'],
  'align-self': ['auto', 'stretch', 'flex-start', 'flex-end', 'center', 'baseline'],
  'cursor': ['auto', 'default', 'pointer', 'move', 'text', 'wait', 'crosshair', 'not-allowed', 'grab', 'grabbing', 'none'],
  'pointer-events': ['auto', 'none'],
  'visibility': ['visible', 'hidden', 'collapse'],
  'border-style': ['none', 'solid', 'dashed', 'dotted', 'double', 'groove', 'ridge', 'inset', 'outset'],
  'box-sizing': ['content-box', 'border-box'],
  'list-style-type': ['none', 'disc', 'circle', 'square', 'decimal', 'lower-alpha', 'upper-alpha'],
};

// ── Style group definitions ────────────────────────────────────────────

interface StyleGroup {
  label: string;
  keys: string[];
  /** Only show when display matches one of these values */
  displayFilter?: string[];
}

const STYLE_GROUPS: StyleGroup[] = [
  {
    label: 'Layout',
    keys: ['display', 'position', 'overflow', 'float', 'clear'],
  },
  {
    label: 'Size',
    keys: ['width', 'height', 'min-width', 'max-width', 'min-height', 'max-height'],
  },
  {
    label: 'Typography',
    keys: [
      'font-family',
      'font-size',
      'font-weight',
      'color',
      'line-height',
      'letter-spacing',
      'text-align',
    ],
  },
  {
    label: 'Background',
    keys: ['background-color', 'background-image'],
  },
  {
    label: 'Flex / Grid',
    keys: ['flex-direction', 'justify-content', 'align-items', 'gap'],
    displayFilter: ['flex', 'inline-flex', 'grid', 'inline-grid'],
  },
];

// ── Common CSS properties for autocomplete ─────────────────────────────

const COMMON_CSS_PROPERTIES = [
  'display', 'position', 'top', 'right', 'bottom', 'left', 'z-index',
  'width', 'height', 'min-width', 'max-width', 'min-height', 'max-height',
  'margin', 'margin-top', 'margin-right', 'margin-bottom', 'margin-left',
  'padding', 'padding-top', 'padding-right', 'padding-bottom', 'padding-left',
  'border', 'border-width', 'border-style', 'border-color', 'border-radius',
  'font-family', 'font-size', 'font-weight', 'font-style', 'line-height',
  'letter-spacing', 'text-align', 'text-decoration', 'text-transform',
  'color', 'background', 'background-color', 'background-image',
  'opacity', 'overflow', 'cursor', 'pointer-events',
  'flex', 'flex-direction', 'flex-wrap', 'justify-content', 'align-items',
  'align-self', 'gap', 'row-gap', 'column-gap', 'order', 'flex-grow', 'flex-shrink',
  'grid-template-columns', 'grid-template-rows', 'grid-column', 'grid-row',
  'box-shadow', 'text-shadow', 'transform', 'transition', 'animation',
  'white-space', 'word-break', 'overflow-wrap',
];

// ── Color detection ────────────────────────────────────────────────────

const COLOR_PROPERTIES = new Set([
  'color', 'background-color', 'border-color',
  'border-top-color', 'border-right-color', 'border-bottom-color', 'border-left-color',
  'outline-color', 'text-decoration-color', 'caret-color', 'accent-color',
  'column-rule-color', 'flood-color', 'lighting-color', 'stop-color',
]);

function isColorValue(property: string, value: string): boolean {
  if (COLOR_PROPERTIES.has(property)) return true;
  return /^(#[0-9a-f]{3,8}|rgba?\(|hsla?\()/i.test(value);
}

/** Convert CSS color string to hex for the native color input. */
function colorToHex(value: string): string {
  if (value.startsWith('#')) {
    const hex = value.replace('#', '');
    if (hex.length === 3) {
      return '#' + hex.split('').map((c) => c + c).join('');
    }
    return '#' + hex.slice(0, 6);
  }
  const rgbMatch = value.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  if (rgbMatch) {
    const r = parseInt(rgbMatch[1], 10).toString(16).padStart(2, '0');
    const g = parseInt(rgbMatch[2], 10).toString(16).padStart(2, '0');
    const b = parseInt(rgbMatch[3], 10).toString(16).padStart(2, '0');
    return `#${r}${g}${b}`;
  }
  return '#000000';
}

// ── Helpers ────────────────────────────────────────────────────────────

/** Convert a camelCase computed-style key to kebab-case for display. */
function toKebab(key: string): string {
  return key.replace(/([A-Z])/g, '-$1').toLowerCase();
}

/** Parse a CSS shorthand or individual value into a numeric px string. */
function extractPx(value: string | undefined): string {
  if (!value) return '0';
  const match = value.match(/([\d.]+)px/);
  return match ? Math.round(parseFloat(match[1])).toString() : '0';
}

/** Get box-model values from computed styles (handles both camelCase and kebab-case). */
function boxValue(
  styles: Record<string, string>,
  prefix: string,
  side: string,
): string {
  const kebab = `${prefix}-${side}`;
  const camel = prefix + side.charAt(0).toUpperCase() + side.slice(1);
  return extractPx(styles[kebab] ?? styles[camel]);
}

// ── Sub-components ─────────────────────────────────────────────────────

function SectionHeader({
  children,
  trailing,
}: {
  children: React.ReactNode;
  trailing?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between mb-2">
      <span className="text-[11px] font-medium text-[var(--text-muted)] uppercase tracking-wider">
        {children}
      </span>
      {trailing}
    </div>
  );
}

function CountBadge({ count }: { count: number }) {
  return (
    <span className="ml-1.5 inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full bg-[var(--surface)] text-[10px] font-mono text-[var(--text-subtle)]">
      {count}
    </span>
  );
}

// ── Smart Value Editor ────────────────────────────────────────────────
// Renders a dropdown for known CSS property values, a color picker for
// color properties, or a click-to-edit text input for everything else.

function SmartValueEditor({
  property,
  value,
  onCommit,
}: {
  property: string;
  value: string;
  onCommit: (property: string, newValue: string) => void;
}) {
  const options = CSS_VALUE_OPTIONS[property];
  const showColor = isColorValue(property, value);
  const isKnownOption = options ? options.includes(value) : false;

  const [customMode, setCustomMode] = useState(!isKnownOption && !!options);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);
  const colorInputRef = useRef<HTMLInputElement>(null);

  // Sync custom mode when value changes externally
  useEffect(() => {
    if (options) {
      setCustomMode(!options.includes(value));
    }
  }, [value, options]);

  // Sync draft when not editing
  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  // Focus input when entering edit mode
  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  const commit = () => {
    setEditing(false);
    if (draft !== value) {
      onCommit(property, draft);
    }
  };

  const cancel = () => {
    setEditing(false);
    setDraft(value);
  };

  const handleColorChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const hex = e.target.value;
    setDraft(hex);
    onCommit(property, hex);
  };

  const handleSelectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const selected = e.target.value;
    if (selected === '__other__') {
      setCustomMode(true);
      setEditing(true);
      setDraft(value);
    } else {
      setCustomMode(false);
      onCommit(property, selected);
    }
  };

  const selectCls =
    'text-[10px] font-mono bg-[var(--surface)] text-[var(--text)] border border-[var(--border)] ' +
    'rounded-[var(--radius-small)] px-1 py-0.5 outline-none focus:border-[var(--primary)] ' +
    'appearance-none cursor-pointer min-h-[24px] sm:min-h-0';

  return (
    <div className="flex items-center gap-1 max-w-[140px] justify-end flex-wrap">
      {/* Color swatch */}
      {showColor && (
        <div className="relative shrink-0">
          <div
            className="w-3 h-3 rounded-sm cursor-pointer shrink-0"
            style={{
              backgroundColor: value,
              border: '1px solid rgba(255,255,255,0.15)',
            }}
            onClick={() => colorInputRef.current?.click()}
          />
          <input
            ref={colorInputRef}
            type="color"
            value={colorToHex(value)}
            onChange={handleColorChange}
            className="absolute top-0 left-0 w-0 h-0 opacity-0 pointer-events-none"
            tabIndex={-1}
          />
        </div>
      )}

      {/* Dropdown for known CSS values */}
      {options && !customMode ? (
        <select
          value={isKnownOption ? value : '__other__'}
          onChange={handleSelectChange}
          className={selectCls}
        >
          {options.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
          <option value="__other__">Other...</option>
        </select>
      ) : editing ? (
        /* Text input (editing mode) */
        <input
          ref={inputRef}
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
            if (e.key === 'Escape') cancel();
          }}
          className="bg-transparent border-b border-[var(--primary)] text-[10px] font-mono text-[var(--text)] outline-none w-full text-right"
        />
      ) : (
        /* Static value (click to edit) */
        <span
          className="text-[10px] font-mono text-[var(--text-muted)] truncate text-right cursor-text"
          onClick={() => setEditing(true)}
          title={value}
        >
          {value}
        </span>
      )}

      {/* When in custom mode with a dropdown property, show back-to-select hint */}
      {options && customMode && !editing && (
        <button
          type="button"
          onClick={() => {
            setCustomMode(false);
          }}
          className="text-[8px] text-[var(--text-subtle)] hover:text-[var(--primary)] transition-colors"
          title="Switch to dropdown"
        >
          <ChevronDown size={8} />
        </button>
      )}
    </div>
  );
}

// ── Editable Box Model Value ──────────────────────────────────────────

function EditableBoxValue({
  value,
  cssProperty,
  colorClass,
  onCommit,
}: {
  value: string;
  cssProperty: string;
  colorClass: string;
  onCommit: (property: string, newValue: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  const commit = () => {
    setEditing(false);
    if (draft !== value) {
      onCommit(cssProperty, draft);
    }
  };

  const cancel = () => {
    setEditing(false);
    setDraft(value);
  };

  const valClass = 'text-[10px] font-mono leading-none';

  if (editing) {
    return (
      <input
        ref={inputRef}
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') cancel();
        }}
        className={`${valClass} ${colorClass} bg-transparent border-b border-[var(--primary)] outline-none text-center w-[30px]`}
      />
    );
  }

  return (
    <span
      className={`${valClass} ${colorClass} cursor-text`}
      onClick={() => setEditing(true)}
    >
      {value}
    </span>
  );
}

// ── Box Model Diagram ─────────────────────────────────────────────────

function BoxModelDiagram({
  styles,
  onCommit,
}: {
  styles: Record<string, string>;
  onCommit?: (property: string, value: string) => void;
}) {
  const m = {
    top: boxValue(styles, 'margin', 'top'),
    right: boxValue(styles, 'margin', 'right'),
    bottom: boxValue(styles, 'margin', 'bottom'),
    left: boxValue(styles, 'margin', 'left'),
  };
  const b = {
    top: boxValue(styles, 'border', 'top-width'),
    right: boxValue(styles, 'border', 'right-width'),
    bottom: boxValue(styles, 'border', 'bottom-width'),
    left: boxValue(styles, 'border', 'left-width'),
  };
  const p = {
    top: boxValue(styles, 'padding', 'top'),
    right: boxValue(styles, 'padding', 'right'),
    bottom: boxValue(styles, 'padding', 'bottom'),
    left: boxValue(styles, 'padding', 'left'),
  };

  const contentW = extractPx(styles['width'] ?? styles.width);
  const contentH = extractPx(styles['height'] ?? styles.height);

  const valClass = 'text-[10px] font-mono leading-none';
  const handleCommit = onCommit ?? (() => {});

  const renderVal = (v: string, prop: string, colorCls: string) => {
    if (onCommit) {
      return (
        <EditableBoxValue
          value={v}
          cssProperty={prop}
          colorClass={colorCls}
          onCommit={handleCommit}
        />
      );
    }
    return <span className={`${valClass} ${colorCls}`}>{v}</span>;
  };

  return (
    <div className="flex items-center justify-center">
      {/* Margin */}
      <div className="relative bg-orange-500/10 border border-orange-500/30 rounded p-3 w-full max-w-[220px] sm:w-[200px]">
        <span className="absolute top-0.5 left-1 text-[8px] font-mono text-orange-400/60">
          margin
        </span>
        <div className="flex justify-center">
          {renderVal(m.top, 'margin-top', 'text-orange-300')}
        </div>
        <div className="flex items-center justify-between">
          {renderVal(m.left, 'margin-left', 'text-orange-300')}

          {/* Border */}
          <div className="relative bg-yellow-500/10 border border-yellow-500/30 rounded p-2.5 flex-1 mx-1">
            <span className="absolute top-0.5 left-1 text-[8px] font-mono text-yellow-400/60">
              border
            </span>
            <div className="flex justify-center">
              {renderVal(b.top, 'border-top-width', 'text-yellow-300')}
            </div>
            <div className="flex items-center justify-between">
              {renderVal(b.left, 'border-left-width', 'text-yellow-300')}

              {/* Padding */}
              <div className="relative bg-green-500/10 border border-green-500/30 rounded p-2 flex-1 mx-1">
                <span className="absolute top-0.5 left-1 text-[8px] font-mono text-green-400/60">
                  padding
                </span>
                <div className="flex justify-center">
                  {renderVal(p.top, 'padding-top', 'text-green-300')}
                </div>
                <div className="flex items-center justify-between">
                  {renderVal(p.left, 'padding-left', 'text-green-300')}

                  {/* Content */}
                  <div className="bg-blue-500/10 border border-blue-500/30 rounded px-2 py-1.5 flex items-center justify-center flex-1 mx-1">
                    <span className={`${valClass} text-blue-300`}>
                      {contentW}&times;{contentH}
                    </span>
                  </div>

                  {renderVal(p.right, 'padding-right', 'text-green-300')}
                </div>
                <div className="flex justify-center">
                  {renderVal(p.bottom, 'padding-bottom', 'text-green-300')}
                </div>
              </div>

              {renderVal(b.right, 'border-right-width', 'text-yellow-300')}
            </div>
            <div className="flex justify-center">
              {renderVal(b.bottom, 'border-bottom-width', 'text-yellow-300')}
            </div>
          </div>

          {renderVal(m.right, 'margin-right', 'text-orange-300')}
        </div>
        <div className="flex justify-center">
          {renderVal(m.bottom, 'margin-bottom', 'text-orange-300')}
        </div>
      </div>
    </div>
  );
}

// ── Add Property Inline ───────────────────────────────────────────────

function AddPropertyInline({
  onAdd,
}: {
  onAdd: (property: string, value: string) => void;
}) {
  const [phase, setPhase] = useState<'idle' | 'property' | 'value'>('idle');
  const [property, setProperty] = useState('');
  const [value, setValue] = useState('');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const propInputRef = useRef<HTMLInputElement>(null);
  const valInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (phase === 'property' && propInputRef.current) {
      propInputRef.current.focus();
    }
    if (phase === 'value' && valInputRef.current) {
      valInputRef.current.focus();
    }
  }, [phase]);

  const updateSuggestions = useCallback((input: string) => {
    if (!input) {
      setSuggestions([]);
      return;
    }
    const lower = input.toLowerCase();
    setSuggestions(
      COMMON_CSS_PROPERTIES.filter((p) => p.startsWith(lower)).slice(0, 5),
    );
  }, []);

  const commitProperty = () => {
    if (property.trim()) {
      setPhase('value');
      setSuggestions([]);
    }
  };

  const commitValue = () => {
    if (property.trim() && value.trim()) {
      onAdd(property.trim(), value.trim());
    }
    reset();
  };

  const reset = () => {
    setPhase('idle');
    setProperty('');
    setValue('');
    setSuggestions([]);
  };

  if (phase === 'idle') {
    return (
      <button
        type="button"
        onClick={() => setPhase('property')}
        className="flex items-center gap-1 text-[10px] text-[var(--text-subtle)] hover:text-[var(--primary)] mt-1 transition-colors"
      >
        <Plus size={10} />
        Add property
      </button>
    );
  }

  if (phase === 'property') {
    return (
      <div className="relative mt-1">
        <input
          ref={propInputRef}
          type="text"
          placeholder="property-name"
          value={property}
          onChange={(e) => {
            setProperty(e.target.value);
            updateSuggestions(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === 'Tab') {
              e.preventDefault();
              if (suggestions.length > 0 && !COMMON_CSS_PROPERTIES.includes(property)) {
                setProperty(suggestions[0]);
                setSuggestions([]);
              } else {
                commitProperty();
              }
            }
            if (e.key === 'Escape') reset();
          }}
          onBlur={() => {
            setTimeout(() => {
              if (phase === 'property' && !property.trim()) reset();
            }, 150);
          }}
          className="bg-transparent border-b border-[var(--primary)] text-[10px] font-mono text-[var(--text)] outline-none w-full"
        />
        {suggestions.length > 0 && (
          <div
            className="absolute top-full left-0 mt-0.5 rounded border z-10 max-h-[100px] overflow-y-auto"
            style={{
              background: 'var(--surface)',
              borderColor: 'var(--border)',
            }}
          >
            {suggestions.map((s) => (
              <button
                key={s}
                type="button"
                className="block w-full text-left px-2 py-0.5 text-[10px] font-mono text-[var(--text-muted)] hover:bg-[var(--primary)]/10"
                onMouseDown={(e) => {
                  e.preventDefault();
                  setProperty(s);
                  setSuggestions([]);
                  setPhase('value');
                }}
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  // phase === 'value' -- show a smart value editor if options exist, else plain input
  const options = CSS_VALUE_OPTIONS[property.trim()];

  return (
    <div className="mt-1 flex flex-col sm:flex-row items-start sm:items-center gap-1">
      <span className="text-[10px] font-mono text-[var(--text-subtle)] shrink-0">
        {property}:
      </span>
      {options ? (
        <div className="flex items-center gap-1 flex-1 min-w-0">
          <select
            value={value || ''}
            onChange={(e) => {
              const selected = e.target.value;
              if (selected === '__other__') {
                setValue('');
              } else {
                setValue(selected);
              }
            }}
            className="text-[10px] font-mono bg-[var(--surface)] text-[var(--text)] border border-[var(--border)] rounded-[var(--radius-small)] px-1 py-0.5 outline-none focus:border-[var(--primary)] appearance-none cursor-pointer min-h-[24px] sm:min-h-0 flex-1"
          >
            <option value="" disabled>
              Select...
            </option>
            {options.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
            <option value="__other__">Other...</option>
          </select>
          {value && value !== '__other__' && (
            <button
              type="button"
              onClick={() => commitValue()}
              className="text-[9px] text-[var(--primary)] hover:underline shrink-0"
            >
              Set
            </button>
          )}
          {(!value || value === '__other__') && (
            <input
              ref={valInputRef}
              type="text"
              placeholder="custom value"
              value={value === '__other__' ? '' : value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitValue();
                if (e.key === 'Escape') reset();
              }}
              onBlur={() => {
                if (value.trim()) commitValue();
                else reset();
              }}
              className="bg-transparent border-b border-[var(--primary)] text-[10px] font-mono text-[var(--text)] outline-none flex-1"
            />
          )}
        </div>
      ) : (
        <input
          ref={valInputRef}
          type="text"
          placeholder="value"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitValue();
            if (e.key === 'Escape') reset();
          }}
          onBlur={() => {
            if (value.trim()) commitValue();
            else reset();
          }}
          className="bg-transparent border-b border-[var(--primary)] text-[10px] font-mono text-[var(--text)] outline-none flex-1 w-full sm:w-auto"
        />
      )}
    </div>
  );
}

// ── Collapsible Style Group ───────────────────────────────────────────

function StyleGroupSection({
  group,
  styles,
  designId,
  onStyleUpdate,
}: {
  group: StyleGroup;
  styles: Record<string, string>;
  designId?: string;
  onStyleUpdate?: (designId: string, property: string, value: string) => void;
}) {
  const [open, setOpen] = useState(true);

  const entries = useMemo(() => {
    return group.keys
      .map((key) => {
        const kebab = toKebab(key);
        const camel = key.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        const value = styles[kebab] ?? styles[camel] ?? styles[key];
        return { key: kebab, value: value ?? '' };
      })
      .filter((e) => e.value !== '');
  }, [group.keys, styles]);

  const handleCommit = useCallback(
    (property: string, value: string) => {
      if (onStyleUpdate && designId) {
        onStyleUpdate(designId, property, value);
      }
    },
    [onStyleUpdate, designId],
  );

  const handleAdd = useCallback(
    (property: string, value: string) => {
      if (onStyleUpdate && designId) {
        onStyleUpdate(designId, property, value);
      }
    },
    [onStyleUpdate, designId],
  );

  if (entries.length === 0 && !onStyleUpdate) return null;

  return (
    <div>
      <button
        type="button"
        className="flex items-center gap-1 w-full text-left mb-1"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? (
          <ChevronDown size={12} className="text-[var(--text-subtle)]" />
        ) : (
          <ChevronRight size={12} className="text-[var(--text-subtle)]" />
        )}
        <span className="text-[11px] font-medium text-[var(--text-muted)] uppercase tracking-wider">
          {group.label}
        </span>
      </button>
      {open && (
        <div className="ml-4 space-y-0.5">
          {entries.map((e) => (
            <div
              key={e.key}
              className="flex flex-col sm:flex-row sm:items-center sm:justify-between py-0.5 gap-0.5 sm:gap-0"
            >
              <span className="text-[10px] font-mono text-[var(--text-subtle)]">
                {e.key}
              </span>
              {onStyleUpdate && designId ? (
                <SmartValueEditor
                  value={e.value}
                  property={e.key}
                  onCommit={handleCommit}
                />
              ) : (
                <span className="text-[10px] font-mono text-[var(--text-muted)] max-w-[120px] truncate text-right">
                  {e.value}
                </span>
              )}
            </div>
          ))}
          {onStyleUpdate && designId && (
            <AddPropertyInline onAdd={handleAdd} />
          )}
        </div>
      )}
    </div>
  );
}

// ── Editable Text Content ─────────────────────────────────────────────

function EditableTextContent({
  value,
  designId,
  onStyleUpdate,
}: {
  value: string;
  designId?: string;
  onStyleUpdate?: (designId: string, property: string, value: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(value);

  useEffect(() => {
    setEditValue(value);
  }, [value]);

  if (!editing) {
    return (
      <p
        onClick={() => designId && onStyleUpdate && setEditing(true)}
        className={`text-[10px] font-mono text-[var(--text-muted)] bg-[var(--surface)] rounded p-2 max-h-20 overflow-y-auto whitespace-pre-wrap break-words ${
          designId && onStyleUpdate
            ? 'cursor-text hover:border-[var(--primary)] border border-transparent'
            : ''
        }`}
      >
        {value.slice(0, 500)}
        {value.length > 500 && '...'}
      </p>
    );
  }

  return (
    <textarea
      value={editValue}
      onChange={(e) => setEditValue(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          if (designId && onStyleUpdate) onStyleUpdate(designId, 'textContent', editValue);
          setEditing(false);
        }
        if (e.key === 'Escape') {
          setEditValue(value);
          setEditing(false);
        }
      }}
      onBlur={() => {
        if (designId && onStyleUpdate && editValue !== value)
          onStyleUpdate(designId, 'textContent', editValue);
        setEditing(false);
      }}
      autoFocus
      rows={3}
      className="w-full text-[10px] font-mono text-[var(--text)] bg-[var(--surface)] rounded p-2 border border-[var(--primary)] outline-none resize-none"
    />
  );
}

// ── Editable Attribute Row ────────────────────────────────────────────

function EditableAttribute({
  name,
  value,
  designId,
  onUpdate,
  onRemove,
}: {
  name: string;
  value: string;
  designId?: string;
  onUpdate?: (designId: string, property: string, value: string) => void;
  onRemove?: (designId: string, property: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(value);

  useEffect(() => {
    setEditValue(value);
  }, [value]);

  const commit = () => {
    if (designId && onUpdate && editValue !== value) {
      onUpdate(designId, `attr:${name}`, editValue);
    }
    setEditing(false);
  };

  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between py-1 border-b border-[var(--border)]/50 group gap-0.5 sm:gap-0">
      <span className="text-[10px] font-mono text-[var(--text-subtle)] shrink-0">
        {name}
      </span>
      <div className="flex items-center gap-1 min-w-0">
        {editing ? (
          <input
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commit();
              if (e.key === 'Escape') {
                setEditValue(value);
                setEditing(false);
              }
            }}
            onBlur={commit}
            autoFocus
            className="text-[10px] font-mono text-[var(--text)] bg-transparent border-b border-[var(--primary)] outline-none max-w-[140px] text-right"
          />
        ) : (
          <span
            onClick={() => designId && onUpdate && setEditing(true)}
            className={`text-[10px] font-mono text-[var(--text-muted)] max-w-[140px] truncate text-right ${
              designId && onUpdate ? 'cursor-text hover:text-[var(--text)]' : ''
            }`}
            title={value}
          >
            {value || '(empty)'}
          </span>
        )}
        {designId && onRemove && (
          <button
            onClick={() => onRemove(designId, `attr:${name}`)}
            className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-red-500/10 text-[var(--text-subtle)] hover:text-red-400 transition-all shrink-0"
            title={`Remove ${name}`}
          >
            <X size={10} />
          </button>
        )}
      </div>
    </div>
  );
}

// ── Add Attribute Row ─────────────────────────────────────────────────

function AddAttributeRow({
  onAdd,
  onCancel,
}: {
  onAdd: (name: string, value: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState('');
  const [value, setValue] = useState('');
  const [step, setStep] = useState<'name' | 'value'>('name');
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  return (
    <div className="flex items-center gap-1 py-1 border-b border-[var(--border)]/50">
      {step === 'name' ? (
        <input
          ref={nameRef}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && name.trim()) setStep('value');
            if (e.key === 'Escape') onCancel();
          }}
          placeholder="attribute name"
          className="flex-1 text-[10px] font-mono text-[var(--text)] bg-transparent border-b border-[var(--primary)] outline-none placeholder:text-[var(--text-subtle)]"
        />
      ) : (
        <>
          <span className="text-[10px] font-mono text-[var(--text-subtle)] shrink-0">
            {name}
          </span>
          <span className="text-[10px] text-[var(--text-subtle)]">=</span>
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onAdd(name.trim(), value);
              if (e.key === 'Escape') onCancel();
            }}
            onBlur={() => {
              if (value) onAdd(name.trim(), value);
              else onCancel();
            }}
            autoFocus
            placeholder="value"
            className="flex-1 text-[10px] font-mono text-[var(--text)] bg-transparent border-b border-[var(--primary)] outline-none placeholder:text-[var(--text-subtle)]"
          />
        </>
      )}
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────

export default function InspectorTab({
  selectedElement,
  cursorElement,
  onStyleUpdate,
  onStyleRemove,
  onSwitchToVisual,
}: InspectorTabProps) {
  const [addingAttribute, setAddingAttribute] = useState(false);

  // Merged tag name -- prefer preview selection
  const tagName = selectedElement?.tagName ?? cursorElement?.tagName ?? null;

  // designId for style/attribute updates
  const designId = selectedElement?.designId ?? selectedElement?.selector ?? '';

  // ── Merged data (computed before hooks that depend on them) ────────
  const computedStyles = selectedElement?.computedStyles ?? {};
  const displayValue =
    computedStyles['display'] ?? computedStyles.display ?? '';

  // Attributes: prefer selectedElement.attributes, fall back to cursorElement.props
  const attributes: { key: string; value: string }[] = useMemo(() => {
    if (selectedElement) {
      return Object.entries(selectedElement.attributes)
        .filter(([k]) => k !== 'class' && k !== 'id')
        .map(([k, v]) => ({ key: k, value: v }));
    }
    if (cursorElement) {
      return cursorElement.props
        .filter((p) => p.name !== 'className' && p.name !== 'id')
        .map((p) => ({ key: p.name, value: p.value }));
    }
    return [];
  }, [selectedElement, cursorElement]);

  // Filtered style groups (hide flex/grid group when irrelevant)
  const visibleGroups = useMemo(() => {
    return STYLE_GROUPS.filter((g) => {
      if (!g.displayFilter) return true;
      return g.displayFilter.includes(displayValue);
    });
  }, [displayValue]);

  // ── Box model commit handler ───────────────────────────────────────
  const handleBoxModelCommit = useCallback(
    (property: string, value: string) => {
      if (onStyleUpdate && designId) {
        onStyleUpdate(designId, property, value);
      }
    },
    [onStyleUpdate, designId],
  );

  // ── Empty state ────────────────────────────────────────────────────
  if (!selectedElement && !cursorElement) {
    return (
      <div className="h-full flex flex-col items-center justify-center px-6 py-12">
        <Info size={28} className="text-[var(--text-subtle)] mb-3" />
        <p className="text-xs text-[var(--text-subtle)] text-center leading-relaxed">
          Select an element in the preview or place your cursor on a JSX element
          to inspect its properties.
        </p>
      </div>
    );
  }

  // ── Remaining merged data ──────────────────────────────────────────
  const id = selectedElement?.id || '';
  const classList = selectedElement?.classList ?? [];
  const parentPath = selectedElement?.parentPath ?? [];
  const reactComponent = selectedElement?.reactComponent ?? null;
  const framework = selectedElement?.framework ?? null;
  const selector = selectedElement?.selector ?? '';
  const textContent = selectedElement?.textContent ?? '';

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4">
        {/* ── A. Element Identity ──────────────────────────────────── */}
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="inline-flex items-center px-2 py-0.5 rounded bg-[var(--primary)]/10 text-[var(--primary)] text-xs font-mono font-medium">
              &lt;{tagName}&gt;
            </span>
            {id && (
              <span className="text-[10px] font-mono text-[var(--text-subtle)]">
                #{id}
              </span>
            )}
            {framework && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 font-medium">
                {framework}
              </span>
            )}
          </div>

          {/* CSS selector */}
          {selector && (
            <div className="mt-1 text-[9px] font-mono text-[var(--text-subtle)] truncate">
              {selector}
            </div>
          )}

          {/* Parent breadcrumb */}
          {parentPath.length > 0 && (
            <div className="mt-2 flex items-center gap-1 overflow-x-auto scrollbar-none">
              {parentPath.map((segment, i) => (
                <React.Fragment key={i}>
                  {i > 0 && (
                    <ChevronRight
                      size={10}
                      className="shrink-0 text-[var(--text-subtle)]"
                    />
                  )}
                  <span className="text-[10px] text-[var(--text-subtle)] font-mono whitespace-nowrap">
                    {segment}
                  </span>
                </React.Fragment>
              ))}
            </div>
          )}
        </div>

        <div className="h-px bg-[var(--border)]" />

        {/* ── A2. React Component ─────────────────────────────────── */}
        {reactComponent && (
          <>
            <div>
              <SectionHeader>React Component</SectionHeader>
              <div className="space-y-1.5">
                <span className="text-[11px] font-mono font-medium text-purple-400">
                  &lt;{reactComponent.name}&gt;
                </span>
                {reactComponent.sourceFile && (
                  <div className="text-[9px] font-mono text-[var(--text-subtle)] truncate">
                    {reactComponent.sourceFile}
                    {reactComponent.lineNumber
                      ? `:${reactComponent.lineNumber}`
                      : ''}
                  </div>
                )}
                {reactComponent.props &&
                  Object.keys(reactComponent.props).length > 0 && (
                    <div className="mt-1 space-y-0.5">
                      {Object.entries(reactComponent.props).map(([k, v]) => (
                        <div
                          key={k}
                          className="flex flex-col sm:flex-row sm:items-center sm:justify-between py-0.5 gap-0.5 sm:gap-0"
                        >
                          <span className="text-[10px] font-mono text-purple-400/70">
                            {k}
                          </span>
                          <span className="text-[10px] font-mono text-[var(--text-muted)] max-w-[120px] truncate text-right">
                            {String(v)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
              </div>
            </div>
            <div className="h-px bg-[var(--border)]" />
          </>
        )}

        {/* ── B. Classes ──────────────────────────────────────────── */}
        {classList.length > 0 && (
          <div>
            <SectionHeader
              trailing={<CountBadge count={classList.length} />}
            >
              Classes
            </SectionHeader>
            <div className="flex flex-wrap gap-1">
              {classList.map((cls, i) => (
                <span
                  key={`${cls}-${i}`}
                  className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--surface)] border border-[var(--border)] text-[var(--text-muted)]"
                >
                  {cls}
                </span>
              ))}
            </div>
            <button
              type="button"
              onClick={onSwitchToVisual}
              className="mt-2 inline-flex items-center gap-1 text-[10px] text-[var(--primary)] hover:underline"
            >
              Edit in Visual
              <ExternalLink size={10} />
            </button>
          </div>
        )}

        {classList.length > 0 && <div className="h-px bg-[var(--border)]" />}

        {/* ── B2. Text Content (editable) ────────────────────────── */}
        {textContent && (
          <>
            <div>
              <SectionHeader>Text Content</SectionHeader>
              <EditableTextContent
                value={textContent}
                designId={selectedElement?.designId}
                onStyleUpdate={onStyleUpdate}
              />
            </div>
            <div className="h-px bg-[var(--border)]" />
          </>
        )}

        {/* ── C. Attributes (editable + add/remove) ──────────────── */}
        <div>
          <SectionHeader
            trailing={
              selectedElement?.designId && (
                <button
                  type="button"
                  onClick={() => setAddingAttribute(true)}
                  className="p-0.5 rounded hover:bg-[var(--surface-hover)] text-[var(--text-subtle)] hover:text-[var(--text-muted)] transition-colors"
                  title="Add attribute"
                >
                  <Plus size={12} />
                </button>
              )
            }
          >
            Attributes
          </SectionHeader>
          {attributes.length > 0 && (
            <div>
              {attributes.map((attr) => (
                <EditableAttribute
                  key={attr.key}
                  name={attr.key}
                  value={attr.value}
                  designId={selectedElement?.designId}
                  onUpdate={onStyleUpdate}
                  onRemove={onStyleRemove}
                />
              ))}
            </div>
          )}
          {addingAttribute && (
            <AddAttributeRow
              onAdd={(name, value) => {
                if (selectedElement?.designId && onStyleUpdate) {
                  onStyleUpdate(selectedElement.designId, `attr:${name}`, value);
                }
                setAddingAttribute(false);
              }}
              onCancel={() => setAddingAttribute(false)}
            />
          )}
          {attributes.length === 0 && !addingAttribute && (
            <p className="text-[10px] text-[var(--text-subtle)] italic">
              No attributes
            </p>
          )}
        </div>

        <div className="h-px bg-[var(--border)]" />

        {/* ── D. Box Model ────────────────────────────────────────── */}
        {selectedElement && (
          <>
            <div>
              <SectionHeader>Box Model</SectionHeader>
              <BoxModelDiagram
                styles={
                  selectedElement.boxModel
                    ? {
                        'margin-top': selectedElement.boxModel.margin.top,
                        'margin-right': selectedElement.boxModel.margin.right,
                        'margin-bottom': selectedElement.boxModel.margin.bottom,
                        'margin-left': selectedElement.boxModel.margin.left,
                        'padding-top': selectedElement.boxModel.padding.top,
                        'padding-right': selectedElement.boxModel.padding.right,
                        'padding-bottom': selectedElement.boxModel.padding.bottom,
                        'padding-left': selectedElement.boxModel.padding.left,
                        'border-top-width': selectedElement.boxModel.border.top,
                        'border-right-width': selectedElement.boxModel.border.right,
                        'border-bottom-width': selectedElement.boxModel.border.bottom,
                        'border-left-width': selectedElement.boxModel.border.left,
                        width: selectedElement.boxModel.width,
                        height: selectedElement.boxModel.height,
                      }
                    : computedStyles
                }
                onCommit={onStyleUpdate ? handleBoxModelCommit : undefined}
              />
            </div>
            <div className="h-px bg-[var(--border)]" />
          </>
        )}

        {/* ── E. Computed Styles ──────────────────────────────────── */}
        {selectedElement && Object.keys(computedStyles).length > 0 && (
          <div>
            <SectionHeader>Styles</SectionHeader>
            <div className="space-y-2">
              {visibleGroups.map((group) => (
                <StyleGroupSection
                  key={group.label}
                  group={group}
                  styles={computedStyles}
                  designId={designId}
                  onStyleUpdate={onStyleUpdate}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
