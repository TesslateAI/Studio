import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Check,
  ExternalLink,
  Eye,
  EyeOff,
  Plus,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import { ToggleLeft, ToggleRight } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import type { ProviderMeta } from './providers';
import type { ApiKey, ModelInfo } from '../../pages/library/ModelsPage';
import { marketplaceApi, secretsApi } from '../../lib/api';

interface ProviderSetupDrawerProps {
  open: boolean;
  meta: ProviderMeta;
  /** Provider id used for API calls — same as meta.key for built-in providers, slug for custom. */
  providerId: string;
  /** Required-key flag. Built-in/Tesslate providers (e.g. internal) hide the key form. */
  requiresKey: boolean;
  existingKey?: ApiKey;
  /** Models attributable to this provider, both system and custom. */
  providerModels: ModelInfo[];
  onClose: () => void;
  onToggleModel: (modelId: string, currentlyDisabled: boolean) => void;
  /** Called after a successful key add/delete or custom-model add/delete so the parent can reload. */
  onChanged: () => void;
}

function formatCreditsPerMillion(usdPer1M: number): string {
  const credits = usdPer1M * 100;
  if (credits === 0) return '0';
  if (Number.isInteger(credits)) return credits.toLocaleString();
  return credits.toFixed(1);
}

function shortName(model: ModelInfo): string {
  if (model.name.includes('/')) {
    const last = model.name.split('/').pop();
    return last || model.name;
  }
  return model.name;
}

