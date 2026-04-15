import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import { ArrowLeft, Play, Stop } from '@phosphor-icons/react';
import { useApps } from '../contexts/AppsContext';
import {
  appInstallsApi,
  appRuntimeApi,
  appRuntimeStatusApi,
  appVersionsApi,
  marketplaceAppsApi,
  appBillingApi,
  type AppInstance,
  type AppRuntimeStatus,
  type AppScheduleRow,
  type AppVersionDetail,
  type MarketplaceApp,
  type SessionHandle,
  type SpendSummary,
} from '../lib/api';
import WorkspaceSurface, { type Surface } from '../components/apps/WorkspaceSurface';

function parseSurfaces(manifest: AppVersionDetail['manifest_json']): Surface[] {
  if (!manifest) return [];
  const raw = (manifest as Record<string, unknown>).surfaces;
  if (!Array.isArray(raw)) return [];
  const out: Surface[] = [];
  for (const s of raw) {
    if (!s || typeof s !== 'object') continue;
    const rec = s as Record<string, unknown>;
    const kind = rec.kind;
    if (
      kind !== 'ui' &&
      kind !== 'chat' &&
      kind !== 'scheduled' &&
      kind !== 'triggered' &&
      kind !== 'mcp-tool'
    )
      continue;
    out.push({
      kind,
      entrypoint: typeof rec.entrypoint === 'string' ? rec.entrypoint : undefined,
      name: typeof rec.name === 'string' ? rec.name : undefined,
      description: typeof rec.description === 'string' ? rec.description : undefined,
    });
  }
  return out;
}

