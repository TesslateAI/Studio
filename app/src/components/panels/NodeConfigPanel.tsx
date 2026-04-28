import { useCallback, useMemo, useState } from 'react';
import { Info, Warning } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import { nodeConfigApi } from '../../lib/api';
import type {
  FormSchema,
  NodeConfigInitialValues,
  NodeConfigMode,
  SubmittedFieldValue,
} from '../../types/nodeConfig';
import {
  buildInitialState,
  buildSubmitValues as buildSubmitValuesShared,
  renderField,
  validateFieldState,
  type FieldState,
  type FieldStateMap,
} from './nodeConfigForm';

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
  const [fieldState, setFieldState] = useState<FieldStateMap>(() =>
    buildInitialState(schema.fields, initialValues)
  );

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const isAgentMode = Boolean(agentInputId);

  const updateField = useCallback((key: string, patch: Partial<FieldState>) => {
    setFieldState((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }));
  }, []);

  const validate = useCallback(
    () => validateFieldState(schema.fields, fieldState),
    [fieldState, schema.fields]
  );

  const buildSubmitValues = useCallback(
    () => buildSubmitValuesShared(schema.fields, fieldState),
    [fieldState, schema.fields]
  );

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

export type { SubmittedFieldValue };
