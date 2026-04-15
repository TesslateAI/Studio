import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { DotsThreeVertical, Package, Plus } from '@phosphor-icons/react';
import { useApps } from '../contexts/AppsContext';
import { CardSurface } from '../components/cards/CardSurface';
import { ConfirmDialog } from '../components/modals/ConfirmDialog';
import type { AppInstance } from '../lib/api';

/**
 * MyAppsPage — /apps/installed
 *
 * Grid of the caller's installed apps. Each card opens into AppWorkspacePage.
 */
function StateBadge({ state }: { state: AppInstance['state'] }) {
  const tone =
    state === 'running' || state === 'installed'
      ? 'bg-green-500/15 text-green-400 border-green-500/30'
      : state === 'stopped'
        ? 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30'
        : state === 'uninstalled'
          ? 'bg-white/5 text-gray-400 border-white/10'
          : 'bg-blue-500/15 text-blue-400 border-blue-500/30';
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-md border text-[10px] font-medium uppercase tracking-wide ${tone}`}
    >
      {state}
    </span>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return '—';
  }
}

export default function MyAppsPage() {
  const { myInstalls, isLoading, error, uninstallApp, refresh } = useApps();
  const navigate = useNavigate();

  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [confirmUninstall, setConfirmUninstall] = useState<AppInstance | null>(null);
  const [uninstalling, setUninstalling] = useState(false);

  const visibleInstalls = useMemo(
    () => myInstalls.filter((i) => i.state !== 'uninstalled'),
    [myInstalls]
  );

  const handleUninstallConfirmed = async () => {
    if (!confirmUninstall) return;
    setUninstalling(true);
    try {
      await uninstallApp(confirmUninstall.id);
      toast.success(`Uninstalled ${confirmUninstall.app_name ?? 'app'}`);
      setConfirmUninstall(null);
      await refresh();
    } catch {
      toast.error('Failed to uninstall app');
    } finally {
      setUninstalling(false);
    }
  };

  if (isLoading && visibleInstalls.length === 0) {
    return (
      <div className="p-8 text-sm text-[var(--muted)]" data-testid="my-apps-loading">
        Loading installed apps…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8" data-testid="my-apps-error">
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {error}
        </div>
      </div>
    );
  }

  if (visibleInstalls.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center min-h-[60vh] px-6 text-center"
        data-testid="my-apps-empty"
      >
        <div className="h-16 w-16 rounded-2xl bg-[var(--surface-hover)] border border-[var(--border)] flex items-center justify-center mb-4">
          <Package className="w-8 h-8 text-[var(--muted)]" />
        </div>
        <h1 className="font-heading text-2xl font-semibold text-[var(--text)] mb-2">
          No apps installed yet
        </h1>
        <p className="text-sm text-[var(--muted)] max-w-md mb-6">
          Browse the marketplace to install your first Tesslate App. Apps run in a sandboxed
          session with their own budget and credentials.
        </p>
        <button
          onClick={() => navigate('/apps')}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[var(--primary)] text-white text-sm font-semibold hover:opacity-90 transition"
        >
          <Plus className="w-4 h-4" />
          Browse Marketplace
        </button>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8" data-testid="my-apps-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-heading text-2xl font-semibold text-[var(--text)]">My Apps</h1>
          <p className="text-sm text-[var(--muted)] mt-1">
            {visibleInstalls.length} installed app{visibleInstalls.length === 1 ? '' : 's'}
          </p>
        </div>
        <button
          onClick={() => navigate('/apps')}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--surface-hover)] text-sm hover:border-[var(--primary)] transition"
        >
          <Plus className="w-4 h-4" />
          Browse
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {visibleInstalls.map((install) => (
          <CardSurface key={install.id} variant="standard" disableHoverLift>
            <div className="flex items-start justify-between mb-3">
              <div className="flex-1 min-w-0">
                <div className="font-heading text-lg font-semibold text-[var(--text)] truncate">
                  {install.app_name ?? install.app_slug ?? 'Untitled App'}
                </div>
                <div className="text-xs text-[var(--muted)] mt-0.5">
                  v{install.app_version ?? '—'} · installed {formatDate(install.installed_at)}
                </div>
              </div>
              <div className="relative">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setOpenMenuId(openMenuId === install.id ? null : install.id);
                  }}
                  className="p-1 rounded-md hover:bg-white/5 text-[var(--muted)]"
                  aria-label="Open app menu"
                  data-testid={`app-menu-${install.id}`}
                >
                  <DotsThreeVertical className="w-5 h-5" weight="bold" />
                </button>
                {openMenuId === install.id && (
                  <div
                    className="absolute right-0 top-full mt-1 min-w-[160px] rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-lg z-10 py-1"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      onClick={() => {
                        setOpenMenuId(null);
                        setConfirmUninstall(install);
                      }}
                      className="w-full text-left px-3 py-2 text-sm text-red-400 hover:bg-red-500/10 transition"
                    >
                      Uninstall
                    </button>
                  </div>
                )}
              </div>
            </div>
            <div className="flex items-center justify-between mt-auto pt-2">
              <StateBadge state={install.state} />
              <button
                onClick={() => navigate(`/apps/installed/${install.id}/workspace`)}
                disabled={install.state === 'uninstalled'}
                className="px-3 py-1.5 rounded-lg bg-[var(--primary)] text-white text-xs font-semibold hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition"
                data-testid={`app-open-${install.id}`}
              >
                Open
              </button>
            </div>
          </CardSurface>
        ))}
      </div>

      <ConfirmDialog
        isOpen={confirmUninstall !== null}
        onClose={() => (!uninstalling ? setConfirmUninstall(null) : undefined)}
        onConfirm={handleUninstallConfirmed}
        title="Uninstall app?"
        message={
          <span>
            Uninstall <strong>{confirmUninstall?.app_name ?? 'this app'}</strong>? Active sessions
            will be ended and associated data will be cleaned up.
          </span>
        }
        confirmText="Uninstall"
        variant="danger"
        isLoading={uninstalling}
      />
    </div>
  );
}