export function ProviderSetupDrawer({
  open,
  meta,
  providerId,
  requiresKey,
  existingKey,
  providerModels,
  onClose,
  onToggleModel,
  onChanged,
}: ProviderSetupDrawerProps) {
  const [apiKey, setApiKey] = useState('');
  const [keyName, setKeyName] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [savingKey, setSavingKey] = useState(false);
  const [confirmDeleteKey, setConfirmDeleteKey] = useState(false);
  const [deletingKey, setDeletingKey] = useState(false);
  const [modelSearch, setModelSearch] = useState('');
  const [newModelId, setNewModelId] = useState('');
  const [addingModel, setAddingModel] = useState(false);

  const keyInputRef = useRef<HTMLInputElement>(null);

  // Reset form when drawer opens or provider changes
  useEffect(() => {
    if (!open) return;
    setApiKey('');
    setKeyName('');
    setShowKey(false);
    setConfirmDeleteKey(false);
    setModelSearch('');
    setNewModelId('');
    if (requiresKey && !existingKey) {
      requestAnimationFrame(() => keyInputRef.current?.focus());
    }
  }, [open, providerId, requiresKey, existingKey]);

  // ESC closes
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !savingKey && !deletingKey) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, savingKey, deletingKey, onClose]);

  const filteredModels = useMemo(() => {
    if (!modelSearch) return providerModels;
    const q = modelSearch.toLowerCase();
    return providerModels.filter(
      (m) => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q)
    );
  }, [providerModels, modelSearch]);

  const enabledCount = providerModels.filter((m) => !m.disabled).length;

  const handleSaveKey = async () => {
    if (!apiKey.trim()) {
      toast.error('Paste an API key first.');
      return;
    }
    setSavingKey(true);
    try {
      await secretsApi.addApiKey({
        provider: providerId,
        api_key: apiKey.trim(),
        key_name: keyName.trim() || undefined,
      });
      toast.success(`${meta.name} connected`);
      setApiKey('');
      setKeyName('');
      onChanged();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(detail || `Failed to add ${meta.name} key`);
    } finally {
      setSavingKey(false);
    }
  };

  const handleDeleteKey = async () => {
    if (!existingKey) return;
    setDeletingKey(true);
    try {
      await secretsApi.deleteApiKey(Number(existingKey.id));
      toast.success(`${meta.name} disconnected`);
      setConfirmDeleteKey(false);
      onChanged();
    } catch {
      toast.error('Failed to disconnect');
    } finally {
      setDeletingKey(false);
    }
  };

  const handleAddCustomModel = async () => {
    const trimmed = newModelId.trim();
    if (!trimmed) return;
    setAddingModel(true);
    try {
      await marketplaceApi.addCustomModel({
        model_id: trimmed,
        model_name: trimmed,
        provider: providerId,
      });
      toast.success('Model added');
      setNewModelId('');
      onChanged();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(detail || 'Failed to add model');
    } finally {
      setAddingModel(false);
    }
  };

  const handleDeleteCustomModel = async (customId: string) => {
    try {
      await marketplaceApi.deleteCustomModel(customId);
      toast.success('Model removed');
      onChanged();
    } catch {
      toast.error('Failed to remove model');
    }
  };

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-8"
          style={{ background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(2px)' }}
          onClick={() => !savingKey && !deletingKey && onClose()}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label={`Configure ${meta.name}`}
            onClick={(e) => e.stopPropagation()}
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: 4 }}
            transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
            className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg)] shadow-2xl"
          >
            {/* Header */}
            <header className="flex items-start justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
              <div className="flex min-w-0 items-center gap-3">
                <div
                  className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-md"
                  style={{ backgroundColor: `${meta.brandColor}1a` }}
                  aria-hidden="true"
                >
                  <span
                    className="block h-5 w-5"
                    style={{
                      backgroundColor: meta.brandColor,
                      maskImage: `url("${meta.iconUrl}")`,
                      WebkitMaskImage: `url("${meta.iconUrl}")`,
                      maskRepeat: 'no-repeat',
                      WebkitMaskRepeat: 'no-repeat',
                      maskSize: 'contain',
                      WebkitMaskSize: 'contain',
                      maskPosition: 'center',
                      WebkitMaskPosition: 'center',
                    }}
                  />
                </div>
                <div className="min-w-0">
                  <h2 className="truncate text-sm font-semibold text-[var(--text)]">{meta.name}</h2>
                  <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                    {providerModels.length} model{providerModels.length === 1 ? '' : 's'} available
                    {' · '}
                    {enabledCount} enabled
                  </p>
                </div>
              </div>
              <div className="flex flex-shrink-0 items-center gap-1">
                {meta.website && (
                  <a
                    href={meta.website}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 rounded-[var(--radius-small)] px-2 py-1 text-[11px] font-medium text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
                  >
                    Console
                    <ExternalLink size={11} />
                  </a>
                )}
                <button
                  onClick={onClose}
                  disabled={savingKey || deletingKey}
                  aria-label="Close"
                  className="rounded-[var(--radius-small)] p-1 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text)] disabled:opacity-50"
                >
                  <X size={16} />
                </button>
              </div>
            </header>

            {/* Body */}
            <div className="flex-1 overflow-y-auto">
              {/* API Key section */}
              {requiresKey && (
                <section className="border-b border-[var(--border)] px-5 py-4">
                  <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    API key
                  </h3>
                  {existingKey ? (
                    <div className="flex items-center justify-between gap-3 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5">
                      <div className="flex min-w-0 items-center gap-2.5">
                        <Check size={14} className="flex-shrink-0 text-emerald-500" />
                        <div className="min-w-0">
                          <div className="truncate text-[12px] font-medium text-[var(--text)]">
                            {existingKey.key_name || 'Default key'}
                          </div>
                          <div className="truncate font-mono text-[10.5px] text-[var(--text-subtle)]">
                            {existingKey.key_preview}
                          </div>
                        </div>
                      </div>
                      {confirmDeleteKey ? (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => setConfirmDeleteKey(false)}
                            disabled={deletingKey}
                            className="btn btn-sm"
                          >
                            Cancel
                          </button>
                          <button
                            onClick={handleDeleteKey}
                            disabled={deletingKey}
                            className="btn btn-sm btn-danger"
                          >
                            {deletingKey ? 'Removing…' : 'Confirm'}
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setConfirmDeleteKey(true)}
                          className="rounded p-1.5 text-[var(--text-muted)] hover:bg-red-500/10 hover:text-red-500"
                          aria-label="Disconnect key"
                          title="Disconnect"
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                  ) : (
                    <div className="space-y-2.5">
                      <div className="relative">
                        <input
                          ref={keyInputRef}
                          type={showKey ? 'text' : 'password'}
                          value={apiKey}
                          onChange={(e) => setApiKey(e.target.value)}
                          placeholder="Paste your API key"
                          autoComplete="off"
                          spellCheck={false}
                          className="w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 pr-10 font-mono text-[12px] text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:border-[var(--border-hover)] focus:outline-none"
                        />
                        <button
                          type="button"
                          onClick={() => setShowKey((v) => !v)}
                          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-[var(--text-subtle)] hover:text-[var(--text)]"
                          aria-label={showKey ? 'Hide key' : 'Show key'}
                        >
                          {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                        </button>
                      </div>
                      <input
                        type="text"
                        value={keyName}
                        onChange={(e) => setKeyName(e.target.value)}
                        placeholder="Key name (optional)"
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-[12px] text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:border-[var(--border-hover)] focus:outline-none"
                      />
                      <div className="flex items-center justify-end">
                        <button
                          onClick={handleSaveKey}
                          disabled={savingKey || !apiKey.trim()}
                          className="btn btn-filled btn-sm disabled:opacity-50"
                        >
                          {savingKey ? 'Connecting…' : `Connect ${meta.name}`}
                        </button>
                      </div>
                    </div>
                  )}
                </section>
              )}

              {/* Models section */}
              <section className="px-5 py-4">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    Available models
                  </h3>
                  {providerModels.length > 4 && (
                    <div className="flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1">
                      <Search size={12} className="text-[var(--text-subtle)]" />
                      <input
                        value={modelSearch}
                        onChange={(e) => setModelSearch(e.target.value)}
                        placeholder="Search models"
                        className="w-32 border-none bg-transparent text-[11px] text-[var(--text)] placeholder:text-[var(--text-subtle)] outline-none"
                      />
                    </div>
                  )}
                </div>

                {providerModels.length === 0 ? (
                  <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-6 text-center">
                    <p className="text-[12px] text-[var(--text-muted)]">
                      No models available yet.
                    </p>
                    <p className="mt-1 text-[10.5px] text-[var(--text-subtle)]">
                      Add a custom model id below to start using this provider.
                    </p>
                  </div>
                ) : filteredModels.length === 0 ? (
                  <p className="py-4 text-center text-[12px] text-[var(--text-muted)]">
                    No models match &ldquo;{modelSearch}&rdquo;.
                  </p>
                ) : (
                  <div className="overflow-hidden rounded-md border border-[var(--border)] bg-[var(--surface)]">
                    <ul className="divide-y divide-[var(--border)]">
                      {filteredModels.map((m) => {
                        const isOff = !!m.disabled;
                        const showPrice =
                          m.pricing && (m.pricing.input > 0 || m.pricing.output > 0);
                        return (
                          <li
                            key={m.id}
                            className={`group flex items-center gap-3 px-3 py-2.5 ${
                              isOff ? 'opacity-60' : ''
                            }`}
                          >
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="truncate text-[12.5px] font-medium text-[var(--text)]">
                                  {shortName(m)}
                                </span>
                                {m.source === 'custom' && (
                                  <span className="rounded bg-[var(--bg)] px-1.5 py-px text-[9px] font-medium uppercase tracking-wide text-[var(--text-subtle)] ring-1 ring-[var(--border)]">
                                    Custom
                                  </span>
                                )}
                                {m.health === 'unhealthy' && (
                                  <span className="rounded bg-red-500/10 px-1.5 py-px text-[9px] font-medium uppercase tracking-wide text-red-500">
                                    Down
                                  </span>
                                )}
                              </div>
                              {showPrice && (
                                <div className="mt-0.5 font-mono text-[10.5px] text-[var(--text-subtle)]">
                                  {formatCreditsPerMillion(m.pricing!.input)}/
                                  {formatCreditsPerMillion(m.pricing!.output)} per 1M
                                </div>
                              )}
                            </div>
                            <div className="flex flex-shrink-0 items-center gap-1">
                              {m.custom_id && (
                                <button
                                  type="button"
                                  onClick={() => handleDeleteCustomModel(m.custom_id!)}
                                  className="rounded p-1.5 text-[var(--text-muted)] opacity-0 transition-opacity hover:bg-red-500/10 hover:text-red-500 group-hover:opacity-100 focus:opacity-100"
                                  aria-label={`Remove ${shortName(m)}`}
                                  title="Remove"
                                >
                                  <Trash2 size={13} />
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() => onToggleModel(m.id, isOff)}
                                className="text-[var(--text-muted)] hover:text-[var(--text)]"
                                aria-label={isOff ? `Enable ${shortName(m)}` : `Disable ${shortName(m)}`}
                                title={isOff ? 'Enable' : 'Disable'}
                              >
                                {isOff ? (
                                  <ToggleLeft size={20} />
                                ) : (
                                  <ToggleRight size={20} className="text-[var(--primary)]" />
                                )}
                              </button>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}

                {/* Add custom model */}
                <div className="mt-3 flex items-center gap-2">
                  <input
                    value={newModelId}
                    onChange={(e) => setNewModelId(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleAddCustomModel();
                    }}
                    placeholder="Add a custom model id (e.g. gpt-4o-audio-preview)"
                    className="flex-1 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 font-mono text-[11.5px] text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:border-[var(--border-hover)] focus:outline-none"
                  />
                  <button
                    onClick={handleAddCustomModel}
                    disabled={!newModelId.trim() || addingModel}
                    className="btn btn-sm disabled:opacity-50"
                  >
                    <Plus size={12} />
                    {addingModel ? 'Adding…' : 'Add'}
                  </button>
                </div>
              </section>
            </div>

            {/* Footer */}
            <footer className="flex items-center justify-between gap-3 border-t border-[var(--border)] bg-[var(--surface)] px-5 py-3">
              <span className="text-[11px] text-[var(--text-subtle)]">
                {requiresKey && !existingKey
                  ? 'Connect a key to enable models'
                  : `${enabledCount} of ${providerModels.length} enabled`}
              </span>
              <button onClick={onClose} className="btn btn-sm">
                Done
              </button>
            </footer>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  );
}
