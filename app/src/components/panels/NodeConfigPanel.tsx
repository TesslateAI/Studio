import { useCallback, useMemo, useState } from 'react';
import { Eye, EyeSlash, Info, Warning } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import { nodeConfigApi } from '../../lib/api';
import type {
  FieldSchema,
  FormSchema,
  NodeConfigInitialValues,
  NodeConfigMode,
  SubmittedFieldValue,
  SubmittedValues,
} from '../../types/nodeConfig';
import { SECRET_SET_SENTINEL } from '../../types/nodeConfig';

export interface NodeConfigPanelProps {
  projectId: string;
  containerId: string;
  containerName: string;
  schema: FormSchema;
  initialValues: NodeConfigInitialValues;
  mode: NodeConfigMode;
  preset: string;
  /** Present → agent is paused waiting on `submit`. Absent → direct edit. */
  agentInputId?: string;
  onClose: () => void;
}

type SecretEditState = 'keep' | 'rotate' | 'clear';

interface FieldState {
  value: string;
  secretMode: SecretEditState; // only meaningful for is_secret fields
  showSecret: boolean;
}

function initialFieldState(
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

export function NodeConfigPanel({
  projectId,
  containerId,
  containerName,
  schema,
  initialValues,
  mode,
  preset,
  agentInputId,
  onClose,
}: NodeConfigPanelProps) {
  const [fieldState, setFieldState] = useState<Record<string, FieldState>>(() => {
    const initial: Record<string, FieldState> = {};
    for (const f of schema.fields) {
      initial[f.key] = initialFieldState(f, initialValues);
    }
    return initial;
  });

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const isAgentMode = Boolean(agentInputId);

  const updateField = useCallback((key: string, patch: Partial<FieldState>) => {
    setFieldState((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }));
  }, []);

  const validate = useCallback((): Record<string, string> => {
    const next: Record<string, string> = {};
    for (const f of schema.fields) {
      const st = fieldState[f.key];
      if (!st) continue;
      if (!f.required) continue;

      if (f.is_secret) {
        // Required secret: OK if keeping an existing one, or providing a new one.
        if (st.secretMode === 'clear') {
          next[f.key] = `${f.label} is required`;
        } else if (st.secretMode === 'rotate' && st.value.trim() === '') {
          next[f.key] = `${f.label} is required`;
        }
      } else if (st.value.trim() === '') {
        next[f.key] = `${f.label} is required`;
      }

      if (f.type === 'url' && st.value.trim() !== '') {
        try {
          new URL(st.value.trim());
        } catch {
          next[f.key] = `${f.label} must be a valid URL`;
        }
      }
      if (f.type === 'number' && st.value.trim() !== '' && Number.isNaN(Number(st.value))) {
        next[f.key] = `${f.label} must be a number`;
      }
    }
    return next;
  }, [fieldState, schema.fields]);

  const buildSubmitValues = useCallback((): SubmittedValues => {
    const out: SubmittedValues = {};
    for (const f of schema.fields) {
      const st = fieldState[f.key];
      if (!st) continue;

      if (f.is_secret) {
        if (st.secretMode === 'keep') {
          // Omit: server preserves existing value.
          continue;
        }
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
  }, [fieldState, schema.fields]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const validation = validate();
      setErrors(validation);
      if (Object.keys(validation).length > 0) return;

      const values = buildSubmitValues();
      setIsSubmitting(true);
      try {
        if (agentInputId) {
          await nodeConfigApi.submit(agentInputId, values);
          toast.success(`Sent config for ${containerName}`);
        } else {
          await nodeConfigApi.patchContainerConfig(projectId, containerId, {
            values,
            preset,
            mode,
          });
          toast.success(`Updated ${containerName}`);
        }
        onClose();
      } catch (err) {
        const message =
          err instanceof Error ? err.message : 'Failed to save configuration';
        toast.error(message);
      } finally {
        setIsSubmitting(false);
      }
    },
    [
      agentInputId,
      buildSubmitValues,
      containerId,
      containerName,
      mode,
      onClose,
      preset,
      projectId,
      validate,
    ]
  );

  const handleCancel = useCallback(async () => {
    if (!agentInputId) {
      onClose();
      return;
    }
    setIsCancelling(true);
    try {
      await nodeConfigApi.cancel(agentInputId);
      toast('Configuration cancelled', { icon: 'ℹ️' });
      onClose();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to cancel';
      toast.error(message);
    } finally {
      setIsCancelling(false);
    }
  }, [agentInputId, onClose]);

  const hasFields = schema.fields.length > 0;

  const submitLabel = useMemo(() => {
    if (isSubmitting) return 'Saving…';
    if (isAgentMode) return mode === 'create' ? 'Provide to agent' : 'Update & resume';
    return 'Save';
  }, [isAgentMode, isSubmitting, mode]);

  return (
    <div className="w-full h-full flex flex-col overflow-hidden bg-[var(--bg)]">
      {/* Header */}
      <div className="flex items-center justify-between h-10 px-4 border-b border-[var(--border)] bg-[var(--surface)] flex-shrink-0">
        <div className="min-w-0">
          <h2 className="text-[12px] font-medium text-[var(--text)] truncate">
            Configure {containerName}
          </h2>
          <p className="text-[10px] text-[var(--text-muted)] truncate">
            {preset} · {mode}
          </p>
        </div>
      </div>

      {/* Agent waiting banner */}
      {isAgentMode && (
        <div className="flex items-start gap-2 px-4 py-2 border-b border-[var(--border)] bg-[var(--primary)]/5 flex-shrink-0">
          <Info
            size={14}
            weight="bold"
            className="text-[var(--primary)] mt-[1px] flex-shrink-0"
          />
          <p className="text-[11px] text-[var(--text)]/80">
            Agent is waiting for these details. Submit to continue, or cancel to let
            the agent know you backed out.
          </p>
        </div>
      )}

      {/* Form */}
      <form
        onSubmit={handleSubmit}
        className="flex-1 flex flex-col overflow-hidden"
      >
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {!hasFields && (
            <p className="text-xs text-[var(--text-muted)]">
              This node has no configurable fields.
            </p>
          )}

          {schema.fields.map((f) => {
            const st = fieldState[f.key];
            if (!st) return null;
            const errorMsg = errors[f.key];
            return (
              <div key={f.key} className="space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <label
                    htmlFor={`nc-${f.key}`}
                    className="text-[11px] font-medium text-[var(--text)]"
                  >
                    {f.label}
                    {f.required && (
                      <span className="text-red-400 ml-0.5" aria-hidden>
                        *
                      </span>
                    )}
                  </label>
                  {f.is_secret && (
                    <span className="text-[9px] uppercase tracking-wide text-[var(--text-muted)]">
                      Secret
                    </span>
                  )}
                </div>

                {renderField(f, st, (patch) => updateField(f.key, patch))}

                {f.help && (
                  <p className="text-[10px] text-[var(--text-muted)]">{f.help}</p>
                )}

                {errorMsg && (
                  <p className="text-[10px] text-red-400 flex items-center gap-1">
                    <Warning size={10} weight="bold" /> {errorMsg}
                  </p>
                )}
              </div>
            );
          })}
        </div>

        {/* Footer actions */}
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-[var(--border)] bg-[var(--surface)] flex-shrink-0">
          <button
            type="button"
            onClick={handleCancel}
            disabled={isCancelling || isSubmitting}
            className="btn"
          >
            {isCancelling ? 'Cancelling…' : isAgentMode ? 'Cancel' : 'Close'}
          </button>
          <button
            type="submit"
            disabled={isSubmitting || isCancelling || !hasFields}
            className="btn btn-filled"
          >
            {submitLabel}
          </button>
        </div>
      </form>
    </div>
  );
}

function renderField(
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
    // rotate / new value
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

export type { SubmittedFieldValue };
