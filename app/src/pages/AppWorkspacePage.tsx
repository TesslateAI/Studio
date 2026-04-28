import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import {
  ArrowClockwise,
  ArrowLeft,
  ArrowSquareOut,
  Copy,
  Gear,
  Play,
  Stop,
  X,
  CaretDown,
} from '@phosphor-icons/react';
import { useApps } from '../contexts/AppsContext';
import {
  appActionsApi,
  appCompositionApi,
  appInstallsApi,
  appRuntimeApi,
  appRuntimeStatusApi,
  appVersionsApi,
  automationsApi,
  marketplaceAppsApi,
  appBillingApi,
  type AppActionRow,
  type AppCompositionLink,
  type AppInstance,
  type AppRuntimeStatus,
  type AppScheduleRow,
  type AppVersionDetail,
  type AutomationDefinitionSummary,
  type AutomationRunSummary,
  type MarketplaceApp,
  type SessionHandle,
  type SpendSummary,
} from '../lib/api';
import WorkspaceSurface, { type Surface } from '../components/apps/WorkspaceSurface';

/**
 * Phase 5 — drawer tab ids. Each maps to a lazy-loaded data source so
 * we never fetch what the user never opens.
 */
type DrawerTab =
  | 'schedules'
  | 'actions'
  | 'automations'
  | 'connections'
  | 'modules'
  | 'spend'
  | 'runs'
  | 'embed';

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

const STARTING_STEPS = ['Provisioning', 'Pulling image', 'Installing deps', 'Ready'] as const;

