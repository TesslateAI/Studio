import { useState, useEffect, useCallback } from 'react';
import toast from 'react-hot-toast';
import { Key, Trash, Plus, Copy, Check, ShieldCheck, Clock } from '@phosphor-icons/react';
import { externalApi, projectsApi } from '../../lib/api';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { SettingsSection } from '../../components/settings';
import { ConfirmDialog } from '../../components/modals/ConfirmDialog';
import { useCancellableParallelRequests } from '../../hooks/useCancellableRequest';

interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[] | null;
  project_ids: string[] | null;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  key: string | null;
}

function formatRelativeDate(dateString: string | null): string {
  if (!dateString) return '';
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(date);
}

function getExpiryStatus(expiresAt: string | null): { label: string; className: string } {
  if (!expiresAt) return { label: 'Never expires', className: '' };
  const now = new Date();
  const expiry = new Date(expiresAt);
  if (expiry < now)
    return {
      label: 'Expired',
      className: 'px-2 py-0.5 bg-red-500/10 text-red-400 rounded text-[10px]',
    };
  const daysLeft = Math.ceil((expiry.getTime() - now.getTime()) / 86400000);
  if (daysLeft <= 7)
    return {
      label: `Expires in ${daysLeft}d`,
      className: 'px-2 py-0.5 bg-yellow-500/10 text-yellow-400 rounded text-[10px]',
    };
  return {
    label: `Expires in ${daysLeft}d`,
    className: 'px-2 py-0.5 bg-white/5 text-[var(--text-subtle)] rounded text-[10px]',
  };
}

