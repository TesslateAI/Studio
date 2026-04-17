import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import {
  ArrowClockwise,
  DotsThreeVertical,
  Package,
  Play,
  Plus,
  Stop,
} from '@phosphor-icons/react';
import { useApps } from '../contexts/AppsContext';
import { ConfirmDialog } from '../components/modals/ConfirmDialog';
import AppDetailsDrawer from '../components/apps/AppDetailsDrawer';
import { appRuntimeStatusApi, type AppInstance, type AppRuntimeStatus } from '../lib/api';

/**
 * MyAppsPage — /apps/installed
 *
 * Homescreen-style grid: each installed app renders as a rounded icon tile.
 * Click = open workspace. Hover/right-click reveals the per-app menu
 * (stop/restart/uninstall/details).
 */

const TRANSITIONAL_STATES = new Set([
  'installing',
  'uninstalling',
  'starting',
  'stopping',
  'creating',
]);

// Deterministic colour per app — stable hash on slug → one of N palette entries.
// Palette borrows iOS/macOS-style saturated gradients so tiles read as "app icons"
// rather than generic cards.
const TILE_PALETTE: Array<{ from: string; to: string }> = [
  { from: '#6366f1', to: '#8b5cf6' }, // indigo → violet
  { from: '#ec4899', to: '#f43f5e' }, // pink → rose
  { from: '#f59e0b', to: '#ef4444' }, // amber → red
  { from: '#10b981', to: '#06b6d4' }, // emerald → cyan
  { from: '#3b82f6', to: '#0ea5e9' }, // blue → sky
  { from: '#14b8a6', to: '#22c55e' }, // teal → green
  { from: '#8b5cf6', to: '#d946ef' }, // violet → fuchsia
  { from: '#f97316', to: '#eab308' }, // orange → yellow
];

function tileColor(seed: string): { from: string; to: string } {
  let h = 0;
  for (let i = 0; i < seed.length; i++) {
    h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  }
  return TILE_PALETTE[h % TILE_PALETTE.length];
}

