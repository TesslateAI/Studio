/**
 * One card in the persistent Config tab. Three states:
 *
 *  - **collapsed** (default): service name + preset + key-count summary.
 *  - **direct edit**: form fields, Save → PATCH `/containers/{cid}/config`.
 *  - **agent-waiting**: agent is paused on this container; submit resumes it
 *    via `/chat/node-config/{input_id}/submit`. Shown when `pendingInputId`
 *    is set on the row.
 *
 * Reuses the shared form helpers from `nodeConfigForm.tsx` so the
 * tri-state secret editor + validation match `NodeConfigPanel` exactly.
 *
 * "+ Add field" affordance lets the user attach custom env keys to any
 * card (preset or empty internal container) without going through the
 * agent. The new field is sent as an override on Save; the backend stores
 * the value and the next GET surfaces it via the schema-merge step in
 * ``routers/node_config.py``.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { CaretDown, CaretRight, Info, Plug, Cube, Plus, Warning, X } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import { nodeConfigApi } from '../../lib/api';
import type {
  FieldSchema,
  NodeConfigFieldType,
  NodeConfigInitialValues,
  ProjectConfigService,
} from '../../types/nodeConfig';
import {
  buildInitialState,
  buildSubmitValues,
  initialFieldState,
  renderField,
  validateFieldState,
  type FieldState,
  type FieldStateMap,
} from './nodeConfigForm';

export interface ConfigCardProps {
  projectId: string;
  service: ProjectConfigService;
  /** Called after a successful save so the parent panel can refetch. */
  onSaved?: () => void;
}

type AddFieldDraft = {
  key: string;
  label: string;
  type: NodeConfigFieldType;
  required: boolean;
};

const EMPTY_DRAFT: AddFieldDraft = {
  key: '',
  label: '',
  type: 'text',
  required: false,
};

