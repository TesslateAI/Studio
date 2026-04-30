/**
 * Marketplace Sources settings page (Wave 5).
 *
 * Lets users register, test, sync, edit, and delete federated marketplace
 * hubs. System rows (``tesslate-official``, ``local``) are read-only — they
 * appear in the table for visibility but expose no edit / delete affordance.
 *
 * Trust levels visible here:
 *   - ``official``       — green badge, fixed (system row)
 *   - ``admin_trusted``  — blue badge, only superusers can promote/demote
 *   - ``local``          — neutral badge, system row
 *   - ``private``        — yellow badge, has bearer token
 *   - ``untrusted``      — red badge, no token; MCP and app installs blocked
 *
 * The promote-to-trusted action is rendered only when the requester is a
 * superuser AND the row is currently ``private``.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import {
  Cloud,
  Plus,
  Trash,
  Pencil,
  ShieldCheck,
  ArrowsClockwise,
  CheckCircle,
  Warning,
  XCircle,
  CircleNotch,
  Lightning,
  Lock,
} from '@phosphor-icons/react';
import {
  marketplaceSourcesApi,
  type MarketplaceSourceResponse,
  type MarketplaceSourceCreate,
  type MarketplaceSourceUpdate,
  type MarketplaceSourceTrustLevel,
} from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { useTeam } from '../../contexts/TeamContext';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { SettingsSection } from '../../components/settings';
import { ConfirmDialog } from '../../components/modals/ConfirmDialog';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatRelativeDate(dateString: string | null): string {
  if (!dateString) return 'Never';
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

interface TrustBadgeStyle {
  label: string;
  className: string;
}

function trustBadgeStyle(level: MarketplaceSourceTrustLevel): TrustBadgeStyle {
  switch (level) {
    case 'official':
      return {
        label: 'Official',
        className:
          'px-2 py-0.5 bg-emerald-500/10 text-emerald-400 rounded text-[10px] font-medium',
      };
    case 'admin_trusted':
      return {
        label: 'Admin Trusted',
        className: 'px-2 py-0.5 bg-blue-500/10 text-blue-400 rounded text-[10px] font-medium',
      };
    case 'local':
      return {
        label: 'Local',
        className:
          'px-2 py-0.5 bg-white/5 text-[var(--text-subtle)] rounded text-[10px] font-medium',
      };
    case 'private':
      return {
        label: 'Private',
        className: 'px-2 py-0.5 bg-yellow-500/10 text-yellow-400 rounded text-[10px] font-medium',
      };
    case 'untrusted':
      return {
        label: 'Untrusted',
        className: 'px-2 py-0.5 bg-red-500/10 text-red-400 rounded text-[10px] font-medium',
      };
    default:
      return {
        label: level,
        className:
          'px-2 py-0.5 bg-white/5 text-[var(--text-subtle)] rounded text-[10px] font-medium',
      };
  }
}

function extractDetail(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') {
    const obj = detail as { message?: string; error?: string };
    if (typeof obj.message === 'string') return obj.message;
    if (typeof obj.error === 'string') return obj.error;
  }
  return e?.message ?? fallback;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface SourceFormValues {
  handle: string;
  display_name: string;
  base_url: string;
  encrypted_token: string;
  scope: 'user' | 'team';
}

const EMPTY_FORM: SourceFormValues = {
  handle: '',
  display_name: '',
  base_url: '',
  encrypted_token: '',
  scope: 'user',
};

interface SourceFormProps {
  initial?: Partial<SourceFormValues> & { is_edit?: boolean };
  hasTeam: boolean;
  hasExistingToken: boolean;
  busy: boolean;
  onSubmit: (values: SourceFormValues, options: { clear_token: boolean }) => Promise<void>;
  onCancel: () => void;
}

function SourceForm({
  initial,
  hasTeam,
  hasExistingToken,
  busy,
  onSubmit,
  onCancel,
}: SourceFormProps) {
  const isEdit = Boolean(initial?.is_edit);
  const [form, setForm] = useState<SourceFormValues>({ ...EMPTY_FORM, ...initial });
  const [clearToken, setClearToken] = useState(false);

  const update = <K extends keyof SourceFormValues>(key: K, value: SourceFormValues[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const submit = async () => {
    await onSubmit(form, { clear_token: clearToken });
  };

  const canSubmit =
    !busy &&
    form.display_name.trim().length > 0 &&
    (isEdit || (form.handle.trim().length > 0 && form.base_url.trim().length > 0));

  return (
    <div className="p-4 bg-[var(--surface)] border border-[var(--border)] rounded-xl mb-4 space-y-4">
      <h4 className="font-semibold text-sm text-[var(--text)]">
        {isEdit ? 'Edit marketplace source' : 'Add marketplace source'}
      </h4>

      <div>
        <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
          Handle <span className="text-red-400">*</span>
        </label>
        <input
          type="text"
          value={form.handle}
          onChange={(e) => update('handle', e.target.value)}
          placeholder="e.g., partner-hub"
          disabled={isEdit}
          className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded-lg text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--primary)] disabled:opacity-60"
          maxLength={64}
        />
        <p className="text-[11px] text-[var(--text-subtle)] mt-1">
          Lowercase letters, digits, hyphen, underscore. Must be unique within your scope.
        </p>
      </div>

      <div>
        <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
          Display name <span className="text-red-400">*</span>
        </label>
        <input
          type="text"
          value={form.display_name}
          onChange={(e) => update('display_name', e.target.value)}
          placeholder="e.g., Partner Marketplace"
          className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded-lg text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--primary)]"
          maxLength={128}
        />
      </div>

      <div>
        <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
          Base URL <span className="text-red-400">*</span>
        </label>
        <input
          type="url"
          value={form.base_url}
          onChange={(e) => update('base_url', e.target.value)}
          placeholder="https://marketplace.example.com"
          disabled={isEdit}
          className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded-lg text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--primary)] disabled:opacity-60"
          maxLength={500}
        />
        <p className="text-[11px] text-[var(--text-subtle)] mt-1">
          Must use https:// in production. http://localhost is allowed for local hubs.
        </p>
      </div>

      <div>
        <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
          Bearer token (optional)
        </label>
        <input
          type="password"
          value={form.encrypted_token}
          onChange={(e) => update('encrypted_token', e.target.value)}
          placeholder={
            isEdit && hasExistingToken
              ? 'Leave blank to keep the saved token'
              : 'Leave blank for an anonymous (untrusted) source'
          }
          disabled={clearToken}
          className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded-lg text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--primary)] disabled:opacity-60"
          autoComplete="off"
        />
        <p className="text-[11px] text-[var(--text-subtle)] mt-1">
          Sources without a token are classified as untrusted. MCP server and app installs are
          blocked from untrusted sources.
        </p>
        {isEdit && hasExistingToken && (
          <label className="flex items-center gap-2 mt-2 cursor-pointer text-[11px] text-[var(--text-subtle)]">
            <input
              type="checkbox"
              checked={clearToken}
              onChange={(e) => setClearToken(e.target.checked)}
              className="rounded border-[var(--border)]"
            />
            Remove the saved token (revert to untrusted)
          </label>
        )}
      </div>

      {!isEdit && (
        <div>
          <label className="text-xs font-medium text-[var(--text)] block mb-1.5">Scope</label>
          <select
            value={form.scope}
            onChange={(e) => update('scope', e.target.value as 'user' | 'team')}
            className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded-lg text-sm text-[var(--text)] focus:outline-none focus:border-[var(--primary)]"
          >
            <option value="user">Mine (only visible to me)</option>
            <option value="team" disabled={!hasTeam}>
              Share with team {hasTeam ? '' : '(requires a team)'}
            </option>
          </select>
        </div>
      )}

      <div className="flex items-center gap-2 pt-2">
        <button
          onClick={submit}
          disabled={!canSubmit}
          className="btn btn-filled flex items-center gap-1.5"
        >
          {busy ? 'Saving...' : isEdit ? 'Save changes' : 'Add source'}
        </button>
        <button onClick={onCancel} disabled={busy} className="btn">
          Cancel
        </button>
      </div>
    </div>
  );
}

interface SourceRowProps {
  source: MarketplaceSourceResponse;
  isSuperuser: boolean;
  busyAction: 'test' | 'sync' | 'toggle' | 'delete' | 'promote' | null;
  onTest: (source: MarketplaceSourceResponse) => void;
  onSync: (source: MarketplaceSourceResponse) => void;
  onToggleActive: (source: MarketplaceSourceResponse) => void;
  onEdit: (source: MarketplaceSourceResponse) => void;
  onDelete: (source: MarketplaceSourceResponse) => void;
  onPromote: (source: MarketplaceSourceResponse) => void;
}

function SourceRow({
  source,
  isSuperuser,
  busyAction,
  onTest,
  onSync,
  onToggleActive,
  onEdit,
  onDelete,
  onPromote,
}: SourceRowProps) {
  const trust = trustBadgeStyle(source.trust_level);
  const isUntrusted = source.trust_level === 'untrusted';
  const visibleCaps = source.capabilities.slice(0, 4);
  const hiddenCount = source.capabilities.length - visibleCaps.length;

  return (
    <div
      className="p-4 bg-[var(--surface)] border border-[var(--border)] rounded-xl hover:border-[var(--border-hover)] transition-all"
      data-testid={`marketplace-source-row-${source.handle}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 flex-1 min-w-0">
          <div className="w-10 h-10 rounded-lg bg-[var(--primary)]/10 flex items-center justify-center flex-shrink-0">
            <Cloud size={20} className="text-[var(--primary)]" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <h4 className="font-semibold text-sm text-[var(--text)]">{source.display_name}</h4>
              <span className={trust.className}>{trust.label}</span>
              {source.is_system && (
                <span className="px-2 py-0.5 bg-white/5 text-[var(--text-subtle)] rounded text-[10px] font-medium flex items-center gap-1">
                  <Lock size={9} />
                  System
                </span>
              )}
              {!source.is_active && !source.is_system && (
                <span className="px-2 py-0.5 bg-white/5 text-[var(--text-subtle)] rounded text-[10px] font-medium">
                  Disabled
                </span>
              )}
              {source.last_sync_error && (
                <span
                  className="px-2 py-0.5 bg-red-500/10 text-red-400 rounded text-[10px] font-medium flex items-center gap-1"
                  title={source.last_sync_error}
                >
                  <Warning size={9} weight="fill" />
                  Sync error
                </span>
              )}
              {isUntrusted && (
                <span
                  className="px-2 py-0.5 bg-red-500/10 text-red-400 rounded text-[10px] font-medium flex items-center gap-1"
                  title="MCP servers and Tesslate Apps cannot be installed from untrusted sources. Add a bearer token to upgrade to private trust."
                >
                  <XCircle size={9} weight="fill" />
                  MCP &amp; app installs blocked
                </span>
              )}
            </div>
            <code className="text-xs font-mono text-[var(--text-subtle)] bg-[var(--bg)] px-2 py-0.5 rounded">
              {source.handle}
            </code>
            <p className="text-[11px] text-[var(--text-subtle)] mt-1 truncate" title={source.base_url}>
              {source.base_url}
            </p>

            {visibleCaps.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {visibleCaps.map((cap) => (
                  <span
                    key={cap}
                    className="px-1.5 py-0.5 bg-[var(--bg)] border border-[var(--border)] rounded text-[10px] font-mono text-[var(--text-subtle)]"
                  >
                    {cap}
                  </span>
                ))}
                {hiddenCount > 0 && (
                  <span
                    className="px-1.5 py-0.5 bg-[var(--bg)] border border-[var(--border)] rounded text-[10px] text-[var(--text-subtle)]"
                    title={source.capabilities.slice(4).join(', ')}
                  >
                    +{hiddenCount} more
                  </span>
                )}
              </div>
            )}

            <div className="flex items-center gap-3 mt-2 flex-wrap text-[11px] text-[var(--text-subtle)]">
              <span>Last synced {formatRelativeDate(source.last_synced_at)}</span>
              {source.has_token && (
                <span className="flex items-center gap-1 text-emerald-400/80">
                  <ShieldCheck size={11} weight="fill" />
                  Token saved
                </span>
              )}
              {source.scope !== 'system' && (
                <span className="px-1.5 py-0.5 bg-white/5 rounded text-[10px]">
                  {source.scope === 'team' ? 'Team' : 'Personal'}
                </span>
              )}
            </div>
          </div>
        </div>

        {!source.is_system && (
          <label
            className="flex items-center gap-2 text-[11px] text-[var(--text-subtle)] cursor-pointer flex-shrink-0"
            title="Enable or disable this source"
          >
            <input
              type="checkbox"
              checked={source.is_active}
              onChange={() => onToggleActive(source)}
              disabled={busyAction === 'toggle'}
              className="rounded border-[var(--border)]"
              data-testid={`source-toggle-${source.handle}`}
            />
            Enabled
          </label>
        )}
      </div>

      {/* Per-row actions */}
      <div className="flex items-center gap-2 mt-3 flex-wrap">
        <button
          onClick={() => onTest(source)}
          disabled={busyAction === 'test'}
          className="btn btn-sm flex items-center gap-1.5"
          title="Verify the hub identity and refresh advertised capabilities"
          data-testid={`source-test-${source.handle}`}
        >
          {busyAction === 'test' ? (
            <CircleNotch size={12} className="animate-spin" />
          ) : (
            <CheckCircle size={12} />
          )}
          Test connection
        </button>
        {!source.is_system && (
          <button
            onClick={() => onSync(source)}
            disabled={busyAction === 'sync' || !source.is_active}
            className="btn btn-sm flex items-center gap-1.5"
            title={source.is_active ? 'Run a one-shot sync' : 'Enable this source to sync'}
            data-testid={`source-sync-${source.handle}`}
          >
            {busyAction === 'sync' ? (
              <CircleNotch size={12} className="animate-spin" />
            ) : (
              <ArrowsClockwise size={12} />
            )}
            Sync now
          </button>
        )}
        {!source.is_system && (
          <button
            onClick={() => onEdit(source)}
            className="btn btn-sm flex items-center gap-1.5"
            title="Edit display name or token"
            data-testid={`source-edit-${source.handle}`}
          >
            <Pencil size={12} />
            Edit
          </button>
        )}
        {!source.is_system && (
          <button
            onClick={() => onDelete(source)}
            disabled={busyAction === 'delete'}
            className="btn btn-sm text-red-400 hover:bg-red-500/10 flex items-center gap-1.5"
            title="Soft-delete this source"
            data-testid={`source-delete-${source.handle}`}
          >
            {busyAction === 'delete' ? (
              <CircleNotch size={12} className="animate-spin" />
            ) : (
              <Trash size={12} />
            )}
            Delete
          </button>
        )}
        {isSuperuser && !source.is_system && source.trust_level === 'private' && (
          <button
            onClick={() => onPromote(source)}
            disabled={busyAction === 'promote'}
            className="btn btn-sm flex items-center gap-1.5"
            title="Promote to admin_trusted (skips per-install confirmation prompt)"
            data-testid={`source-promote-${source.handle}`}
          >
            {busyAction === 'promote' ? (
              <CircleNotch size={12} className="animate-spin" />
            ) : (
              <Lightning size={12} weight="fill" />
            )}
            Promote to trusted
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function MarketplaceSourcesSettings() {
  const { user } = useAuth();
  const isSuperuser = Boolean(user?.is_superuser);
  const { activeTeam, teamSwitchKey } = useTeam();
  const hasTeam = Boolean(activeTeam && !activeTeam.is_personal);

  const [sources, setSources] = useState<MarketplaceSourceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);
  // Per-row in-flight action so spinners only render on the targeted source.
  const [rowBusy, setRowBusy] = useState<{
    id: string;
    action: 'test' | 'sync' | 'toggle' | 'delete' | 'promote';
  } | null>(null);
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

  const loadSources = useCallback(async () => {
    setLoading(true);
    try {
      const data = await marketplaceSourcesApi.list({ include_inactive: true });
      setSources(data);
    } catch (err) {
      toast.error(extractDetail(err, 'Failed to load marketplace sources'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSources();
  }, [loadSources, teamSwitchKey]);

  const editingSource = useMemo(
    () => (editingId ? sources.find((s) => s.id === editingId) ?? null : null),
    [editingId, sources]
  );

  const handleCreate = async (
    values: SourceFormValues,
    _options: { clear_token: boolean }
  ) => {
    setCreating(true);
    try {
      const payload: MarketplaceSourceCreate = {
        handle: values.handle.trim(),
        display_name: values.display_name.trim(),
        base_url: values.base_url.trim(),
        scope: values.scope,
      };
      const token = values.encrypted_token.trim();
      if (token) payload.encrypted_token = token;
      const created = await marketplaceSourcesApi.create(payload);
      setSources((prev) => [...prev, created]);
      setShowAddForm(false);
      toast.success(`Added ${created.display_name}`);
    } catch (err) {
      toast.error(extractDetail(err, 'Failed to add marketplace source'));
    } finally {
      setCreating(false);
    }
  };

  const handleUpdate = async (
    values: SourceFormValues,
    options: { clear_token: boolean }
  ) => {
    if (!editingSource) return;
    setSavingEdit(true);
    try {
      const patch: MarketplaceSourceUpdate = {};
      if (values.display_name.trim() !== editingSource.display_name) {
        patch.display_name = values.display_name.trim();
      }
      const tokenInput = values.encrypted_token.trim();
      if (options.clear_token) {
        patch.clear_token = true;
      } else if (tokenInput) {
        patch.encrypted_token = tokenInput;
      }
      // Skip the API call entirely when nothing changed — avoids a no-op
      // PATCH that would still bump updated_at on the row.
      if (Object.keys(patch).length === 0) {
        setEditingId(null);
        return;
      }
      const updated = await marketplaceSourcesApi.update(editingSource.id, patch);
      setSources((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      setEditingId(null);
      toast.success(`Updated ${updated.display_name}`);
    } catch (err) {
      toast.error(extractDetail(err, 'Failed to update marketplace source'));
    } finally {
      setSavingEdit(false);
    }
  };

  const handleToggleActive = async (source: MarketplaceSourceResponse) => {
    const nextActive = !source.is_active;
    // Optimistic — flip immediately, roll back on failure.
    setSources((prev) =>
      prev.map((s) => (s.id === source.id ? { ...s, is_active: nextActive } : s))
    );
    setRowBusy({ id: source.id, action: 'toggle' });
    try {
      const updated = await marketplaceSourcesApi.update(source.id, {
        is_active: nextActive,
      });
      setSources((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
    } catch (err) {
      // Roll back the optimistic flip
      setSources((prev) =>
        prev.map((s) =>
          s.id === source.id ? { ...s, is_active: source.is_active } : s
        )
      );
      toast.error(extractDetail(err, 'Failed to update source'));
    } finally {
      setRowBusy(null);
    }
  };

  const handleTest = async (source: MarketplaceSourceResponse) => {
    setRowBusy({ id: source.id, action: 'test' });
    try {
      const result = await marketplaceSourcesApi.test(source.id);
      const pinNote = result.pinned_hub_id_changed ? ' (hub identity pinned)' : '';
      toast.success(
        `Connected to ${result.display_name ?? source.display_name}${pinNote} - ${result.capabilities.length} capability${result.capabilities.length === 1 ? '' : 'ies'}`
      );
      // Refresh the row from the server so capabilities/policies update too.
      void loadSources();
    } catch (err) {
      toast.error(extractDetail(err, 'Connection test failed'));
      void loadSources();
    } finally {
      setRowBusy(null);
    }
  };

  const handleSync = async (source: MarketplaceSourceResponse) => {
    setRowBusy({ id: source.id, action: 'sync' });
    try {
      const result = await marketplaceSourcesApi.sync(source.id);
      if (result.error) {
        toast.error(`Sync completed with errors: ${result.error}`);
      } else if (result.skipped_reason) {
        toast.success(`Sync skipped: ${result.skipped_reason}`);
      } else {
        const upserts = result.items_upserted;
        toast.success(
          `Synced ${source.display_name} - ${result.events_processed} event${result.events_processed === 1 ? '' : 's'} (${upserts} upsert${upserts === 1 ? '' : 's'})`
        );
      }
      void loadSources();
    } catch (err) {
      toast.error(extractDetail(err, 'Sync failed'));
    } finally {
      setRowBusy(null);
    }
  };

  const handleDelete = (source: MarketplaceSourceResponse) => {
    setConfirmDialog({
      isOpen: true,
      title: `Delete "${source.display_name}"`,
      message:
        'This source will be disabled and hidden from the marketplace dropdown. ' +
        'Items already installed from this source remain in your library, but new installs are blocked. ' +
        'You can re-enable the source by toggling it back on.',
      confirmText: 'Disable source',
      variant: 'danger',
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        setRowBusy({ id: source.id, action: 'delete' });
        try {
          await marketplaceSourcesApi.delete(source.id);
          // Soft-delete returns the row but flagged inactive. Reflect that
          // locally without a refetch — the include_inactive list call would
          // have returned it anyway.
          setSources((prev) =>
            prev.map((s) => (s.id === source.id ? { ...s, is_active: false } : s))
          );
          toast.success(`Disabled ${source.display_name}`);
        } catch (err) {
          toast.error(extractDetail(err, 'Failed to delete source'));
        } finally {
          setRowBusy(null);
        }
      },
    });
  };

  const handlePromote = (source: MarketplaceSourceResponse) => {
    setConfirmDialog({
      isOpen: true,
      title: `Promote "${source.display_name}" to admin_trusted`,
      message:
        'Admin-trusted sources skip the per-install confirmation prompt for MCP servers and Tesslate Apps. ' +
        'Only promote sources you have personally vetted — this affects every user who can see this source.',
      confirmText: 'Promote',
      variant: 'warning',
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        setRowBusy({ id: source.id, action: 'promote' });
        try {
          const updated = await marketplaceSourcesApi.promote(source.id, 'admin_trusted');
          setSources((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
          toast.success(`Promoted ${updated.display_name} to admin_trusted`);
        } catch (err) {
          toast.error(extractDetail(err, 'Failed to promote source'));
        } finally {
          setRowBusy(null);
        }
      },
    });
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading marketplace sources..." size={60} />
      </div>
    );
  }

  return (
    <>
      <SettingsSection
        title="Marketplace Sources"
        description="Add federated marketplace hubs to install agents, apps, themes, and connectors from beyond the Tesslate official catalog."
      >
        <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-xl">
          <div className="flex items-start gap-3">
            <ShieldCheck size={20} className="text-blue-400 mt-0.5 flex-shrink-0" />
            <div className="text-sm text-blue-400">
              <p className="font-semibold mb-1">Federated marketplaces</p>
              <p className="text-xs opacity-80">
                Sources you add appear as filter options in the Marketplace. The system rows
                (<code className="font-mono">tesslate-official</code> and{' '}
                <code className="font-mono">local</code>) are always visible and cannot be
                edited. Anonymous sources without a bearer token are classified as untrusted —
                MCP server and Tesslate App installs from untrusted sources are blocked by the
                install gate.
              </p>
            </div>
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-[var(--text)] flex items-center gap-2">
              <Cloud size={18} />
              Your sources ({sources.length})
            </h3>
            {!showAddForm && !editingId && (
              <button
                onClick={() => setShowAddForm(true)}
                className="btn btn-filled flex items-center gap-1.5"
                data-testid="add-marketplace-source"
              >
                <Plus size={14} weight="bold" />
                Add marketplace
              </button>
            )}
          </div>

          {showAddForm && (
            <SourceForm
              hasTeam={hasTeam}
              hasExistingToken={false}
              busy={creating}
              onSubmit={handleCreate}
              onCancel={() => setShowAddForm(false)}
            />
          )}

          {editingSource && (
            <SourceForm
              initial={{
                handle: editingSource.handle,
                display_name: editingSource.display_name,
                base_url: editingSource.base_url,
                encrypted_token: '',
                scope: editingSource.scope === 'team' ? 'team' : 'user',
                is_edit: true,
              }}
              hasTeam={hasTeam}
              hasExistingToken={editingSource.has_token}
              busy={savingEdit}
              onSubmit={handleUpdate}
              onCancel={() => setEditingId(null)}
            />
          )}

          {sources.length > 0 ? (
            <div className="space-y-3">
              {sources.map((source) => (
                <SourceRow
                  key={source.id}
                  source={source}
                  isSuperuser={isSuperuser}
                  busyAction={rowBusy?.id === source.id ? rowBusy.action : null}
                  onTest={handleTest}
                  onSync={handleSync}
                  onToggleActive={handleToggleActive}
                  onEdit={(s) => {
                    setEditingId(s.id);
                    setShowAddForm(false);
                  }}
                  onDelete={handleDelete}
                  onPromote={handlePromote}
                />
              ))}
            </div>
          ) : (
            <div className="text-center py-12">
              <div className="w-16 h-16 rounded-2xl bg-[var(--surface)] border border-[var(--border)] flex items-center justify-center mx-auto mb-4">
                <Cloud size={32} className="text-[var(--text-subtle)]" />
              </div>
              <h3 className="text-sm font-semibold text-[var(--text)] mb-2">
                No marketplace sources yet
              </h3>
              <p className="text-xs text-[var(--text-subtle)] mb-4 max-w-sm mx-auto">
                Add a federated marketplace hub to expand the catalog beyond Tesslate Official.
              </p>
              {!showAddForm && (
                <button
                  onClick={() => setShowAddForm(true)}
                  className="btn btn-filled flex items-center gap-1.5 mx-auto"
                >
                  <Plus size={14} weight="bold" />
                  Add your first source
                </button>
              )}
            </div>
          )}
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