function formatRemaining(seconds: number): string {
  if (seconds <= 0) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function SpendSidebar({
  spendForThisApp,
  spend,
  otherSurfaces,
}: {
  spendForThisApp: number;
  spend: SpendSummary | null;
  otherSurfaces: Surface[];
}) {
  return (
    <aside className="hidden lg:flex flex-col w-80 border-l border-[var(--border)] bg-[var(--surface)] p-4 gap-4">
      <div>
        <div className="text-xs uppercase tracking-wide text-[var(--muted)] mb-2">
          Spend (this app)
        </div>
        <div className="text-2xl font-heading text-[var(--text)]">
          ${spendForThisApp.toFixed(4)}
        </div>
      </div>
      <div className="h-px bg-[var(--border)]" />
      <div>
        <div className="text-xs uppercase tracking-wide text-[var(--muted)] mb-2">Total spend</div>
        <dl className="text-sm space-y-1.5 text-[var(--text)]">
          {(
            [
              ['Last 24h', spend?.total_usd_24h ?? 0],
              ['Last 7d', spend?.total_usd_7d ?? 0],
              ['Last 30d', spend?.total_usd_30d ?? 0],
            ] as const
          ).map(([label, val]) => (
            <div key={label} className="flex justify-between">
              <dt className="text-[var(--muted)]">{label}</dt>
              <dd>${val.toFixed(4)}</dd>
            </div>
          ))}
        </dl>
      </div>
      {otherSurfaces.length > 0 && (
        <>
          <div className="h-px bg-[var(--border)]" />
          <div>
            <div className="text-xs uppercase tracking-wide text-[var(--muted)] mb-2">
              Other surfaces
            </div>
            <ul className="space-y-1 text-xs text-[var(--muted)]">
              {otherSurfaces.map((s, i) => (
                <li key={i}>
                  <span className="text-[var(--text)]">{s.name ?? s.kind}</span>
                  <span className="ml-2">({s.kind})</span>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </aside>
  );
}

const STARTING_STEPS = [
  'Provisioning',
  'Pulling image',
  'Installing deps',
  'Ready',
] as const;

function StartingStepper({
  appName,
  runtime,
}: {
  appName: string;
  runtime: AppRuntimeStatus | null;
}) {
  // Rough mapping from rollup state to the first "active" step index.
  // In "starting" with any non-stopped container, we are at least on step 2.
  const activeIdx = (() => {
    if (!runtime) return 0;
    if (runtime.state === 'running') return STARTING_STEPS.length - 1;
    const nonStopped = runtime.containers.filter((c) => c.status !== 'stopped');
    if (nonStopped.length === 0) return 0;
    if (nonStopped.some((c) => c.status === 'starting')) return 2;
    return 1;
  })();

  return (
    <div
      className="h-full flex flex-col items-center justify-center gap-6 p-8"
      data-testid="runtime-starting"
    >
      <div className="text-center">
        <div className="font-heading text-xl text-[var(--text)] mb-1">
          Starting {appName}…
        </div>
        <div className="text-sm text-[var(--muted)]">
          This usually takes under a minute.
        </div>
      </div>
      <ol className="flex items-center gap-3 text-xs">
        {STARTING_STEPS.map((label, i) => {
          const state =
            i < activeIdx ? 'done' : i === activeIdx ? 'active' : 'pending';
          return (
            <li
              key={label}
              className="flex items-center gap-2"
              data-step-state={state}
            >
              <span
                className={
                  'w-6 h-6 rounded-full flex items-center justify-center text-[10px] ' +
                  (state === 'done'
                    ? 'bg-[var(--primary)] text-white'
                    : state === 'active'
                      ? 'border border-[var(--primary)] text-[var(--primary)] animate-pulse'
                      : 'border border-[var(--border)] text-[var(--muted)]')
                }
              >
                {i + 1}
              </span>
              <span
                className={
                  state === 'pending'
                    ? 'text-[var(--muted)]'
                    : 'text-[var(--text)]'
                }
              >
                {label}
              </span>
              {i < STARTING_STEPS.length - 1 ? (
                <span className="w-6 h-px bg-[var(--border)]" />
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function SchedulesPanel({
  rows,
  loaded,
  onToggle,
  onRun,
}: {
  rows: AppScheduleRow[];
  loaded: boolean;
  onToggle: (r: AppScheduleRow) => void | Promise<void>;
  onRun: (r: AppScheduleRow) => void | Promise<void>;
}) {
  if (!loaded) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-[var(--muted)]">
        Loading schedules…
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div
        className="h-full flex items-center justify-center text-xs text-[var(--muted)]"
        data-testid="schedules-empty"
      >
        No schedules configured for this app.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2" data-testid="schedules-panel">
      {rows.map((r) => (
        <div
          key={r.id}
          className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3"
          data-testid={`schedule-row-${r.id}`}
        >
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-sm font-semibold text-[var(--text)] truncate">
              <span>{r.name}</span>
              <span className="text-[10px] uppercase tracking-wide text-[var(--muted)]">
                {r.trigger_kind}
              </span>
            </div>
            <div className="text-xs text-[var(--muted)]">
              {r.cron ?? '— no cron —'}
              {r.last_run_at ? (
                <>
                  {' • '}
                  last: {new Date(r.last_run_at).toLocaleString()}
                  {r.last_status ? ` (${r.last_status})` : ''}
                </>
              ) : null}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <label className="inline-flex items-center gap-1.5 text-xs text-[var(--muted)] cursor-pointer">
              <input
                type="checkbox"
                checked={r.enabled}
                onChange={() => void onToggle(r)}
                data-testid={`schedule-toggle-${r.id}`}
              />
              Enabled
            </label>
            <button
              onClick={() => void onRun(r)}
              className="px-2.5 py-1 rounded-md border border-[var(--border)] bg-[var(--surface-hover)] text-xs font-semibold text-[var(--text)] hover:bg-white/5 transition"
              data-testid={`schedule-run-${r.id}`}
            >
              Run now
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function AppWorkspacePage() {
  const { appInstanceId } = useParams<{ appInstanceId: string }>();
  const navigate = useNavigate();
  const { myInstalls } = useApps();

  const [instance, setInstance] = useState<AppInstance | null>(null);
  const [app, setApp] = useState<MarketplaceApp | null>(null);
  const [version, setVersion] = useState<AppVersionDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [session, setSession] = useState<SessionHandle | null>(null);
  const [sessionExpiresAt, setSessionExpiresAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [startingSession, setStartingSession] = useState(false);
  const [endingSession, setEndingSession] = useState(false);

  const [spend, setSpend] = useState<SpendSummary | null>(null);
  const tickRef = useRef<number | null>(null);

  // Runtime lifecycle state (pod start/stop for the underlying project).
  const [runtime, setRuntime] = useState<AppRuntimeStatus | null>(null);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [stoppingRuntime, setStoppingRuntime] = useState(false);

  // Schedules tab state.
  const [schedules, setSchedules] = useState<AppScheduleRow[]>([]);
  const [schedulesLoaded, setSchedulesLoaded] = useState(false);
  const [activeTab, setActiveTab] = useState<'surface' | 'schedules'>('surface');

  // Resolve instance: prefer context, fall back to a fresh fetch.
  useEffect(() => {
    if (!appInstanceId) return;
    const fromCtx = myInstalls.find((i) => i.id === appInstanceId) ?? null;
    if (fromCtx) {
      setInstance(fromCtx);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const env = await appInstallsApi.listMine({ limit: 200 });
        if (cancelled) return;
        const found = env.items.find((i) => i.id === appInstanceId) ?? null;
        if (!found) setLoadError('App install not found');
        setInstance(found);
      } catch {
        if (!cancelled) setLoadError('Failed to load app install');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [appInstanceId, myInstalls]);

  useEffect(() => {
    if (!instance) return;
    let cancelled = false;
    (async () => {
      try {
        const [a, v] = await Promise.all([
          marketplaceAppsApi.get(instance.app_id),
          appVersionsApi.get(instance.app_version_id),
        ]);
        if (cancelled) return;
        setApp(a);
        setVersion(v);
      } catch {
        if (!cancelled) setLoadError('Failed to load app manifest');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [instance]);

  const refreshSpend = useCallback(async () => {
    try {
      setSpend(await appBillingApi.getSpendSummary());
    } catch {
      /* non-fatal */
    }
  }, []);
  useEffect(() => {
    void refreshSpend();
  }, [refreshSpend, session?.session_id]);

  useEffect(() => {
    if (!sessionExpiresAt) return;
    tickRef.current = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      if (tickRef.current !== null) window.clearInterval(tickRef.current);
      tickRef.current = null;
    };
  }, [sessionExpiresAt]);

  const remainingSeconds = useMemo(() => {
    if (!sessionExpiresAt) return 0;
    return Math.max(0, Math.floor((sessionExpiresAt - now) / 1000));
  }, [sessionExpiresAt, now]);

  useEffect(() => {
    if (session && sessionExpiresAt && remainingSeconds === 0) {
      setSession(null);
      setSessionExpiresAt(null);
    }
  }, [remainingSeconds, session, sessionExpiresAt]);

  // Boot the runtime: GET status; if stopped, POST /start; then poll every
  // 2s (cap 90s) until running or error. Re-runs if appInstanceId changes.
  useEffect(() => {
    if (!instance) return;
    let cancelled = false;
    let timer: number | null = null;

    const finish = (final: AppRuntimeStatus) => {
      if (cancelled) return;
      setRuntime(final);
    };

    const poll = async (deadline: number) => {
      if (cancelled) return;
      try {
        const r = await appRuntimeStatusApi.getRuntime(instance.id);
        if (cancelled) return;
        setRuntime(r);
        if (r.state === 'running' || r.state === 'error') {
          finish(r);
          return;
        }
        if (Date.now() >= deadline) {
          setRuntimeError('Timed out waiting for app to start');
          return;
        }
        timer = window.setTimeout(() => void poll(deadline), 2000);
      } catch (e) {
        if (cancelled) return;
        setRuntimeError((e as Error).message || 'Failed to query runtime');
      }
    };

    (async () => {
      try {
        const initial = await appRuntimeStatusApi.getRuntime(instance.id);
        if (cancelled) return;
        setRuntime(initial);
        if (initial.state === 'running' || initial.state === 'error') {
          return;
        }
        if (initial.state === 'stopped') {
          try {
            const started = await appRuntimeStatusApi.start(instance.id);
            if (cancelled) return;
            setRuntime(started);
          } catch (e) {
            if (!cancelled) setRuntimeError((e as Error).message || 'Failed to start app');
            return;
          }
        }
        void poll(Date.now() + 90_000);
      } catch (e) {
        if (!cancelled) setRuntimeError((e as Error).message || 'Failed to query runtime');
      }
    })();

    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [instance]);

  const stopRuntime = async () => {
    if (!instance) return;
    setStoppingRuntime(true);
    try {
      const r = await appRuntimeStatusApi.stop(instance.id);
      setRuntime(r);
      toast.success('App stopped');
    } catch {
      toast.error('Failed to stop app');
    } finally {
      setStoppingRuntime(false);
    }
  };

  const surfaces = useMemo(() => (version ? parseSurfaces(version.manifest_json) : []), [version]);
  const primary = surfaces[0];
  const isHeadless = surfaces.length === 0;

  // Load schedules whenever instance changes.
  const refreshSchedules = useCallback(async () => {
    if (!instance) return;
    try {
      const rows = await appRuntimeStatusApi.listSchedules(instance.id);
      setSchedules(rows);
      setSchedulesLoaded(true);
    } catch {
      setSchedulesLoaded(true);
    }
  }, [instance]);
  useEffect(() => {
    void refreshSchedules();
  }, [refreshSchedules]);

  // For headless apps, default the tab to Schedules.
  useEffect(() => {
    if (isHeadless) setActiveTab('schedules');
  }, [isHeadless]);

  const toggleScheduleEnabled = async (row: AppScheduleRow) => {
    if (!instance) return;
    try {
      const updated = await appRuntimeStatusApi.patchSchedule(instance.id, row.id, {
        enabled: !row.enabled,
      });
      setSchedules((prev) => prev.map((s) => (s.id === row.id ? updated : s)));
    } catch {
      toast.error('Failed to update schedule');
    }
  };

  const runScheduleNow = async (row: AppScheduleRow) => {
    if (!instance) return;
    try {
      await appRuntimeStatusApi.runSchedule(instance.id, row.id, {});
      toast.success(`Queued "${row.name}"`);
    } catch {
      toast.error('Failed to queue schedule');
    }
  };

  // Resolve the effective iframe src. Legacy (2025-01) manifests may ship an
  // absolute URL as ``surfaces[0].entrypoint``; treat those as-is. Otherwise
  // it's a path rooted at the primary container URL.
  const effectiveEntrypoint = useMemo<string | undefined>(() => {
    const rawEntry = primary?.entrypoint;
    if (!rawEntry) {
      return runtime?.primary_url ?? undefined;
    }
    try {
      // If it parses as an absolute URL (has scheme + host), use as-is.
      const u = new URL(rawEntry);
      if (u.protocol && u.host) return rawEntry;
    } catch {
      /* not a URL — treat as path */
    }
    if (!runtime?.primary_url) return undefined;
    const base = runtime.primary_url.replace(/\/+$/, '');
    const path = rawEntry.startsWith('/') ? rawEntry : `/${rawEntry}`;
    return `${base}${path}`;
  }, [primary?.entrypoint, runtime?.primary_url]);

  const startSession = async () => {
    if (!instance) return;
    setStartingSession(true);
    try {
      const handle = await appRuntimeApi.createSession({
        app_instance_id: instance.id,
        budget_usd: 5,
        ttl_seconds: 60 * 30,
      });
      setSession(handle);
      setSessionExpiresAt(Date.now() + handle.ttl_seconds * 1000);
      toast.success('Session started');
    } catch {
      toast.error('Failed to start session');
    } finally {
      setStartingSession(false);
    }
  };

  const endSession = async () => {
    if (!session) return;
    setEndingSession(true);
    try {
      await appRuntimeApi.deleteSession(session.session_id);
      toast.success('Session ended');
    } catch {
      toast.error('Failed to end session');
    } finally {
      setSession(null);
      setSessionExpiresAt(null);
      setEndingSession(false);
      void refreshSpend();
    }
  };

  const spendForThisApp = useMemo(() => {
    if (!spend || !instance) return 0;
    const entry = spend.per_app.find((p) => p.app_instance_id === instance.id);
    return entry?.amount_usd ?? 0;
  }, [spend, instance]);

  if (loadError) {
    return (
      <div className="p-8" data-testid="workspace-error">
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {loadError}
        </div>
      </div>
    );
  }
  if (!instance || !app || !version) {
    return (
      <div className="p-8 text-sm text-[var(--muted)]" data-testid="workspace-loading">
        Loading app…
      </div>
    );
  }

  const sessionBadge = session
    ? `Active (${formatRemaining(remainingSeconds)})`
    : endingSession
      ? 'Settling'
      : 'No session';

  return (
    <div className="flex h-full min-h-0 w-full" data-testid="app-workspace-page">
      <div className="flex-1 flex flex-col min-w-0">
        <header className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)] bg-[var(--surface)]">
          <div className="flex items-center gap-3 min-w-0">
            <button
              onClick={() => navigate('/apps/installed')}
              className="p-1.5 rounded-md hover:bg-white/5 text-[var(--muted)]"
              aria-label="Back to installed apps"
            >
              <ArrowLeft className="w-4 h-4" />
            </button>
            <div className="min-w-0">
              <div className="font-heading text-lg font-semibold text-[var(--text)] truncate">
                {app.name}
              </div>
              <div className="text-xs text-[var(--muted)]">v{version.version}</div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span
              className="text-xs px-2.5 py-1 rounded-md border border-[var(--border)] bg-[var(--surface-hover)] text-[var(--muted)]"
              data-testid="runtime-state-badge"
            >
              {runtime ? runtime.state : 'starting'}
            </span>
            {runtime?.state === 'running' ? (
              <button
                onClick={stopRuntime}
                disabled={stoppingRuntime}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface-hover)] text-[var(--muted)] text-xs font-semibold hover:bg-white/5 disabled:opacity-50 transition"
                data-testid="stop-runtime-btn"
              >
                <Stop className="w-3.5 h-3.5" weight="fill" />
                Stop
              </button>
            ) : null}
            <span
              className="text-xs px-2.5 py-1 rounded-md border border-[var(--border)] bg-[var(--surface-hover)] text-[var(--muted)]"
              data-testid="session-badge"
            >
              {sessionBadge}
            </span>
            {session ? (
              <button
                onClick={endSession}
                disabled={endingSession}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-500/30 bg-red-500/10 text-red-300 text-xs font-semibold hover:bg-red-500/20 disabled:opacity-50 transition"
                data-testid="end-session-btn"
              >
                <Stop className="w-3.5 h-3.5" weight="fill" />
                End session
              </button>
            ) : (
              <button
                onClick={startSession}
                disabled={startingSession}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--primary)] text-white text-xs font-semibold hover:opacity-90 disabled:opacity-50 transition"
                data-testid="start-session-btn"
              >
                <Play className="w-3.5 h-3.5" weight="fill" />
                Start session
              </button>
            )}
          </div>
        </header>

        <nav
          className="flex gap-1 px-6 border-b border-[var(--border)] bg-[var(--surface)]"
          data-testid="workspace-tabs"
        >
          {!isHeadless && (
            <button
              onClick={() => setActiveTab('surface')}
              className={
                'px-3 py-2 text-xs font-semibold transition border-b-2 ' +
                (activeTab === 'surface'
                  ? 'border-[var(--primary)] text-[var(--text)]'
                  : 'border-transparent text-[var(--muted)] hover:text-[var(--text)]')
              }
              data-testid="tab-surface"
            >
              App
            </button>
          )}
          <button
            onClick={() => setActiveTab('schedules')}
            className={
              'px-3 py-2 text-xs font-semibold transition border-b-2 ' +
              (activeTab === 'schedules'
                ? 'border-[var(--primary)] text-[var(--text)]'
                : 'border-transparent text-[var(--muted)] hover:text-[var(--text)]')
            }
            data-testid="tab-schedules"
          >
            Schedules
            {schedules.length > 0 ? (
              <span className="ml-1.5 text-[10px] text-[var(--muted)]">
                ({schedules.length})
              </span>
            ) : null}
          </button>
        </nav>

        <main className="flex-1 min-h-0 p-4 overflow-hidden">
          {activeTab === 'schedules' ? (
            <SchedulesPanel
              rows={schedules}
              loaded={schedulesLoaded}
              onToggle={toggleScheduleEnabled}
              onRun={runScheduleNow}
            />
          ) : runtimeError || runtime?.state === 'error' ? (
            <div
              className="h-full flex items-center justify-center"
              data-testid="runtime-error"
            >
              <div className="max-w-md rounded-xl border border-red-500/30 bg-red-500/10 p-6 text-sm text-red-300">
                <div className="font-heading text-base mb-2 text-red-200">
                  App failed to start
                </div>
                <div className="mb-3">
                  {runtimeError ?? 'One or more containers failed to start.'}
                </div>
                {runtime?.project_slug ? (
                  <a
                    href={`/project/${runtime.project_slug}`}
                    className="underline"
                    target="_blank"
                    rel="noreferrer"
                  >
                    View logs →
                  </a>
                ) : null}
              </div>
            </div>
          ) : !runtime || runtime.state === 'stopped' || runtime.state === 'starting' ? (
            <StartingStepper appName={app.name} runtime={runtime} />
          ) : (
            <WorkspaceSurface
              surface={primary ? { ...primary, entrypoint: effectiveEntrypoint } : primary}
              appInstanceId={instance.id}
              sessionId={session?.session_id ?? null}
              apiKey={session?.api_key ?? null}
            />
          )}
        </main>
      </div>

      <SpendSidebar
        spendForThisApp={spendForThisApp}
        spend={spend}
        otherSurfaces={surfaces.slice(1)}
      />
    </div>
  );
}
