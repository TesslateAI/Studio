import { useMemo, useState } from 'react';

interface Props {
  /** JSON Schema object describing the action's input shape. */
  schema: Record<string, unknown> | null | undefined;
  /** Current value of the input — typically the action's config.input. */
  value: Record<string, unknown> | string;
  /** Called with the new structured value (object) OR raw text when in raw mode. */
  onChange: (next: Record<string, unknown> | string) => void;
}

interface PropertyDef {
  name: string;
  type: 'string' | 'integer' | 'number' | 'boolean' | 'array' | 'object' | 'unknown';
  description?: string;
  enumValues?: string[];
  required: boolean;
  default?: unknown;
  itemsType?: string;
}

/**
 * Tiny JSON Schema -> form renderer covering the cases real app manifests
 * use today (objects with primitive properties, optional enums, optional
 * defaults). Anything fancier (allOf / oneOf / nested objects beyond one
 * level / $ref) drops to a raw-JSON textarea fallback.
 *
 * The form keeps the user's value as a structured object whenever it can
 * — the parent receives the object directly via onChange. If the user
 * opens raw mode, onChange receives a string (validated by the parent
 * before submit).
 */
export function JsonSchemaForm({ schema, value, onChange }: Props) {
  const [rawOpen, setRawOpen] = useState(false);
  const [rawText, setRawText] = useState<string>(() =>
    typeof value === 'string' ? value : JSON.stringify(value ?? {}, null, 2)
  );

  const parsedSchema = useMemo(() => parseSchema(schema), [schema]);
  const valueObject = useMemo<Record<string, unknown>>(() => {
    if (typeof value === 'string') {
      try {
        const parsed = JSON.parse(value || '{}');
        return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
          ? (parsed as Record<string, unknown>)
          : {};
      } catch {
        return {};
      }
    }
    return value ?? {};
  }, [value]);

  // No schema or schema we can't introspect → show the raw textarea by
  // default. The user still gets a usable form, just unstructured.
  const structuredAvailable = parsedSchema !== null && parsedSchema.length > 0;
  const showRaw = !structuredAvailable || rawOpen;

  const setField = (name: string, raw: unknown) => {
    const next = { ...valueObject };
    if (raw === undefined || raw === '' || raw === null) {
      delete next[name];
    } else {
      next[name] = raw;
    }
    onChange(next);
  };

  return (
    <div className="space-y-3">
      {structuredAvailable && !showRaw && (
        <div className="space-y-3">
          {parsedSchema.map((prop) => (
            <FieldRow
              key={prop.name}
              prop={prop}
              value={valueObject[prop.name]}
              onChange={(next) => setField(prop.name, next)}
            />
          ))}
        </div>
      )}

      {showRaw && (
        <label className="block">
          <span className="block text-xs font-medium text-[var(--text)] mb-1">
            Action input (JSON)
          </span>
          <textarea
            rows={5}
            value={rawText}
            onChange={(e) => {
              setRawText(e.target.value);
              try {
                const parsed = JSON.parse(e.target.value);
                onChange(parsed);
              } catch {
                // Keep typing — parent validates on submit.
                onChange(e.target.value);
              }
            }}
            placeholder='{"key": "value"}'
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
          />
          {!structuredAvailable && (
            <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
              This action doesn't expose an input schema, so we can't generate a form. Provide the
              input as JSON.
            </span>
          )}
        </label>
      )}

      {structuredAvailable && (
        <button
          type="button"
          onClick={() => {
            // When toggling into raw mode, snapshot the current structured
            // value into the textarea. When toggling back, the textarea's
            // last successful parse remains in valueObject already.
            if (!rawOpen) setRawText(JSON.stringify(valueObject, null, 2));
            setRawOpen((v) => !v);
          }}
          className="text-[10px] text-[var(--text-subtle)] hover:text-[var(--text)] underline"
        >
          {rawOpen ? 'Use the form' : 'Edit raw JSON instead'}
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Schema parsing — best-effort
// ---------------------------------------------------------------------------

function parseSchema(schema: Record<string, unknown> | null | undefined): PropertyDef[] | null {
  if (!schema || typeof schema !== 'object') return null;
  if ((schema as { type?: unknown }).type !== 'object') return null;
  const props = (schema as { properties?: unknown }).properties;
  if (!props || typeof props !== 'object') return null;
  const required = Array.isArray((schema as { required?: unknown }).required)
    ? ((schema as { required?: unknown }).required as unknown[]).map(String)
    : [];

  const out: PropertyDef[] = [];
  for (const [name, def] of Object.entries(props)) {
    if (!def || typeof def !== 'object') continue;
    const d = def as Record<string, unknown>;
    const rawType = d.type;
    let type: PropertyDef['type'] = 'unknown';
    if (typeof rawType === 'string') {
      if (
        rawType === 'string' ||
        rawType === 'integer' ||
        rawType === 'number' ||
        rawType === 'boolean' ||
        rawType === 'array' ||
        rawType === 'object'
      ) {
        type = rawType;
      }
    }
    out.push({
      name,
      type,
      description: typeof d.description === 'string' ? d.description : undefined,
      enumValues: Array.isArray(d.enum) ? d.enum.map(String) : undefined,
      required: required.includes(name),
      default: d.default,
      itemsType:
        d.items &&
        typeof d.items === 'object' &&
        typeof (d.items as { type?: unknown }).type === 'string'
          ? String((d.items as { type: string }).type)
          : undefined,
    });
  }
  return out;
}

// ---------------------------------------------------------------------------
// Field row — one schema property
// ---------------------------------------------------------------------------

function FieldRow({
  prop,
  value,
  onChange,
}: {
  prop: PropertyDef;
  value: unknown;
  onChange: (next: unknown) => void;
}) {
  const label = (
    <span className="block text-xs font-medium text-[var(--text)] mb-1">
      {prop.name}
      {prop.required && <span className="text-[var(--status-error)] ml-0.5">*</span>}
    </span>
  );

  if (prop.enumValues && prop.enumValues.length > 0) {
    return (
      <label className="block">
        {label}
        <select
          value={value === undefined || value === null ? '' : String(value)}
          onChange={(e) => onChange(e.target.value || undefined)}
          className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
        >
          <option value="">— Pick a value —</option>
          {prop.enumValues.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
        {prop.description && <Help text={prop.description} />}
      </label>
    );
  }

  switch (prop.type) {
    case 'boolean':
      return (
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={value === true}
            onChange={(e) => onChange(e.target.checked)}
          />
          <span className="text-xs text-[var(--text)]">
            {prop.name}
            {prop.required && <span className="text-[var(--status-error)] ml-0.5">*</span>}
          </span>
          {prop.description && (
            <span className="text-[10px] text-[var(--text-subtle)] ml-2">{prop.description}</span>
          )}
        </label>
      );

    case 'integer':
    case 'number':
      return (
        <label className="block">
          {label}
          <input
            type="number"
            step={prop.type === 'integer' ? 1 : 'any'}
            value={value === undefined || value === null ? '' : String(value)}
            onChange={(e) => {
              const raw = e.target.value;
              if (raw === '') return onChange(undefined);
              const n = prop.type === 'integer' ? parseInt(raw, 10) : parseFloat(raw);
              onChange(Number.isFinite(n) ? n : undefined);
            }}
            placeholder={
              prop.default !== undefined ? `default: ${String(prop.default)}` : undefined
            }
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
          />
          {prop.description && <Help text={prop.description} />}
        </label>
      );

    case 'array':
      return (
        <label className="block">
          {label}
          <input
            type="text"
            value={Array.isArray(value) ? value.map(String).join(', ') : ''}
            onChange={(e) => {
              const items = e.target.value
                .split(',')
                .map((s) => s.trim())
                .filter((s) => s.length > 0);
              if (prop.itemsType === 'integer' || prop.itemsType === 'number') {
                onChange(
                  items
                    .map((s) => (prop.itemsType === 'integer' ? parseInt(s, 10) : parseFloat(s)))
                    .filter((n) => Number.isFinite(n))
                );
              } else {
                onChange(items);
              }
            }}
            placeholder="comma-separated values"
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
          />
          {prop.description && <Help text={prop.description} />}
        </label>
      );

    case 'object':
    case 'unknown':
      return (
        <label className="block">
          {label}
          <textarea
            rows={3}
            value={
              value === undefined || value === null
                ? ''
                : typeof value === 'string'
                  ? value
                  : JSON.stringify(value, null, 2)
            }
            onChange={(e) => {
              const raw = e.target.value;
              if (!raw.trim()) return onChange(undefined);
              try {
                onChange(JSON.parse(raw));
              } catch {
                onChange(raw);
              }
            }}
            placeholder='{"…": "…"}'
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
          />
          {prop.description && <Help text={prop.description} />}
        </label>
      );

    case 'string':
    default:
      return (
        <label className="block">
          {label}
          <input
            type="text"
            value={value === undefined || value === null ? '' : String(value)}
            onChange={(e) => onChange(e.target.value || undefined)}
            placeholder={
              prop.default !== undefined ? `default: ${String(prop.default)}` : undefined
            }
            className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
          />
          {prop.description && <Help text={prop.description} />}
        </label>
      );
  }
}

function Help({ text }: { text: string }) {
  return <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">{text}</span>;
}
