/**
 * Shared form helpers for node-config UIs.
 *
 * Extracted from `NodeConfigPanel.tsx` so the persistent Config tab's
 * `ConfigCard` component can render the same field/secret semantics
 * (tri-state secret editing, validation, submit-value shaping) without
 * duplicating the logic. `NodeConfigPanel` and `ConfigCard` both import
 * from here.
 */

import { Eye, EyeSlash } from '@phosphor-icons/react';
import type {
  FieldSchema,
  NodeConfigInitialValues,
  SubmittedValues,
} from '../../types/nodeConfig';
import { SECRET_SET_SENTINEL } from '../../types/nodeConfig';

export type SecretEditState = 'keep' | 'rotate' | 'clear';

export interface FieldState {
  value: string;
  /** Only meaningful for `is_secret` fields. */
  secretMode: SecretEditState;
  showSecret: boolean;
}

export type FieldStateMap = Record<string, FieldState>;

/** Build the initial state for a single field given the masked initial values
 * from the backend (secrets show as `__SET__` if already stored). */
export function initialFieldState(
  field: FieldSchema,
  initialValues: NodeConfigInitialValues
): FieldState {
  const raw = initialValues[field.key];
  if (field.is_secret) {
    const hasExisting = raw === SECRET_SET_SENTINEL;
    return {
      value: '',
      secretMode: hasExisting ? 'keep' : 'rotate',
      showSecret: false,
    };
  }
  return {
    value: typeof raw === 'string' ? raw : raw != null ? String(raw) : '',
    secretMode: 'keep',
    showSecret: false,
  };
}

/** Build a fresh `FieldStateMap` from a schema + initial values. */
export function buildInitialState(
  fields: FieldSchema[],
  initialValues: NodeConfigInitialValues
): FieldStateMap {
  const out: FieldStateMap = {};
  for (const f of fields) out[f.key] = initialFieldState(f, initialValues);
  return out;
}

/** Validate the current state against the schema. Returns a map of
 * `key → error message` for any failing field. Empty map = valid. */
export function validateFieldState(
  fields: FieldSchema[],
  state: FieldStateMap
): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const f of fields) {
    const st = state[f.key];
    if (!st) continue;

    if (f.required) {
      if (f.is_secret) {
        if (st.secretMode === 'clear') {
          errors[f.key] = `${f.label} is required`;
        } else if (st.secretMode === 'rotate' && st.value.trim() === '') {
          errors[f.key] = `${f.label} is required`;
        }
      } else if (st.value.trim() === '') {
        errors[f.key] = `${f.label} is required`;
      }
    }

    if (f.type === 'url' && st.value.trim() !== '') {
      try {
        new URL(st.value.trim());
      } catch {
        errors[f.key] = `${f.label} must be a valid URL`;
      }
    }
    if (
      f.type === 'number' &&
      st.value.trim() !== '' &&
      Number.isNaN(Number(st.value))
    ) {
      errors[f.key] = `${f.label} must be a number`;
    }
  }
  return errors;
}

/** Convert state → server-shaped submit values, applying secret tri-state
 * semantics (keep omits, rotate sends new string, clear sends `{clear: true}`). */
export function buildSubmitValues(
  fields: FieldSchema[],
  state: FieldStateMap
): SubmittedValues {
  const out: SubmittedValues = {};
  for (const f of fields) {
    const st = state[f.key];
    if (!st) continue;

    if (f.is_secret) {
      if (st.secretMode === 'keep') continue;
      if (st.secretMode === 'clear') {
        out[f.key] = { clear: true };
        continue;
      }
      const trimmed = st.value.trim();
      if (trimmed === '') continue; // optional secret left blank
      out[f.key] = trimmed;
      continue;
    }

    const trimmed = st.value.trim();
    if (f.type === 'number') {
      if (trimmed === '') {
        out[f.key] = null;
      } else {
        const n = Number(trimmed);
        out[f.key] = Number.isNaN(n) ? trimmed : n;
      }
    } else {
      out[f.key] = trimmed;
    }
  }
  return out;
}

/** Render an input for one field. Caller passes the field state and an
 * `onChange(patch)` to merge changes back into its state map. */
export function renderField(
  field: FieldSchema,
  state: FieldState,
  onChange: (patch: Partial<FieldState>) => void
) {
  const baseInputClass =
    'w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]';

  if (field.is_secret) {
    if (state.secretMode === 'keep') {
      return (
        <div className="flex items-center gap-2">
          <span className="flex-1 px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text-muted)] font-mono select-none">
            ••••••••
          </span>
          <button
            type="button"
            onClick={() => onChange({ secretMode: 'rotate', value: '' })}
            className="btn"
          >
            Rotate
          </button>
          <button
            type="button"
            onClick={() => onChange({ secretMode: 'clear' })}
            className="btn"
          >
            Clear
          </button>
        </div>
      );
    }
    if (state.secretMode === 'clear') {
      return (
        <div className="flex items-center gap-2">
          <span className="flex-1 px-2 py-1.5 bg-red-500/10 border border-red-500/30 rounded-[var(--radius-small)] text-xs text-red-300 font-mono">
            Will be cleared on submit
          </span>
          <button
            type="button"
            onClick={() => onChange({ secretMode: 'keep' })}
            className="btn"
          >
            Keep
          </button>
        </div>
      );
    }
    return (
      <div className="flex items-center gap-2">
        <input
          id={`nc-${field.key}`}
          type={state.showSecret ? 'text' : 'password'}
          value={state.value}
          autoComplete="off"
          placeholder={field.placeholder}
          onChange={(e) => onChange({ value: e.target.value })}
          className={baseInputClass}
        />
        <button
          type="button"
          onClick={() => onChange({ showSecret: !state.showSecret })}
          className="btn"
          aria-label={state.showSecret ? 'Hide value' : 'Show value'}
          title={state.showSecret ? 'Hide value' : 'Show value'}
        >
          {state.showSecret ? (
            <EyeSlash size={12} weight="bold" />
          ) : (
            <Eye size={12} weight="bold" />
          )}
        </button>
      </div>
    );
  }

  if (field.type === 'textarea') {
    return (
      <textarea
        id={`nc-${field.key}`}
        value={state.value}
        placeholder={field.placeholder}
        onChange={(e) => onChange({ value: e.target.value })}
        rows={3}
        className={`${baseInputClass} font-mono`}
      />
    );
  }

  if (field.type === 'select' && field.options && field.options.length > 0) {
    return (
      <select
        id={`nc-${field.key}`}
        value={state.value}
        onChange={(e) => onChange({ value: e.target.value })}
        className={baseInputClass}
      >
        {!field.required && <option value="">—</option>}
        {field.options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    );
  }

  const inputType: string =
    field.type === 'url' ? 'url' : field.type === 'number' ? 'number' : 'text';
  return (
    <input
      id={`nc-${field.key}`}
      type={inputType}
      value={state.value}
      placeholder={field.placeholder}
      onChange={(e) => onChange({ value: e.target.value })}
      className={baseInputClass}
    />
  );
}