function StartingStepper({
  appName,
  runtime,
}: {
  appName: string;
  runtime: AppRuntimeStatus | null;
}) {
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
      className="h-full w-full flex flex-col items-center justify-center gap-6 p-8"
      data-testid="runtime-starting"
    >
      <div className="text-center">
        <div className="text-sm font-semibold text-[var(--text)]">Starting {appName}…</div>
        <div className="text-xs text-[var(--text-muted)] mt-1">
          Usually under a minute.
        </div>
      </div>
      <ol className="flex items-center gap-2 text-[11px]">
        {STARTING_STEPS.map((label, i) => {
          const state = i < activeIdx ? 'done' : i === activeIdx ? 'active' : 'pending';
          const dotClass =
            state === 'done'
              ? 'bg-[var(--status-success)]'
              : state === 'active'
                ? 'bg-[var(--primary)] animate-pulse'
                : 'bg-[var(--text-subtle)]';
          return (
            <li
              key={label}
              className="flex items-center gap-2"
              data-step-state={state}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${dotClass}`} />
              <span
                className={
                  state === 'pending' ? 'text-[var(--text-subtle)]' : 'text-[var(--text)]'
                }
              >
                {label}
              </span>
              {i < STARTING_STEPS.length - 1 ? (
                <span className="w-4 h-px bg-[var(--border)]" />
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function StatusPill({ state }: { state: string }) {
  const dot = (() => {
    switch (state) {
      case 'running':
        return 'bg-[var(--status-success)]';
      case 'starting':
        return 'bg-[var(--primary)] animate-pulse';
      case 'error':
        return 'bg-[var(--status-error)]';
      case 'job_only':
        return 'bg-[var(--text-muted)]';
      default:
        return 'bg-[var(--text-subtle)]';
    }
  })();
  const label = (() => {
    switch (state) {
      case 'running':
        return 'Running';
      case 'starting':
        return 'Starting';
      case 'stopped':
        return 'Stopped';
      case 'error':
        return 'Error';
      case 'job_only':
        return 'Schedule';
      default:
        return state;
    }
  })();
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[11px] text-[var(--text-muted)]"
      data-testid="runtime-state-badge"
    >
      <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
      {label}
    </span>
  );
}

const drawerCard =
  'bg-[var(--surface-hover)] rounded-[var(--radius)] border border-[var(--border)] overflow-hidden';

function DrawerSection({
  label,
  count,
  defaultExpanded = true,
  children,
}: {
  label: string;
  count?: number;
  defaultExpanded?: boolean;
  children: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  return (
    <div className={drawerCard}>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 px-4 py-2.5 hover:bg-[var(--surface-hover)] transition-colors group w-full"
      >
        <span className="text-[11px] font-medium text-[var(--text-muted)] group-hover:text-[var(--text)]">
          {label}
        </span>
        {typeof count === 'number' && count > 0 && (
          <span className="text-[10px] text-[var(--text-subtle)]">{count}</span>
        )}
        <span
          className={`ml-auto transition-transform duration-200 text-[var(--text-subtle)] ${
            expanded ? 'rotate-0' : '-rotate-90'
          }`}
        >
          <CaretDown size={10} />
        </span>
      </button>
      {expanded && <div className="px-4 pb-4 pt-1 space-y-3">{children}</div>}
    </div>
  );
}

function SchedulesList({
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
    return <div className="text-[11px] text-[var(--text-subtle)]">Loading…</div>;
  }
  if (rows.length === 0) {
    return (
      <div
        className="text-[11px] text-[var(--text-subtle)]"
        data-testid="schedules-empty"
      >
        None configured.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2" data-testid="schedules-panel">
      {rows.map((r) => (
        <div
          key={r.id}
          className="rounded-[var(--radius-medium)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5"
          data-testid={`schedule-row-${r.id}`}
        >
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold text-[var(--text)] truncate">{r.name}</span>
            <span className="text-[10px] text-[var(--text-subtle)] uppercase tracking-wide">
              {r.trigger_kind}
            </span>
          </div>
          <div className="font-mono text-[10px] text-[var(--text-muted)] mb-2">
            {r.cron ?? '—'}
            {r.last_run_at ? (
              <>
                {' • '}
                {new Date(r.last_run_at).toLocaleString()}
                {r.last_status ? ` (${r.last_status})` : ''}
              </>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <label className="inline-flex items-center gap-1.5 text-[11px] text-[var(--text-muted)] cursor-pointer">
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
              className="btn btn-sm"
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

function SpendList({
  spendForThisApp,
  spend,
}: {
  spendForThisApp: number;
  spend: SpendSummary | null;
}) {
  const rows: [string, number][] = [
    ['This app', spendForThisApp],
    ['All apps · 24h', spend?.total_usd_24h ?? 0],
    ['All apps · 7d', spend?.total_usd_7d ?? 0],
    ['All apps · 30d', spend?.total_usd_30d ?? 0],
  ];
  return (
    <div className="space-y-2">
      {rows.map(([label, val]) => (
        <div key={label} className="flex items-center justify-between text-xs">
          <span className="text-[var(--text-muted)]">{label}</span>
          <span className="font-mono text-[var(--text)]">${val.toFixed(4)}</span>
        </div>
      ))}
    </div>
  );
}

function SurfacesList({ surfaces }: { surfaces: Surface[] }) {
  if (surfaces.length === 0) {
    return <div className="text-[11px] text-[var(--text-subtle)]">None.</div>;
  }
  return (
    <ul className="space-y-1.5">
      {surfaces.map((s, i) => (
        <li key={i} className="text-xs">
          <span className="text-[var(--text)]">{s.name ?? s.kind}</span>
          <span className="ml-2 text-[var(--text-subtle)]">{s.kind}</span>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Phase 5 drawer tabs — Actions, Automations, Connections, Modules, Runs
// ---------------------------------------------------------------------------

const TAB_DEFS: { key: DrawerTab; label: string }[] = [
  { key: 'schedules', label: 'Schedules' },
  { key: 'actions', label: 'Actions' },
  { key: 'automations', label: 'Automations' },
  { key: 'connections', label: 'Connections' },
  { key: 'modules', label: 'Modules' },
  { key: 'spend', label: 'Spend' },
  { key: 'runs', label: 'Runs' },
  { key: 'embed', label: 'Embed' },
];

function DrawerTabBar({
  active,
  onChange,
}: {
  active: DrawerTab;
  onChange: (tab: DrawerTab) => void;
}) {
  return (
    <div
      className="flex items-center gap-1 px-3 py-2 border-b border-[var(--border)] overflow-x-auto"
      data-testid="drawer-tab-bar"
    >
      {TAB_DEFS.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`px-2 py-1 text-[11px] rounded-[var(--radius-small)] whitespace-nowrap ${
            active === t.key
              ? 'bg-[var(--surface-hover)] text-[var(--text)] font-medium'
              : 'text-[var(--text-muted)] hover:text-[var(--text)]'
          }`}
          data-testid={`drawer-tab-btn-${t.key}`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

function ActionsList({ actions }: { actions: AppActionRow[] | null }) {
  if (actions === null) {
    return <div className="text-[11px] text-[var(--text-subtle)]">Loading…</div>;
  }
  if (actions.length === 0) {
    return (
      <div className="text-[11px] text-[var(--text-subtle)]" data-testid="actions-empty">
        No actions declared in this app's manifest.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2" data-testid="actions-panel">
      {actions.map((a) => (
        <div
          key={a.id}
          className="rounded-[var(--radius-medium)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2"
          data-testid={`action-row-${a.name}`}
        >
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-[var(--text)] truncate">{a.name}</span>
            {a.timeout_seconds ? (
              <span className="text-[10px] text-[var(--text-subtle)]">
                timeout {a.timeout_seconds}s
              </span>
            ) : null}
          </div>
          <div className="text-[10px] text-[var(--text-subtle)] mt-1">
            {a.required_connectors.length > 0
              ? `connectors: ${a.required_connectors.join(', ')}`
              : 'no connectors'}
          </div>
        </div>
      ))}
    </div>
  );
}

function AutomationsList({
  automations,
}: {
  automations: AutomationDefinitionSummary[] | null;
}) {
  if (automations === null) {
    return <div className="text-[11px] text-[var(--text-subtle)]">Loading…</div>;
  }
  if (automations.length === 0) {
    return (
      <div
        className="text-[11px] text-[var(--text-subtle)]"
        data-testid="automations-empty"
      >
        No automations yet. Create one from the Automations page.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2" data-testid="automations-panel">
      {automations.map((a) => (
        <Link
          key={a.id}
          to={`/automations/${a.id}`}
          className="rounded-[var(--radius-medium)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2 hover:bg-[var(--surface-hover)] transition-colors"
          data-testid={`automation-row-${a.id}`}
        >
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-[var(--text)] truncate flex-1">
              {a.name}
            </span>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide ${
                a.is_active
                  ? 'bg-[var(--accent-subtle)] text-[var(--accent)]'
                  : 'bg-[var(--surface-hover)] text-[var(--text-subtle)]'
              }`}
            >
              {a.is_active ? 'active' : 'paused'}
            </span>
          </div>
          {a.paused_reason ? (
            <div className="text-[10px] text-[var(--text-subtle)] mt-1">
              {a.paused_reason}
            </div>
          ) : null}
        </Link>
      ))}
    </div>
  );
}