export function ConfigCard({ projectId, service, onSaved }: ConfigCardProps) {
  const {
    container_id: containerId,
    container_name: containerName,
    deployment_mode: deploymentMode,
    preset,
    schema,
    initial_values: initialValues,
    pending_input_id: pendingInputId,
    needs_restart: needsRestart,
  } = service;

  const isExternal = deploymentMode === 'external';
  const isAgentWaiting = Boolean(pendingInputId);

  const [isExpanded, setIsExpanded] = useState<boolean>(isAgentWaiting);
  /** Fields the user has added in this session, on top of `schema.fields`.
   * Sent as `overrides` on Save; cleared after a successful save (the next
   * GET will surface them via the backend's merge step). */
  const [addedFields, setAddedFields] = useState<FieldSchema[]>([]);
  const [fieldState, setFieldState] = useState<FieldStateMap>(() =>
    buildInitialState(schema.fields, initialValues as NodeConfigInitialValues)
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);

  /** Inline "+ Add field" mini-form state. */
  const [showAddForm, setShowAddForm] = useState(false);
  const [draft, setDraft] = useState<AddFieldDraft>(EMPTY_DRAFT);
  const [draftError, setDraftError] = useState<string | null>(null);

  const effectiveFields = useMemo(
    () => [...schema.fields, ...addedFields],
    [schema.fields, addedFields]
  );

  // Reset on prop change (refetch landed). Keep on container_id + value
  // signature; refetched fields are now part of `schema.fields` so we
  // discard local `addedFields`.
  const valuesSignature = useMemo(
    () => JSON.stringify(initialValues),
    [initialValues]
  );
  useEffect(() => {
    setFieldState(buildInitialState(schema.fields, initialValues as NodeConfigInitialValues));
    setAddedFields([]);
    setErrors({});
    setShowAddForm(false);
    setDraft(EMPTY_DRAFT);
    setDraftError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerId, valuesSignature]);

  const updateField = useCallback((key: string, patch: Partial<FieldState>) => {
    setFieldState((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }));
  }, []);

  const summary = useMemo(() => {
    const total = effectiveFields.length;
    const secrets = effectiveFields.filter((f) => f.is_secret).length;
    if (total === 0) return 'No fields';
    if (secrets === 0) return `${total} key${total === 1 ? '' : 's'}`;
    return `${total} key${total === 1 ? '' : 's'} · ${secrets} secret${secrets === 1 ? '' : 's'}`;
  }, [effectiveFields]);

  const handleAddField = useCallback(() => {
    const trimmedKey = draft.key.trim();
    const trimmedLabel = draft.label.trim() || trimmedKey;

    if (!trimmedKey) {
      setDraftError('Key is required');
      return;
    }
    if (/\s/.test(trimmedKey)) {
      setDraftError('Key cannot contain whitespace');
      return;
    }
    if (effectiveFields.some((f) => f.key === trimmedKey)) {
      setDraftError(`Key "${trimmedKey}" is already on this card`);
      return;
    }

    const isSecret = draft.type === 'secret';
    const newField: FieldSchema = {
      key: trimmedKey,
      label: trimmedLabel,
      type: draft.type,
      required: draft.required,
      is_secret: isSecret,
    };

    setAddedFields((prev) => [...prev, newField]);
    setFieldState((prev) => ({
      ...prev,
      [trimmedKey]: initialFieldState(newField, {}),
    }));
    // Reset draft + close mini-form
    setDraft(EMPTY_DRAFT);
    setDraftError(null);
    setShowAddForm(false);
  }, [draft, effectiveFields]);

  const handleRemoveAddedField = useCallback((key: string) => {
    setAddedFields((prev) => prev.filter((f) => f.key !== key));
    setFieldState((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setErrors((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const handleSave = useCallback(
    async (e?: React.FormEvent) => {
      e?.preventDefault();
      const validation = validateFieldState(effectiveFields, fieldState);
      setErrors(validation);
      if (Object.keys(validation).length > 0) {
        toast.error('Fix validation errors before saving');
        return;
      }

      const values = buildSubmitValues(effectiveFields, fieldState);
      setIsSaving(true);
      try {
        if (isAgentWaiting && pendingInputId) {
          await nodeConfigApi.submit(pendingInputId, values);
          toast.success(`Submitted ${containerName} — agent resuming`);
        } else {
          await nodeConfigApi.patchContainerConfig(projectId, containerId, {
            values,
            preset,
            mode: 'edit',
            // Persist user-added field metadata so the value lands under the
            // right merge bucket (text vs secret). Backend's schema-merge step
            // will surface them on the next GET.
            ...(addedFields.length > 0 ? { overrides: addedFields } : {}),
          });
          toast.success(`Saved ${containerName}`);
        }
        onSaved?.();
        setIsExpanded(false);
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Failed to save';
        toast.error(msg);
      } finally {
        setIsSaving(false);
      }
    },
    [
      addedFields,
      containerId,
      containerName,
      effectiveFields,
      fieldState,
      isAgentWaiting,
      onSaved,
      pendingInputId,
      preset,
      projectId,
    ]
  );

  const handleCancelAgent = useCallback(async () => {
    if (!pendingInputId) return;
    setIsCancelling(true);
    try {
      await nodeConfigApi.cancel(pendingInputId);
      toast('Cancelled — agent informed', { icon: 'ℹ️' });
      onSaved?.();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to cancel';
      toast.error(msg);
    } finally {
      setIsCancelling(false);
    }
  }, [pendingInputId, onSaved]);

  const baseInputClass =
    'w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]';

  return (
    <div
      className={`border rounded-[var(--radius)] bg-[var(--surface)] ${
        isAgentWaiting
          ? 'border-[var(--primary)]/60 ring-1 ring-[var(--primary)]/30'
          : 'border-[var(--border)]'
      }`}
      data-container-id={containerId}
    >
      {/* Header */}
      <button
        type="button"
        onClick={() => setIsExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[var(--bg)]/40 rounded-t-[var(--radius)]"
      >
        {isExpanded ? (
          <CaretDown size={12} weight="bold" className="text-[var(--text-muted)]" />
        ) : (
          <CaretRight size={12} weight="bold" className="text-[var(--text-muted)]" />
        )}
        {isExternal ? (
          <Plug size={14} weight="bold" className="text-purple-400 flex-shrink-0" />
        ) : (
          <Cube size={14} weight="bold" className="text-green-400 flex-shrink-0" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[12px] font-medium text-[var(--text)] truncate">
              {containerName}
            </span>
            {isAgentWaiting && (
              <span className="text-[9px] uppercase tracking-wide text-[var(--primary)] bg-[var(--primary)]/10 px-1.5 py-0.5 rounded">
                Agent waiting
              </span>
            )}
            {needsRestart && !isAgentWaiting && (
              <span className="text-[9px] uppercase tracking-wide text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded">
                Restart pending
              </span>
            )}
          </div>
          <div className="text-[10px] text-[var(--text-muted)] truncate">
            {preset} · {isExternal ? 'external' : 'internal container'} · {summary}
          </div>
        </div>
      </button>

      {/* Body */}
      {isExpanded && (
        <form onSubmit={handleSave} className="border-t border-[var(--border)] px-3 py-3">
          {isAgentWaiting && (
            <div className="flex items-start gap-2 mb-3 px-2 py-2 bg-[var(--primary)]/5 border border-[var(--primary)]/20 rounded-[var(--radius-small)]">
              <Info
                size={12}
                weight="bold"
                className="text-[var(--primary)] mt-[2px] flex-shrink-0"
              />
              <p className="text-[11px] text-[var(--text)]/80">
                The agent is paused waiting on these values. Submit to continue, or
                cancel to let it know you backed out.
              </p>
            </div>
          )}

          {effectiveFields.length === 0 && !showAddForm ? (
            <p className="text-[11px] text-[var(--text-muted)]">
              This node has no configurable fields yet — click{' '}
              <span className="font-medium">+ Add field</span> below to attach a
              custom env var or secret.
            </p>
          ) : (
            <div className="space-y-3">
              {effectiveFields.map((f) => {
                const st = fieldState[f.key];
                if (!st) return null;
                const errorMsg = errors[f.key];
                const isUserAdded = addedFields.some((af) => af.key === f.key);
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
                      <div className="flex items-center gap-1">
                        {f.is_secret && (
                          <span className="text-[9px] uppercase tracking-wide text-[var(--text-muted)]">
                            Secret
                          </span>
                        )}
                        {isUserAdded && (
                          <button
                            type="button"
                            onClick={() => handleRemoveAddedField(f.key)}
                            className="text-[var(--text-muted)] hover:text-red-400 transition-colors"
                            aria-label={`Remove field ${f.key}`}
                            title="Remove this field (only affects unsaved additions)"
                          >
                            <X size={10} weight="bold" />
                          </button>
                        )}
                      </div>
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
          )}

          {/* + Add field affordance — always visible (except when the agent is
              forcing a specific schema, in which case adding extras would
              confuse the resume flow). */}
          {!isAgentWaiting && (
            <div className="mt-3 pt-3 border-t border-dashed border-[var(--border)]">
              {showAddForm ? (
                <div className="space-y-2 px-2 py-2 bg-[var(--bg)]/40 rounded-[var(--radius-small)]">
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <label className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                        Key
                      </label>
                      <input
                        type="text"
                        value={draft.key}
                        onChange={(e) => {
                          setDraft({ ...draft, key: e.target.value });
                          setDraftError(null);
                        }}
                        placeholder="OPENWEATHERMAP_DEFAULT_CITY"
                        className={`${baseInputClass} font-mono`}
                        autoFocus
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                        Label
                      </label>
                      <input
                        type="text"
                        value={draft.label}
                        onChange={(e) => setDraft({ ...draft, label: e.target.value })}
                        placeholder={draft.key || 'Default city'}
                        className={baseInputClass}
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-2 items-end">
                    <div className="space-y-1">
                      <label className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                        Type
                      </label>
                      <select
                        value={draft.type}
                        onChange={(e) =>
                          setDraft({
                            ...draft,
                            type: e.target.value as NodeConfigFieldType,
                          })
                        }
                        className={baseInputClass}
                      >
                        <option value="text">text</option>
                        <option value="secret">secret</option>
                        <option value="url">url</option>
                        <option value="number">number</option>
                        <option value="textarea">textarea</option>
                      </select>
                    </div>
                    <label className="flex items-center gap-1.5 text-[11px] text-[var(--text)]/80 pb-1">
                      <input
                        type="checkbox"
                        checked={draft.required}
                        onChange={(e) =>
                          setDraft({ ...draft, required: e.target.checked })
                        }
                      />
                      Required
                    </label>
                  </div>
                  {draftError && (
                    <p className="text-[10px] text-red-400 flex items-center gap-1">
                      <Warning size={10} weight="bold" /> {draftError}
                    </p>
                  )}
                  <div className="flex items-center justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setShowAddForm(false);
                        setDraft(EMPTY_DRAFT);
                        setDraftError(null);
                      }}
                      className="btn"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={handleAddField}
                      className="btn btn-filled"
                    >
                      Add field
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setShowAddForm(true)}
                  className="text-[11px] text-[var(--text-muted)] hover:text-[var(--text)] flex items-center gap-1"
                >
                  <Plus size={12} weight="bold" />
                  Add field
                </button>
              )}
            </div>
          )}

          {/* Footer actions — visible if there's anything to save OR an agent
              is paused. An empty card with no added fields just renders the
              "+ Add field" affordance above. */}
          {(effectiveFields.length > 0 || isAgentWaiting) && (
            <div className="flex items-center justify-end gap-2 mt-3 pt-3 border-t border-[var(--border)]">
              {isAgentWaiting ? (
                <>
                  <button
                    type="button"
                    onClick={handleCancelAgent}
                    disabled={isCancelling || isSaving}
                    className="btn"
                  >
                    {isCancelling ? 'Cancelling…' : 'Cancel'}
                  </button>
                  <button
                    type="submit"
                    disabled={isCancelling || isSaving}
                    className="btn btn-filled"
                  >
                    {isSaving ? 'Submitting…' : 'Submit & continue'}
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => setIsExpanded(false)}
                    disabled={isSaving}
                    className="btn"
                  >
                    Close
                  </button>
                  <button
                    type="submit"
                    disabled={isSaving}
                    className="btn btn-filled"
                  >
                    {isSaving ? 'Saving…' : 'Save'}
                  </button>
                </>
              )}
            </div>
          )}
        </form>
      )}
    </div>
  );
}