function tileInitials(name: string): string {
  const cleaned = name.trim();
  if (!cleaned) return 'A';
  const words = cleaned.split(/\s+/).filter(Boolean);
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

/**
 * Subscribes to the app-runtime SSE stream for a single install. Returns the
 * latest RuntimeStatus snapshot (or null until first frame arrives).
 *
 * Reconnects with exponential backoff on error.
 */
function useRuntimeSse(instanceId: string | null): AppRuntimeStatus | null {
  const [runtime, setRuntime] = useState<AppRuntimeStatus | null>(null);

  useEffect(() => {
    if (!instanceId) return;
    let cancelled = false;
    let es: EventSource | null = null;
    let backoffTimer: number | null = null;
    let backoffMs = 1000;

    const open = () => {
      if (cancelled) return;
      try {
        const token = localStorage.getItem('token');
        const qs = token ? `?access_token=${encodeURIComponent(token)}` : '';
        es = new EventSource(`/api/app-installs/${instanceId}/events${qs}`, {
          withCredentials: true,
        });
      } catch {
        return;
      }
      es.onmessage = (ev) => {
        try {
          const payload = JSON.parse(ev.data);
          setRuntime(
            (prev) =>
              ({ ...(prev ?? ({} as AppRuntimeStatus)), ...payload }) as AppRuntimeStatus
          );
          backoffMs = 1000;
        } catch {
          /* ignore malformed */
        }
      };
      es.onerror = () => {
        if (cancelled) return;
        try {
          es?.close();
        } catch {
          /* noop */
        }
        es = null;
        const delay = backoffMs;
        backoffMs = Math.min(backoffMs * 2, 30_000);
        backoffTimer = window.setTimeout(open, delay);
      };
    };
    open();
    return () => {
      cancelled = true;
      if (backoffTimer !== null) window.clearTimeout(backoffTimer);
      try {
        es?.close();
      } catch {
        /* noop */
      }
    };
  }, [instanceId]);

  return runtime;
}

// Small coloured dot that sits on the corner of the tile.
function StatusDot({ state }: { state: string }) {
  const cls =
    state === 'running'
      ? 'bg-emerald-400 shadow-[0_0_0_2px_var(--bg),0_0_8px_2px_rgba(52,211,153,0.55)]'
      : state === 'starting' || state === 'stopping' || TRANSITIONAL_STATES.has(state)
        ? 'bg-amber-400 animate-pulse shadow-[0_0_0_2px_var(--bg)]'
        : state === 'error'
          ? 'bg-red-500 shadow-[0_0_0_2px_var(--bg)]'
          : state === 'job_only'
            ? 'bg-sky-400 shadow-[0_0_0_2px_var(--bg)]'
            : 'bg-transparent';
  if (!cls || cls === 'bg-transparent') return null;
  return (
    <span
      aria-hidden="true"
      className={`absolute top-1.5 right-1.5 h-2.5 w-2.5 rounded-full ${cls}`}
    />
  );
}

interface AppTileProps {
  install: AppInstance;
  onUninstall: (i: AppInstance) => void;
  onOpenDrawer: (i: AppInstance, runtime: AppRuntimeStatus | null) => void;
  onRuntimeChange: (id: string, runtime: AppRuntimeStatus | null) => void;
  openMenu: boolean;
  setOpenMenu: (open: boolean) => void;
}

function AppTile({
  install,
  onUninstall,
  onOpenDrawer,
  onRuntimeChange,
  openMenu,
  setOpenMenu,
}: AppTileProps) {
  const navigate = useNavigate();
  const runtime = useRuntimeSse(install.id);
  const [busy, setBusy] = useState<'starting' | 'stopping' | 'restarting' | null>(null);

  const onRuntimeChangeRef = useRef(onRuntimeChange);
  onRuntimeChangeRef.current = onRuntimeChange;
  useEffect(() => {
    onRuntimeChangeRef.current(install.id, runtime);
  }, [install.id, runtime]);

  const effectiveState = runtime?.state ?? install.state;
  const isJobOnly = effectiveState === 'job_only';
  const canOpen = install.state !== 'uninstalled' && !isJobOnly;
  const inFlight =
    busy !== null ||
    TRANSITIONAL_STATES.has(install.state) ||
    effectiveState === 'starting' ||
    effectiveState === 'stopping';

  const displayName = install.app_name ?? install.app_slug ?? 'Untitled App';
  const colorKey = install.app_slug ?? install.app_id ?? install.id;
  const { from, to } = tileColor(colorKey);

  const handleOpen = () => {
    if (!canOpen) {
      onOpenDrawer(install, runtime);
      return;
    }
    navigate(`/apps/installed/${install.id}/workspace`);
  };

  const handleStart = async () => {
    setBusy('starting');
    setOpenMenu(false);
    try {
      await appRuntimeStatusApi.start(install.id);
    } catch {
      toast.error('Failed to start app');
    } finally {
      setBusy(null);
    }
  };

  const handleStop = async () => {
    setBusy('stopping');
    setOpenMenu(false);
    try {
      await appRuntimeStatusApi.stop(install.id);
    } catch {
      toast.error('Failed to stop app');
    } finally {
      setBusy(null);
    }
  };

  const handleRestart = async () => {
    setBusy('restarting');
    setOpenMenu(false);
    try {
      await appRuntimeStatusApi.stop(install.id);
      await new Promise((r) => setTimeout(r, 500));
      await appRuntimeStatusApi.start(install.id);
      toast.success('Restarting app…');
    } catch {
      toast.error('Failed to restart app');
    } finally {
      setBusy(null);
    }
  };

  const running = effectiveState === 'running';

  return (
    <div
      className="group relative flex flex-col items-center gap-2 select-none"
      onContextMenu={(e) => {
        e.preventDefault();
        setOpenMenu(!openMenu);
      }}
    >
      {/* Icon tile */}
      <button
        onClick={handleOpen}
        disabled={install.state === 'uninstalled'}
        aria-label={`Open ${displayName}`}
        data-testid={`app-open-${install.id}`}
        className="relative h-20 w-20 md:h-[88px] md:w-[88px] rounded-[22px] flex items-center justify-center text-white font-heading font-semibold text-2xl md:text-[28px] tracking-tight overflow-hidden transition-transform duration-150 ease-out hover:scale-[1.04] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)] shadow-[0_6px_14px_rgba(0,0,0,0.25),inset_0_1px_0_rgba(255,255,255,0.18)] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
        style={{
          backgroundImage: `linear-gradient(145deg, ${from} 0%, ${to} 100%)`,
        }}
      >
        <span aria-hidden="true">{tileInitials(displayName)}</span>
        <StatusDot state={effectiveState} />
        {inFlight && (
          <span
            aria-hidden="true"
            className="absolute inset-0 flex items-center justify-center bg-black/30 backdrop-blur-[1px]"
          >
            <span className="h-5 w-5 rounded-full border-2 border-white/60 border-t-transparent animate-spin" />
          </span>
        )}
      </button>

      {/* Name */}
      <span
        className="max-w-[104px] text-center text-[12px] leading-tight text-[var(--text)] font-medium truncate"
        title={displayName}
      >
        {displayName}
      </span>

      {/* Kebab — visible on hover / when menu open */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpenMenu(!openMenu);
        }}
        className={`absolute top-0 right-0 p-1 rounded-full bg-black/50 text-white/90 backdrop-blur-sm transition-opacity ${
          openMenu ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus:opacity-100'
        }`}
        aria-label={`${displayName} menu`}
        data-testid={`app-menu-${install.id}`}
      >
        <DotsThreeVertical className="w-4 h-4" weight="bold" />
      </button>

      {openMenu && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpenMenu(false)} />
          <div
            className="absolute top-[22px] right-0 z-20 min-w-[160px] rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-lg py-1"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => {
                setOpenMenu(false);
                onOpenDrawer(install, runtime);
              }}
              className="w-full text-left px-3 py-2 text-xs text-[var(--text)] hover:bg-[var(--surface-hover)] transition"
            >
              Details
            </button>
            {!isJobOnly && (running ? (
              <>
                <button
                  onClick={handleStop}
                  disabled={inFlight && busy !== 'stopping'}
                  className="w-full text-left flex items-center gap-2 px-3 py-2 text-xs text-[var(--text)] hover:bg-[var(--surface-hover)] disabled:opacity-50 transition"
                  data-testid={`app-stop-${install.id}`}
                >
                  <Stop className="w-3 h-3" weight="fill" />
                  {busy === 'stopping' ? 'Stopping…' : 'Stop'}
                </button>
                <button
                  onClick={handleRestart}
                  disabled={inFlight && busy !== 'restarting'}
                  className="w-full text-left flex items-center gap-2 px-3 py-2 text-xs text-[var(--text)] hover:bg-[var(--surface-hover)] disabled:opacity-50 transition"
                  data-testid={`app-restart-${install.id}`}
                >
                  <ArrowClockwise className="w-3 h-3" weight="bold" />
                  {busy === 'restarting' ? 'Restarting…' : 'Restart'}
                </button>
              </>
            ) : (
              <button
                onClick={handleStart}
                disabled={inFlight}
                className="w-full text-left flex items-center gap-2 px-3 py-2 text-xs text-[var(--text)] hover:bg-[var(--surface-hover)] disabled:opacity-50 transition"
                data-testid={`app-start-${install.id}`}
              >
                <Play className="w-3 h-3" weight="fill" />
                {busy === 'starting' ? 'Starting…' : 'Start'}
              </button>
            ))}
            <div className="h-px bg-[var(--border)] my-1" />
            <button
              onClick={() => {
                setOpenMenu(false);
                onUninstall(install);
              }}
              className="w-full text-left px-3 py-2 text-xs text-red-400 hover:bg-red-500/10 transition"
            >
              Uninstall
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// "+" tile to jump to the marketplace.
function InstallTile({ onClick }: { onClick: () => void }) {
  return (
    <div className="flex flex-col items-center gap-2">
      <button
        onClick={onClick}
        aria-label="Browse marketplace"
        className="h-20 w-20 md:h-[88px] md:w-[88px] rounded-[22px] flex items-center justify-center border border-dashed border-[var(--border-hover)] bg-[var(--surface)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)]"
        data-testid="app-install-tile"
      >
        <Plus className="w-8 h-8" weight="bold" />
      </button>
      <span className="max-w-[104px] text-center text-[12px] leading-tight text-[var(--text-muted)] font-medium">
        Install
      </span>
    </div>
  );
}

export default function MyAppsPage() {
  const { myInstalls, isLoading, error, uninstallApp, refresh } = useApps();
  const navigate = useNavigate();

  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [confirmUninstall, setConfirmUninstall] = useState<AppInstance | null>(null);
  const [uninstalling, setUninstalling] = useState(false);
  const [drawerInstall, setDrawerInstall] = useState<AppInstance | null>(null);
  const [runtimeById, setRuntimeById] = useState<Record<string, AppRuntimeStatus | null>>({});

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

  const browse = () => navigate('/marketplace?type=app');

  const runningCount = useMemo(() => {
    if (visibleInstalls.length === 0) return 0;
    return visibleInstalls.filter((i) => {
      const rt = runtimeById[i.id];
      return (rt?.state ?? i.state) === 'running';
    }).length;
  }, [visibleInstalls, runtimeById]);

  return (
    <>
      {/* Title row — matches Dashboard (Workspaces) */}
      <div className="flex-shrink-0">
        <div
          className="h-10 flex items-center justify-between gap-[6px]"
          style={{
            paddingLeft: '18px',
            paddingRight: '4px',
            borderBottom: 'var(--border-width) solid var(--border)',
          }}
        >
          <h2 className="text-xs font-semibold text-[var(--text)] flex-1">My Apps</h2>
          <button
            onClick={browse}
            className="btn btn-icon"
            aria-label="Browse marketplace"
            data-testid="my-apps-browse"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>

        {/* Tab bar — single "All" pseudo-tab + install count meta */}
        <div
          className="h-10 flex items-center justify-between"
          style={{ paddingLeft: '7px', paddingRight: '10px' }}
        >
          <div className="flex items-center gap-1 flex-1 min-w-0">
            <button className="btn btn-tab-active">All apps</button>
            <span className="text-[11px] text-[var(--text-subtle)] ml-2 tabular-nums">
              {visibleInstalls.length} installed
              {runningCount > 0 ? ` · ${runningCount} running` : ''}
            </span>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto" data-testid="my-apps-page">
        {isLoading && visibleInstalls.length === 0 ? (
          <div className="p-8 text-sm text-[var(--text-muted)]" data-testid="my-apps-loading">
            Loading installed apps…
          </div>
        ) : error ? (
          <div className="p-8" data-testid="my-apps-error">
            <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4 text-sm text-[var(--status-error)]">
              {error}
            </div>
          </div>
        ) : visibleInstalls.length === 0 ? (
          <div
            className="flex flex-col items-center justify-center min-h-[60vh] px-6 text-center"
            data-testid="my-apps-empty"
          >
            <div className="h-16 w-16 rounded-[var(--radius)] bg-[var(--surface-hover)] border border-[var(--border)] flex items-center justify-center mb-4">
              <Package className="w-8 h-8 text-[var(--text-subtle)]" />
            </div>
            <h1 className="text-sm font-semibold text-[var(--text)] mb-2">
              No apps installed yet
            </h1>
            <p className="text-xs text-[var(--text-muted)] max-w-md mb-6">
              Install your first app from the marketplace. Apps run in a sandboxed session with
              their own budget and credentials.
            </p>
            <button onClick={browse} className="btn btn-filled">
              <Plus className="w-3 h-3" />
              Browse Marketplace
            </button>
          </div>
        ) : (
          <div className="px-6 md:px-8 pt-6 pb-10">
            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-7 2xl:grid-cols-8 gap-x-4 gap-y-6 md:gap-x-6 md:gap-y-8">
              {visibleInstalls.map((install) => (
                <AppTile
                  key={install.id}
                  install={install}
                  onUninstall={setConfirmUninstall}
                  onOpenDrawer={(i) => setDrawerInstall(i)}
                  onRuntimeChange={(id, rt) =>
                    setRuntimeById((prev) => (prev[id] === rt ? prev : { ...prev, [id]: rt }))
                  }
                  openMenu={openMenuId === install.id}
                  setOpenMenu={(open) => setOpenMenuId(open ? install.id : null)}
                />
              ))}
              <InstallTile onClick={browse} />
            </div>
          </div>
        )}
      </div>

      <AppDetailsDrawer
        install={drawerInstall}
        runtime={drawerInstall ? runtimeById[drawerInstall.id] ?? null : null}
        onClose={() => setDrawerInstall(null)}
      />

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
    </>
  );
}