function ConnectionsList({
  manifest,
}: {
  manifest: AppVersionDetail['manifest_json'];
}) {
  const connectors = (() => {
    if (!manifest) return [] as Array<{
      id: string;
      kind: string;
      exposure: string;
    }>;
    const raw = (manifest as Record<string, unknown>).connectors;
    if (!Array.isArray(raw)) return [];
    return raw
      .filter((c) => c && typeof c === 'object')
      .map((c) => {
        const r = c as Record<string, unknown>;
        return {
          id: String(r.id ?? ''),
          kind: String(r.kind ?? ''),
          exposure: String(r.exposure ?? ''),
        };
      });
  })();

  if (connectors.length === 0) {
    return (
      <div
        className="text-[11px] text-[var(--text-subtle)]"
        data-testid="connections-empty"
      >
        No connectors declared in this app's manifest.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2" data-testid="connections-panel">
      {connectors.map((c) => (
        <div
          key={c.id}
          className="rounded-[var(--radius-medium)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2"
          data-testid={`connection-row-${c.id}`}
        >
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-[var(--text)]">{c.id}</span>
            <span className="text-[10px] text-[var(--text-subtle)] uppercase tracking-wide">
              {c.kind}
            </span>
            <span
              className={`ml-auto text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide ${
                c.exposure === 'env'
                  ? 'bg-amber-500/15 text-amber-600 border border-amber-500/30'
                  : 'bg-emerald-500/15 text-emerald-600'
              }`}
              title={
                c.exposure === 'env'
                  ? 'env: app process can read this secret directly'
                  : 'proxy: token never reaches the app pod'
              }
            >
              {c.exposure}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function ModulesList({ links }: { links: AppCompositionLink[] | null }) {
  if (links === null) {
    return <div className="text-[11px] text-[var(--text-subtle)]">Loading…</div>;
  }
  if (links.length === 0) {
    return (
      <div
        className="text-[11px] text-[var(--text-subtle)]"
        data-testid="modules-empty"
      >
        This app has no module dependencies.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2" data-testid="modules-panel">
      {links.map((l) => (
        <div
          key={`${l.alias}-${l.child_install_id}`}
          className="rounded-[var(--radius-medium)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2"
          data-testid={`module-row-${l.alias}`}
        >
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-[var(--text)]">{l.alias}</span>
            <span className="text-[10px] text-[var(--text-subtle)] truncate">
              → {l.child_app_name ?? l.child_app_slug ?? l.child_app_id}
            </span>
            {l.required ? (
              <span className="ml-auto text-[10px] text-[var(--accent)] uppercase tracking-wide">
                required
              </span>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function RunsList({ runs }: { runs: AutomationRunSummary[] | null }) {
  if (runs === null) {
    return <div className="text-[11px] text-[var(--text-subtle)]">Loading…</div>;
  }
  if (runs.length === 0) {
    return (
      <div
        className="text-[11px] text-[var(--text-subtle)]"
        data-testid="runs-empty"
      >
        No recent runs.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5" data-testid="runs-panel">
      {runs.map((r) => (
        <Link
          key={r.id}
          to={`/automations/${r.automation_id}/runs/${r.id}`}
          className="rounded-[var(--radius-medium)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2 hover:bg-[var(--surface-hover)] transition-colors"
          data-testid={`run-row-${r.id}`}
        >
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono text-[var(--text-subtle)]">
              {r.id.slice(0, 8)}
            </span>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide ${
                r.status === 'succeeded'
                  ? 'bg-emerald-500/15 text-emerald-600'
                  : r.status === 'failed' || r.status === 'expired'
                  ? 'bg-red-500/15 text-red-600'
                  : 'bg-[var(--surface-hover)] text-[var(--text-subtle)]'
              }`}
            >
              {r.status}
            </span>
            <span className="ml-auto text-[10px] font-mono text-[var(--text-muted)]">
              ${Number(r.spend_usd).toFixed(4)}
            </span>
          </div>
          <div className="text-[10px] text-[var(--text-subtle)] mt-1">
            {r.started_at
              ? new Date(r.started_at).toLocaleString()
              : new Date(r.created_at).toLocaleString()}
          </div>
        </Link>
      ))}
    </div>
  );
}

function EmbedShareBlock({ instanceId }: { instanceId: string }) {
  const embedUrl = `${window.location.origin}/apps/embed/${instanceId}`;
  return (
    <div className="space-y-2">
      <div className="text-[11px] text-[var(--text-muted)]">
        Public URL (requires signed-in session in the current origin):
      </div>
      <div className="flex items-center gap-2">
        <input
          readOnly
          value={embedUrl}
          className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-[11px] font-mono focus:outline-none focus:border-[var(--border-hover)]"
          onFocus={(e) => e.currentTarget.select()}
        />
        <button
          onClick={() => {
            void navigator.clipboard.writeText(embedUrl);
            toast.success('Embed URL copied');
          }}
          className="btn btn-icon btn-sm"
          aria-label="Copy embed URL"
        >
          <Copy size={12} />
        </button>
      </div>
      <div className="text-[10px] text-[var(--text-subtle)] leading-relaxed">
        Drop this URL into an <code className="font-mono">&lt;iframe&gt;</code> to embed the app.
        Cross-origin hosts need the Tesslate deployment to allowlist their origin
        (frame-ancestors CSP).
      </div>
    </div>
  );
}

export default function AppWorkspacePage() {
  const { appInstanceId } = useParams<{ appInstanceId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  // Embed mode: dedicated route `/apps/embed/:id` (lives outside DashboardLayout,
  // so no sidebar) OR `?embed=1` query param on the normal route (useful for
  // quick-preview without a route swap).
  const embedMode =
    location.pathname.startsWith('/apps/embed/') || searchParams.get('embed') === '1';
  const { myInstalls } = useApps();

  const [instance, setInstance] = useState<AppInstance | null>(null);
  const [app, setApp] = useState<MarketplaceApp | null>(null);
  const [version, setVersion] = useState<AppVersionDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [session, setSession] = useState<SessionHandle | null>(null);
  const sessionIdRef = useRef<string | null>(null);

  const [spend, setSpend] = useState<SpendSummary | null>(null);

  const [runtime, setRuntime] = useState<AppRuntimeStatus | null>(null);
  const runtimeRef = useRef<AppRuntimeStatus | null>(null);
  useEffect(() => {
    runtimeRef.current = runtime;
  }, [runtime]);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [stoppingRuntime, setStoppingRuntime] = useState(false);
  const [restarting, setRestarting] = useState(false);

  const [schedules, setSchedules] = useState<AppScheduleRow[]>([]);
  const [schedulesLoaded, setSchedulesLoaded] = useState(false);

  // Right-side settings drawer: closed by default. Persists per-session.
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Phase 5 — extended drawer tabs (UX surface #4): Actions ·
  // Automations · Connections · Modules · Spend · Runs.
  const [drawerTab, setDrawerTab] = useState<DrawerTab>('schedules');
  const [actions, setActions] = useState<AppActionRow[] | null>(null);
  const [automations, setAutomations] = useState<AutomationDefinitionSummary[] | null>(
    null
  );
  const [recentRuns, setRecentRuns] = useState<AutomationRunSummary[] | null>(null);
  const [moduleLinks, setModuleLinks] = useState<AppCompositionLink[] | null>(null);

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
    return () => {
      const sid = sessionIdRef.current;
      if (!sid) return;
      sessionIdRef.current = null;
      void appRuntimeApi.deleteSession(sid).catch(() => {});
    };
  }, []);

  useEffect(() => {
    if (!instance) return;
    let cancelled = false;
    let es: EventSource | null = null;
    let backoffTimer: number | null = null;
    let fallbackTimer: number | null = null;
    let backoffMs = 1000;
    let receivedAny = false;
    let startKicked = false;

    const maybeKickStart = (state: string | undefined) => {
      if (startKicked) return;
      if (state !== 'stopped') return;
      startKicked = true;
      void appRuntimeStatusApi.start(instance.id).catch((e) => {
        if (!cancelled) {
          setRuntimeError((e as Error).message || 'Failed to start app');
        }
      });
    };

    const handlePayload = (payload: Partial<AppRuntimeStatus> & { state?: string }) => {
      if (cancelled) return;
      receivedAny = true;
      setRuntime(
        (prev) => ({ ...(prev ?? ({} as AppRuntimeStatus)), ...payload }) as AppRuntimeStatus,
      );
      maybeKickStart(payload.state);
    };

    const open = () => {
      if (cancelled) return;
      try {
        const token = localStorage.getItem('token');
        const qs = token ? `?access_token=${encodeURIComponent(token)}` : '';
        es = new EventSource(`/api/app-installs/${instance.id}/events${qs}`, {
          withCredentials: true,
        });
      } catch (e) {
        setRuntimeError((e as Error).message || 'Failed to open runtime stream');
        return;
      }
      es.onmessage = (ev) => {
        try {
          const payload = JSON.parse(ev.data);
          handlePayload(payload);
          backoffMs = 1000;
        } catch {
          /* ignore malformed frame */
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

    fallbackTimer = window.setTimeout(() => {
      if (cancelled || receivedAny) return;
      void appRuntimeStatusApi
        .getRuntime(instance.id)
        .then((r) => {
          if (cancelled || receivedAny) return;
          setRuntime(r);
          maybeKickStart(r.state);
        })
        .catch((e) => {
          if (cancelled || receivedAny) return;
          setRuntimeError((e as Error).message || 'Failed to query runtime');
        });
    }, 2000);

    return () => {
      cancelled = true;
      if (backoffTimer !== null) window.clearTimeout(backoffTimer);
      if (fallbackTimer !== null) window.clearTimeout(fallbackTimer);
      try {
        es?.close();
      } catch {
        /* noop */
      }
    };
  }, [instance]);

  const stopRuntime = async () => {
    if (!instance) return;
    setStoppingRuntime(true);
    try {
      await endSessionSilent();
      const r = await appRuntimeStatusApi.stop(instance.id);
      setRuntime(r);
      toast.success('App stopped');
    } catch {
      toast.error('Failed to stop app');
    } finally {
      setStoppingRuntime(false);
    }
  };

  const restartRuntime = async () => {
    if (!instance) return;
    setRestarting(true);
    try {
      await endSessionSilent();
      await appRuntimeStatusApi.stop(instance.id);
      const deadline = Date.now() + 5000;
      while (Date.now() < deadline) {
        if (runtimeRef.current?.state === 'stopped') break;
        await new Promise((r) => setTimeout(r, 250));
      }
      const r = await appRuntimeStatusApi.start(instance.id);
      setRuntime(r);
      void beginSessionSilent();
      toast.success('Restarting app…');
    } catch {
      toast.error('Failed to restart app');
    } finally {
      setRestarting(false);
    }
  };

  const startRuntime = async () => {
    if (!instance) return;
    setRestarting(true);
    try {
      const r = await appRuntimeStatusApi.start(instance.id);
      setRuntime(r);
      void beginSessionSilent();
    } catch {
      toast.error('Failed to start app');
    } finally {
      setRestarting(false);
    }
  };

  const surfaces = useMemo(() => (version ? parseSurfaces(version.manifest_json) : []), [version]);
  const primary = surfaces[0];
  const manifestComputeModel = useMemo<string | null>(() => {
    if (!version?.manifest_json) return null;
    const compute = (version.manifest_json as Record<string, unknown>).compute;
    if (!compute || typeof compute !== 'object') return null;
    const model = (compute as Record<string, unknown>).model;
    return typeof model === 'string' ? model : null;
  }, [version]);
  const isJobOnly = runtime?.state === 'job_only' || manifestComputeModel === 'job-only';
  const isHeadless = surfaces.length === 0 || isJobOnly;

  // Phase 5 — lazy data loaders for the new drawer tabs. Each fires
  // once when its tab becomes active for the first time; the result is
  // cached in component state until the install changes.
  const refreshActions = useCallback(async () => {
    if (!instance) return;
    try {
      const data = await appActionsApi.list(instance.id);
      setActions(data.actions ?? []);
    } catch {
      setActions([]);
    }
  }, [instance]);
  const refreshAutomations = useCallback(async () => {
    if (!instance) return;
    try {
      const rows = await automationsApi.list({
        app_instance_id: instance.id,
        limit: 100,
      });
      setAutomations(rows);
    } catch {
      setAutomations([]);
    }
  }, [instance]);
  const refreshRuns = useCallback(async () => {
    if (!instance) return;
    try {
      const rows = await automationsApi.listRunsByInstall(instance.id, {
        limit: 25,
      });
      setRecentRuns(rows);
    } catch {
      setRecentRuns([]);
    }
  }, [instance]);
  const refreshModuleLinks = useCallback(async () => {
    if (!instance) return;
    const rows = await appCompositionApi.listLinks(instance.id);
    setModuleLinks(rows);
  }, [instance]);
  useEffect(() => {
    if (drawerTab === 'actions' && actions === null) void refreshActions();
    if (drawerTab === 'automations' && automations === null) void refreshAutomations();
    if (drawerTab === 'modules' && moduleLinks === null) void refreshModuleLinks();
    if (drawerTab === 'runs' && recentRuns === null) void refreshRuns();
  }, [
    drawerTab,
    actions,
    automations,
    recentRuns,
    moduleLinks,
    refreshActions,
    refreshAutomations,
    refreshRuns,
    refreshModuleLinks,
  ]);

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

  // For headless / job-only apps, open the drawer by default — the iframe
  // area is empty so the schedules tab is the only actionable surface.
  useEffect(() => {
    if (!version) return;
    if (isHeadless) setDrawerOpen(true);
  }, [version, isHeadless]);

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

  const effectiveEntrypoint = useMemo<string | undefined>(() => {
    const rawEntry = primary?.entrypoint;
    if (!rawEntry) return runtime?.primary_url ?? undefined;
    try {
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

  // Primary container id, resolved by matching `runtime.primary_url` against
  // the per-container URLs the orchestrator exposes. Used to drive the
  // health-check polling that gates iframe mount in WorkspaceSurface.
  // Falls back to the first container so single-container apps still work
  // when primary_url has trailing-slash / casing drift versus container.url.
  const primaryContainerId = useMemo<string | null>(() => {
    if (!runtime || runtime.containers.length === 0) return null;
    const norm = (u: string | null | undefined) =>
      (u ?? '').replace(/\/+$/, '').toLowerCase();
    const target = norm(runtime.primary_url);
    if (target) {
      const match = runtime.containers.find((c) => norm(c.url) === target);
      if (match) return match.id;
    }
    return runtime.containers[0]?.id ?? null;
  }, [runtime]);

  const beginSessionSilent = useCallback(async (): Promise<SessionHandle | null> => {
    if (!instance) return null;
    try {
      const handle = await appRuntimeApi.createSession({
        app_instance_id: instance.id,
        budget_usd: 5,
        ttl_seconds: 60 * 30,
      });
      setSession(handle);
      sessionIdRef.current = handle.session_id;
      return handle;
    } catch (e) {
      console.warn('session begin failed', e);
      return null;
    }
  }, [instance]);

  const endSessionSilent = useCallback(async () => {
    const sid = sessionIdRef.current;
    if (!sid) return;
    sessionIdRef.current = null;
    setSession(null);
    try {
      await appRuntimeApi.deleteSession(sid);
    } catch (e) {
      console.warn('session end failed', e);
    } finally {
      void refreshSpend();
    }
  }, [refreshSpend]);

  useEffect(() => {
    if (!instance || !version) return;
    if (sessionIdRef.current) return;
    if (isJobOnly) return;
    void beginSessionSilent();
  }, [instance, version, isJobOnly, beginSessionSilent]);

  const spendForThisApp = useMemo(() => {
    if (!spend || !instance) return 0;
    const entry = spend.per_app.find((p) => p.app_instance_id === instance.id);
    return entry?.amount_usd ?? 0;
  }, [spend, instance]);

  if (loadError) {
    return (
      <div className="p-6" data-testid="workspace-error">
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface-hover)] p-4 text-xs text-[var(--status-error)]">
          {loadError}
        </div>
      </div>
    );
  }
  if (!instance || !app || !version) {
    return (
      <div
        className="h-full w-full flex items-center justify-center text-xs text-[var(--text-muted)]"
        data-testid="workspace-loading"
      >
        Loading app…
      </div>
    );
  }

  const effectiveState = runtime?.state ?? 'starting';

  const renderStage = () => {
    if (runtimeError || runtime?.state === 'error') {
      return (
        <div
          className="h-full w-full flex items-center justify-center p-6"
          data-testid="runtime-error"
        >
          <div className={`${drawerCard} max-w-md w-full p-5`}>
            <div className="text-sm font-semibold text-[var(--text)] mb-2">
              App failed to start
            </div>
            <div className="text-xs text-[var(--text-muted)] mb-3">
              {runtimeError ?? 'One or more containers failed to start.'}
            </div>
            {runtime?.project_slug ? (
              <a
                href={`/project/${runtime.project_slug}`}
                className="text-xs text-[var(--primary)] hover:underline inline-flex items-center gap-1"
                target="_blank"
                rel="noreferrer"
              >
                View logs <ArrowSquareOut size={12} />
              </a>
            ) : null}
          </div>
        </div>
      );
    }
    if (isJobOnly) {
      return (
        <div
          className="h-full w-full flex items-center justify-center p-8"
          data-testid="runtime-job-only"
        >
          <div className={`${drawerCard} max-w-md w-full p-5`}>
            <div className="text-sm font-semibold text-[var(--text)] mb-1.5">
              Triggered by schedule
            </div>
            <div className="text-xs text-[var(--text-muted)]">
              No always-on surface. Use the settings panel to manage schedules or trigger a
              run.
            </div>
          </div>
        </div>
      );
    }
    if (!runtime || runtime.state === 'stopped' || runtime.state === 'starting') {
      return <StartingStepper appName={app.name} runtime={runtime} />;
    }
    return (
      <WorkspaceSurface
        surface={primary ? { ...primary, entrypoint: effectiveEntrypoint } : primary}
        appInstanceId={instance.id}
        sessionId={session?.session_id ?? null}
        apiKey={session?.api_key ?? null}
        appName={app.name}
        projectSlug={runtime?.project_slug ?? null}
        primaryContainerId={primaryContainerId}
      />
    );
  };

  // Embed mode: strip chrome, render only the surface. Still keeps session +
  // spend tracking silent in the background. A tiny status pill sits in the
  // corner so the embedding site can tell the app is alive.
  if (embedMode) {
    return (
      <div
        className="fixed inset-0 flex flex-col bg-[var(--bg)]"
        data-testid="app-workspace-embed"
      >
        <div className="flex-1 min-h-0 overflow-hidden">{renderStage()}</div>
        <div className="absolute top-2 right-2 pointer-events-none">
          <div className="inline-flex items-center gap-1.5 px-2 py-1 rounded-[var(--radius-small)] bg-[var(--surface-hover)]/90 backdrop-blur text-[10px] text-[var(--text-muted)] border border-[var(--border)]">
            <StatusPill state={effectiveState} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="relative flex flex-col h-full min-h-0 w-full"
      data-testid="app-workspace-page"
    >
      {/* Thin top bar — app identity + runtime controls + settings toggle. */}
      <div className="flex-shrink-0 flex items-center gap-2 px-3 py-2 border-b border-[var(--border)] bg-[var(--bg)]">
        <button
          onClick={() => navigate('/apps/installed')}
          className="btn btn-icon btn-sm"
          aria-label="Back to installed apps"
        >
          <ArrowLeft size={14} />
        </button>
        <div className="min-w-0 flex items-center gap-2">
          <span className="text-xs font-semibold text-[var(--text)] truncate">{app.name}</span>
          <span className="text-[10px] text-[var(--text-subtle)] font-mono">
            v{version.version}
          </span>
          <StatusPill state={effectiveState} />
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          {effectiveState === 'running' ? (
            <>
              <button
                onClick={stopRuntime}
                disabled={stoppingRuntime || restarting}
                className="btn btn-sm"
                data-testid="stop-runtime-btn"
              >
                <Stop size={12} weight="fill" />
                Stop
              </button>
              <button
                onClick={restartRuntime}
                disabled={stoppingRuntime || restarting}
                className="btn btn-sm"
                data-testid="restart-runtime-btn"
              >
                <ArrowClockwise size={12} weight="bold" />
                Restart
              </button>
            </>
          ) : effectiveState === 'stopped' || effectiveState === 'error' ? (
            <button
              onClick={startRuntime}
              disabled={restarting}
              className="btn btn-primary btn-sm"
              data-testid="start-runtime-btn"
            >
              <Play size={12} weight="fill" />
              {effectiveState === 'error' ? 'Retry' : 'Start'}
            </button>
          ) : null}
          {effectiveEntrypoint ? (
            <a
              href={effectiveEntrypoint}
              target="_blank"
              rel="noreferrer"
              className="btn btn-icon btn-sm"
              aria-label="Open app in new tab"
              title="Open in new tab"
            >
              <ArrowSquareOut size={12} />
            </a>
          ) : null}
          <button
            onClick={() => setDrawerOpen((v) => !v)}
            className={`btn btn-icon btn-sm ${drawerOpen ? 'btn-active' : ''}`}
            aria-label="App settings"
            data-testid="drawer-toggle-btn"
          >
            <Gear size={12} />
          </button>
        </div>
      </div>

      {/* Stage: iframe / stepper / error / empty — fills all remaining space. */}
      <div className="flex-1 min-h-0 flex relative">
        <div className="flex-1 min-w-0 min-h-0 overflow-hidden">{renderStage()}</div>

        {/* Settings drawer — slides in from the right. */}
        {drawerOpen && (
          <aside
            className="flex-shrink-0 w-[340px] border-l border-[var(--border)] bg-[var(--bg)] overflow-y-auto"
            data-testid="app-settings-drawer"
          >
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--border)] sticky top-0 bg-[var(--bg)] z-10">
              <span className="text-[11px] font-medium text-[var(--text-muted)] uppercase tracking-wide">
                Settings
              </span>
              <button
                onClick={() => setDrawerOpen(false)}
                className="btn btn-icon btn-sm"
                aria-label="Close settings"
              >
                <X size={12} />
              </button>
            </div>
            <DrawerTabBar active={drawerTab} onChange={setDrawerTab} />
            <div className="p-3 space-y-2" data-testid={`drawer-tab-${drawerTab}`}>
              {drawerTab === 'schedules' && (
                <DrawerSection label="Schedules" count={schedules.length}>
                  <SchedulesList
                    rows={schedules}
                    loaded={schedulesLoaded}
                    onToggle={toggleScheduleEnabled}
                    onRun={runScheduleNow}
                  />
                </DrawerSection>
              )}
              {drawerTab === 'actions' && (
                <DrawerSection label="Actions" count={actions?.length ?? 0}>
                  <ActionsList actions={actions} />
                </DrawerSection>
              )}
              {drawerTab === 'automations' && (
                <DrawerSection label="Automations" count={automations?.length ?? 0}>
                  <AutomationsList automations={automations} />
                </DrawerSection>
              )}
              {drawerTab === 'connections' && (
                <DrawerSection label="Connections">
                  <ConnectionsList manifest={version?.manifest_json ?? null} />
                </DrawerSection>
              )}
              {drawerTab === 'modules' && (
                <DrawerSection label="Modules" count={moduleLinks?.length ?? 0}>
                  <ModulesList links={moduleLinks} />
                </DrawerSection>
              )}
              {drawerTab === 'spend' && (
                <DrawerSection label="Spend">
                  <SpendList spendForThisApp={spendForThisApp} spend={spend} />
                </DrawerSection>
              )}
              {drawerTab === 'runs' && (
                <DrawerSection label="Recent runs" count={recentRuns?.length ?? 0}>
                  <RunsList runs={recentRuns} />
                </DrawerSection>
              )}
              {drawerTab === 'embed' && (
                <DrawerSection label="Embed" defaultExpanded>
                  <EmbedShareBlock instanceId={instance.id} />
                </DrawerSection>
              )}
              {surfaces.length > 1 && drawerTab === 'schedules' && (
                <DrawerSection label="Other surfaces" defaultExpanded={false}>
                  <SurfacesList surfaces={surfaces.slice(1)} />
                </DrawerSection>
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