export default function ApiKeysSettings() {
  // Data
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [projects, setProjects] = useState<{ id: string; name: string; slug: string }[]>([]);
  const [loading, setLoading] = useState(true);

  // Create form
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [expiryDays, setExpiryDays] = useState<number | null>(null);
  const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);

  // Created key display
  const [createdKey, setCreatedKey] = useState<ApiKey | null>(null);
  const [copied, setCopied] = useState(false);

  // Revoke
  const [deletingKeyId, setDeletingKeyId] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    confirmText: string;
    variant: 'danger' | 'warning' | 'info';
    onConfirm: () => void;
  }>({
    isOpen: false,
    title: '',
    message: '',
    confirmText: 'Confirm',
    variant: 'info',
    onConfirm: () => {},
  });

  const { executeAll } = useCancellableParallelRequests();

  const loadData = useCallback(() => {
    executeAll([() => externalApi.listKeys(), () => projectsApi.getAll()], {
      onAllSuccess: ([keysData, projectsData]: [unknown, unknown]) => {
        setKeys(keysData as ApiKey[]);
        setProjects(projectsData as { id: string; name: string; slug: string }[]);
      },
      onError: (error: unknown) => {
        const err = error as { response?: { data?: { detail?: string } } };
        toast.error(err.response?.data?.detail || 'Failed to load API keys');
      },
      onFinally: () => setLoading(false),
    });
  }, [executeAll]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const resetForm = () => {
    setNewKeyName('');
    setExpiryDays(null);
    setSelectedProjectIds([]);
  };

  const handleCreateKey = async () => {
    if (!newKeyName.trim()) return;
    setCreating(true);
    try {
      const data: { name: string; expires_in_days?: number; project_ids?: string[] } = {
        name: newKeyName.trim(),
      };
      if (expiryDays !== null) data.expires_in_days = expiryDays;
      if (selectedProjectIds.length > 0) data.project_ids = selectedProjectIds;

      const response = await externalApi.createKey(data);
      setCreatedKey(response as ApiKey);
      setShowCreateForm(false);
      resetForm();
      toast.success('API key created');
      loadData();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to create API key');
    } finally {
      setCreating(false);
    }
  };

  const handleRevokeKey = (keyId: string, keyName: string) => {
    setConfirmDialog({
      isOpen: true,
      title: `Revoke "${keyName}"`,
      message:
        'This key will stop working immediately. Any applications using it will lose access. This cannot be undone.',
      confirmText: 'Revoke',
      variant: 'danger',
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        setDeletingKeyId(keyId);
        try {
          await externalApi.deleteKey(keyId);
          toast.success('API key revoked');
          loadData();
        } catch (error: unknown) {
          const err = error as { response?: { data?: { detail?: string } } };
          toast.error(err.response?.data?.detail || 'Failed to revoke key');
        } finally {
          setDeletingKeyId(null);
        }
      },
    });
  };

  const handleCopyKey = async () => {
    if (!createdKey?.key) return;
    await navigator.clipboard.writeText(createdKey.key);
    setCopied(true);
    toast.success('API key copied to clipboard');
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDismissCreatedKey = () => {
    setCreatedKey(null);
    setCopied(false);
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading API keys..." size={60} />
      </div>
    );
  }

  return (
    <>
      <SettingsSection title="API Keys" description="Manage API keys for the Tesslate SDK">
        {/* Info box */}
        <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-xl">
          <div className="flex items-start gap-3">
            <ShieldCheck size={20} className="text-blue-400 mt-0.5 flex-shrink-0" />
            <div className="text-sm text-blue-400">
              <p className="font-semibold mb-1">SDK Authentication</p>
              <p className="text-xs opacity-80">
                API keys authenticate requests from the{' '}
                <code className="font-mono bg-blue-500/20 px-1 rounded">@tesslate/sdk</code>. Keys
                are prefixed with{' '}
                <code className="font-mono bg-blue-500/20 px-1 rounded">tsk_</code> and can be
                scoped to specific projects.
              </p>
            </div>
          </div>
        </div>

        {/* Created key banner */}
        {createdKey?.key && (
          <div className="p-4 bg-green-500/10 border border-green-500/20 rounded-xl">
            <div className="flex items-start gap-3">
              <Check size={20} className="text-green-400 mt-0.5 flex-shrink-0" weight="bold" />
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-green-400 mb-1">
                  API key created: {createdKey.name}
                </p>
                <p className="text-xs text-green-400/80 mb-3">
                  Copy this key now. It will not be shown again.
                </p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 font-mono text-sm bg-black/30 text-green-300 px-3 py-2 rounded-lg border border-green-500/20 select-all overflow-x-auto">
                    {createdKey.key}
                  </code>
                  <button
                    onClick={handleCopyKey}
                    className="btn btn-sm flex items-center gap-1.5 flex-shrink-0"
                  >
                    {copied ? <Check size={14} /> : <Copy size={14} />}
                    {copied ? 'Copied!' : 'Copy'}
                  </button>
                </div>
                <button
                  onClick={handleDismissCreatedKey}
                  className="mt-3 text-xs text-green-400/60 hover:text-green-400 transition-colors"
                >
                  Dismiss
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Header + create button */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-[var(--text)] flex items-center gap-2">
              <Key size={18} />
              Your API Keys
            </h3>
            {!showCreateForm && (
              <button
                onClick={() => setShowCreateForm(true)}
                className="btn btn-filled flex items-center gap-1.5"
              >
                <Plus size={14} weight="bold" />
                Create Key
              </button>
            )}
          </div>

          {/* Inline create form */}
          {showCreateForm && (
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] rounded-xl mb-4">
              <h4 className="font-semibold text-sm text-[var(--text)] mb-4">Create new API key</h4>
              <div className="space-y-4">
                {/* Name */}
                <div>
                  <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
                    Key name <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={newKeyName}
                    onChange={(e) => setNewKeyName(e.target.value)}
                    placeholder="e.g., Production, CI/CD Pipeline"
                    className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded-lg text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--primary)]"
                    maxLength={100}
                    autoFocus
                  />
                </div>

                {/* Expiry */}
                <div>
                  <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
                    Expiration
                  </label>
                  <select
                    value={expiryDays ?? 'never'}
                    onChange={(e) =>
                      setExpiryDays(e.target.value === 'never' ? null : Number(e.target.value))
                    }
                    className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded-lg text-sm text-[var(--text)] focus:outline-none focus:border-[var(--primary)]"
                  >
                    <option value="never">Never expires</option>
                    <option value="30">30 days</option>
                    <option value="60">60 days</option>
                    <option value="90">90 days</option>
                  </select>
                </div>

                {/* Project scope */}
                <div>
                  <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
                    Project scope
                  </label>
                  <p className="text-[11px] text-[var(--text-subtle)] mb-2">
                    Leave empty for access to all projects
                  </p>
                  <div className="max-h-40 overflow-y-auto space-y-1 bg-[var(--bg)] border border-[var(--border)] rounded-lg p-2">
                    {projects.map((project) => (
                      <label
                        key={project.id}
                        className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-[var(--surface-hover)] cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={selectedProjectIds.includes(project.id)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedProjectIds((prev) => [...prev, project.id]);
                            } else {
                              setSelectedProjectIds((prev) =>
                                prev.filter((id) => id !== project.id)
                              );
                            }
                          }}
                          className="rounded border-[var(--border)]"
                        />
                        <span className="text-sm text-[var(--text)]">{project.name}</span>
                      </label>
                    ))}
                    {projects.length === 0 && (
                      <p className="text-xs text-[var(--text-subtle)] px-2 py-1">
                        No projects found
                      </p>
                    )}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 pt-2">
                  <button
                    onClick={handleCreateKey}
                    disabled={!newKeyName.trim() || creating}
                    className="btn btn-filled flex items-center gap-1.5"
                  >
                    {creating ? 'Creating...' : 'Create Key'}
                  </button>
                  <button
                    onClick={() => {
                      setShowCreateForm(false);
                      resetForm();
                    }}
                    className="btn"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Key list */}
          {keys.length > 0 ? (
            <div className="space-y-3">
              {keys.map((apiKey) => {
                const expiry = getExpiryStatus(apiKey.expires_at);
                return (
                  <div
                    key={apiKey.id}
                    className="p-4 bg-[var(--surface)] border border-[var(--border)] rounded-xl hover:border-[var(--border-hover)] transition-all"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-start gap-3 flex-1 min-w-0">
                        <div className="w-10 h-10 rounded-lg bg-[var(--primary)]/10 flex items-center justify-center flex-shrink-0">
                          <Key size={20} className="text-[var(--primary)]" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <h4 className="font-semibold text-sm text-[var(--text)] mb-1">
                            {apiKey.name}
                          </h4>
                          <code className="text-xs font-mono text-[var(--text-subtle)] bg-[var(--bg)] px-2 py-0.5 rounded">
                            {apiKey.key_prefix}...
                          </code>
                          <div className="flex items-center gap-3 mt-2 flex-wrap text-[11px] text-[var(--text-subtle)]">
                            <span className="flex items-center gap-1">
                              <Clock size={12} />
                              Created {formatRelativeDate(apiKey.created_at)}
                            </span>
                            <span>
                              {apiKey.last_used_at
                                ? `Last used ${formatRelativeDate(apiKey.last_used_at)}`
                                : 'Never used'}
                            </span>
                            {expiry.className ? (
                              <span className={expiry.className}>{expiry.label}</span>
                            ) : (
                              <span>{expiry.label}</span>
                            )}
                            {apiKey.project_ids ? (
                              <span className="px-2 py-0.5 bg-blue-500/10 text-blue-400 rounded text-[10px]">
                                {apiKey.project_ids.length} project
                                {apiKey.project_ids.length !== 1 ? 's' : ''}
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 bg-white/5 text-[var(--text-subtle)] rounded text-[10px]">
                                All projects
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                      <button
                        onClick={() => handleRevokeKey(apiKey.id, apiKey.name)}
                        disabled={deletingKeyId === apiKey.id}
                        className="p-2 text-[var(--text-subtle)] hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors disabled:opacity-50 flex-shrink-0"
                        title="Revoke key"
                      >
                        {deletingKeyId === apiKey.id ? (
                          <svg
                            className="w-[18px] h-[18px] animate-spin"
                            viewBox="0 0 24 24"
                            fill="none"
                          >
                            <circle
                              className="opacity-25"
                              cx="12"
                              cy="12"
                              r="10"
                              stroke="currentColor"
                              strokeWidth="4"
                            />
                            <path
                              className="opacity-75"
                              fill="currentColor"
                              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                            />
                          </svg>
                        ) : (
                          <Trash size={18} />
                        )}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : !showCreateForm ? (
            <div className="text-center py-12">
              <div className="w-16 h-16 rounded-2xl bg-[var(--surface)] border border-[var(--border)] flex items-center justify-center mx-auto mb-4">
                <Key size={32} className="text-[var(--text-subtle)]" />
              </div>
              <h3 className="text-sm font-semibold text-[var(--text)] mb-2">No API keys yet</h3>
              <p className="text-xs text-[var(--text-subtle)] mb-4 max-w-sm mx-auto">
                Create an API key to authenticate requests from the Tesslate SDK in your
                applications.
              </p>
              <button
                onClick={() => setShowCreateForm(true)}
                className="btn btn-filled flex items-center gap-1.5 mx-auto"
              >
                <Plus size={14} weight="bold" />
                Create your first key
              </button>
            </div>
          ) : null}
        </div>
      </SettingsSection>

      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        onClose={() => setConfirmDialog((prev) => ({ ...prev, isOpen: false }))}
        onConfirm={confirmDialog.onConfirm}
        title={confirmDialog.title}
        message={confirmDialog.message}
        confirmText={confirmDialog.confirmText}
        variant={confirmDialog.variant}
      />
    </>
  );
}
