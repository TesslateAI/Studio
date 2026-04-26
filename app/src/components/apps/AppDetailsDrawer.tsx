import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { X } from '@phosphor-icons/react';
import {
  appInstallsApi,
  createLogStreamWebSocket,
  type AppInstance,
  type AppInstanceDetail,
  type AppRuntimeStatus,
} from '../../lib/api';

type TabKey = 'overview' | 'containers' | 'schedules' | 'logs';

interface Props {
  install: AppInstance | null;
  runtime: AppRuntimeStatus | null;
  onClose: () => void;
}

interface LogContainer {
  id: string;
  name: string;
  status: string;
  type: string;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return '—';
  }
}

/**
 * Right-side drawer for managing an installed app: overview metadata,
 * per-container status, schedules, and live container logs (via the existing
 * project /logs/stream WebSocket — apps are projects with project_kind='app_runtime').
 */
export default function AppDetailsDrawer({ install, runtime, onClose }: Props) {
  const [tab, setTab] = useState<TabKey>('overview');
  const [detail, setDetail] = useState<AppInstanceDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const open = install !== null;

  // Load detail whenever the drawer opens for a new install.
  useEffect(() => {
    if (!install) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    appInstallsApi
      .getDetail(install.id)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message ?? 'Failed to load app details');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [install]);

  // Reset tab when the drawer changes target.
  useEffect(() => {
    setTab('overview');
  }, [install?.id]);

  // Live status overlay from SSE runtime stream: prefer runtime container
  // statuses over the snapshot stored in detail, since SSE is the source of
  // truth between detail refreshes.
  const containers = useMemo(() => {
    const base = detail?.containers ?? [];
    if (!runtime?.containers?.length) return base;
    const liveById = new Map(runtime.containers.map((c) => [c.id, c]));
    return base.map((c) => ({ ...c, status: liveById.get(c.id)?.status ?? c.status }));
  }, [detail, runtime]);

  if (!open || !install) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
        data-testid="app-drawer-backdrop"
      />
      {/* Drawer */}
      <aside
        className="fixed right-0 top-0 bottom-0 w-full max-w-[640px] bg-[var(--surface)] border-l border-[var(--border)] z-50 flex flex-col shadow-2xl"
        data-testid="app-details-drawer"
        role="dialog"
        aria-label="App details"
      >
        <header className="flex items-start justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="min-w-0">
            <div className="font-heading text-lg font-semibold text-[var(--text)] truncate">
              {install.app_name ?? install.app_slug ?? 'Untitled App'}
            </div>
            <div className="text-xs text-[var(--muted)] mt-0.5">
              v{install.app_version ?? '—'} · {install.state}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md hover:bg-white/5 text-[var(--muted)]"
            aria-label="Close drawer"
            data-testid="app-drawer-close"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        <nav className="flex gap-1 px-5 border-b border-[var(--border)]">
          {(
            [
              ['overview', 'Overview'],
              ['containers', `Containers${containers.length ? ` (${containers.length})` : ''}`],
              ['schedules', `Schedules${detail?.schedules.length ? ` (${detail.schedules.length})` : ''}`],
              ['logs', 'Logs'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key as TabKey)}
              className={
                'px-3 py-2 text-xs font-semibold transition border-b-2 ' +
                (tab === key
                  ? 'border-[var(--primary)] text-[var(--text)]'
                  : 'border-transparent text-[var(--muted)] hover:text-[var(--text)]')
              }
              data-testid={`drawer-tab-${key}`}
            >
              {label}
            </button>
          ))}
        </nav>

        <div className="flex-1 min-h-0 overflow-y-auto p-5">
          {loading && !detail ? (
            <div className="text-sm text-[var(--muted)]">Loading details…</div>
          ) : error ? (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
              {error}
            </div>
          ) : tab === 'overview' ? (
            <OverviewTab install={install} detail={detail} containerCount={containers.length} />
          ) : tab === 'containers' ? (
            <ContainersTab containers={containers} primaryId={detail?.primary_container_id ?? null} />
          ) : tab === 'schedules' ? (
            <SchedulesTab rows={detail?.schedules ?? []} />
          ) : (
            <LogsTab projectSlug={detail?.project_slug ?? runtime?.project_slug ?? null} />
          )}
        </div>
      </aside>
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 border-b border-[var(--border)] last:border-0">
      <dt className="text-xs uppercase tracking-wide text-[var(--muted)] flex-shrink-0 pt-0.5">
        {label}
      </dt>
      <dd className="text-sm text-[var(--text)] text-right break-all min-w-0">{children}</dd>
    </div>
  );
}

function OverviewTab({
  install,
  detail,
  containerCount,
}: {
  install: AppInstance;
  detail: AppInstanceDetail | null;
  containerCount: number;
}) {
  const primary = detail?.containers.find((c) => c.id === detail.primary_container_id) ?? null;
  return (
    <dl data-testid="drawer-overview">
      <Field label="Instance ID">
        <code className="text-[11px]">{install.id}</code>
      </Field>
      <Field label="App version">v{install.app_version ?? '—'}</Field>
      <Field label="Installed">{formatDate(install.installed_at)}</Field>
      <Field label="Update policy">{install.update_policy}</Field>
      <Field label="Compute model">{detail?.compute_model ?? 'always-on'}</Field>
      <Field label="Primary container">{primary?.name ?? '—'}</Field>
      <Field label="Containers">{containerCount}</Field>
      <Field label="Volume">
        {install.volume_id ? <code className="text-[11px]">{install.volume_id}</code> : '—'}
      </Field>
      <Field label="Project slug">
        {detail?.project_slug ? <code className="text-[11px]">{detail.project_slug}</code> : '—'}
      </Field>
    </dl>
  );
}

function StatusDot({ status }: { status: string }) {
  const tone =
    status === 'running'
      ? 'bg-green-500'
      : status === 'starting' || status === 'creating'
        ? 'bg-blue-500 animate-pulse'
        : status === 'failed' || status === 'error'
          ? 'bg-red-500'
          : 'bg-gray-500';
  return <span className={`inline-block w-2 h-2 rounded-full ${tone}`} />;
}

function ContainersTab({
  containers,
  primaryId,
}: {
  containers: AppInstanceDetail['containers'];
  primaryId: string | null;
}) {
  if (containers.length === 0) {
    return <div className="text-sm text-[var(--muted)]">No containers configured.</div>;
  }
  return (
    <div className="flex flex-col gap-3" data-testid="drawer-containers">
      {containers.map((c) => (
        <div
          key={c.id}
          className="rounded-lg border border-[var(--border)] bg-[var(--surface-hover)] p-3"
          data-testid={`drawer-container-${c.id}`}
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2 min-w-0">
              <StatusDot status={c.status} />
              <span className="font-semibold text-sm text-[var(--text)] truncate">{c.name}</span>
              {c.id === primaryId ? (
                <span className="text-[10px] uppercase px-1.5 py-0.5 rounded border border-[var(--primary)]/40 text-[var(--primary)]">
                  Primary
                </span>
              ) : null}
              <span className="text-[10px] uppercase text-[var(--muted)]">{c.kind}</span>
            </div>
            <span className="text-[11px] text-[var(--muted)]">{c.status}</span>
          </div>
          <dl className="text-xs text-[var(--muted)] grid grid-cols-[80px_1fr] gap-y-1 gap-x-3">
            {c.image ? (
              <>
                <dt>Image</dt>
                <dd className="text-[var(--text)] break-all">
                  <code>{c.image}</code>
                </dd>
              </>
            ) : null}
            {c.port != null ? (
              <>
                <dt>Port</dt>
                <dd className="text-[var(--text)]">{c.port}</dd>
              </>
            ) : null}
            {c.directory ? (
              <>
                <dt>Dir</dt>
                <dd className="text-[var(--text)] break-all">{c.directory}</dd>
              </>
            ) : null}
          </dl>
          {c.connections.length > 0 ? (
            <div className="mt-2 pt-2 border-t border-[var(--border)]">
              <div className="text-[10px] uppercase text-[var(--muted)] mb-1">Connections</div>
              <ul className="text-xs space-y-0.5">
                {c.connections.map((cn, i) => (
                  <li key={i} className="text-[var(--text)]">
                    <span className="text-[var(--muted)]">{cn.source}</span>
                    <span className="mx-1.5">→</span>
                    <span>{cn.target}</span>
                    {cn.connector_type ? (
                      <span className="ml-2 text-[10px] text-[var(--muted)]">
                        ({cn.connector_type})
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function SchedulesTab({ rows }: { rows: AppInstanceDetail['schedules'] }) {
  if (rows.length === 0) {
    return (
      <div className="text-sm text-[var(--muted)]" data-testid="drawer-schedules-empty">
        No schedules configured.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2" data-testid="drawer-schedules">
      {rows.map((s) => (
        <div
          key={s.id}
          className="rounded-lg border border-[var(--border)] bg-[var(--surface-hover)] p-3"
        >
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold text-[var(--text)]">{s.name}</div>
            <span
              className={
                'text-[10px] uppercase tracking-wide ' +
                (s.is_active ? 'text-green-400' : 'text-[var(--muted)]')
              }
            >
              {s.is_active ? 'Active' : 'Paused'}
            </span>
          </div>
          <div className="text-xs text-[var(--muted)] mt-1">
            {s.trigger_kind}
            {s.cron_expression ? ` · ${s.cron_expression}` : ''}
          </div>
          <div className="text-[11px] text-[var(--muted)] mt-1">
            Next: {formatDate(s.next_run_at)} · Last: {formatDate(s.last_run_at)}
          </div>
        </div>
      ))}
    </div>
  );
}

function LogsTab({ projectSlug }: { projectSlug: string | null }) {
  const [containers, setContainers] = useState<LogContainer[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [connState, setConnState] = useState<'connecting' | 'open' | 'closed' | 'error'>(
    'connecting'
  );
  const wsRef = useRef<WebSocket | null>(null);
  const linesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!projectSlug) {
      setConnState('error');
      return;
    }
    setConnState('connecting');
    setLines([]);
    const ws = createLogStreamWebSocket(projectSlug);
    wsRef.current = ws;
    ws.onopen = () => setConnState('open');
    ws.onerror = () => setConnState('error');
    ws.onclose = () => setConnState('closed');
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'containers' && Array.isArray(msg.data)) {
          setContainers(msg.data as LogContainer[]);
        } else if (msg.type === 'log' && typeof msg.data === 'string') {
          setLines((prev) => {
            const next = [...prev, msg.data];
            // Cap buffer to keep memory bounded.
            return next.length > 2000 ? next.slice(-2000) : next;
          });
        }
      } catch {
        /* ignore malformed */
      }
    };
    return () => {
      try {
        ws.close();
      } catch {
        /* noop */
      }
      wsRef.current = null;
    };
  }, [projectSlug]);

  // Auto-scroll to bottom on new lines.
  useEffect(() => {
    linesEndRef.current?.scrollIntoView({ behavior: 'auto' });
  }, [lines]);

  const switchContainer = useCallback((id: string) => {
    setSelected(id);
    setLines([]);
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'switch_container', container_id: id }));
    }
  }, []);

  if (!projectSlug) {
    return (
      <div className="text-sm text-[var(--muted)]">
        No underlying project — start the app to view logs.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 h-full min-h-[300px]" data-testid="drawer-logs">
      <div className="flex items-center gap-2">
        <label className="text-xs text-[var(--muted)]">Container</label>
        <select
          value={selected ?? ''}
          onChange={(e) => switchContainer(e.target.value)}
          className="flex-1 px-2 py-1 rounded-md border border-[var(--border)] bg-[var(--surface-hover)] text-xs text-[var(--text)]"
          data-testid="logs-container-select"
        >
          <option value="" disabled>
            {containers.length === 0 ? 'Loading…' : 'Pick a container'}
          </option>
          {containers.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.status})
            </option>
          ))}
        </select>
        <span
          className={
            'text-[10px] uppercase ' +
            (connState === 'open'
              ? 'text-green-400'
              : connState === 'connecting'
                ? 'text-blue-400'
                : 'text-red-400')
          }
        >
          {connState}
        </span>
      </div>
      <pre
        className="flex-1 min-h-0 overflow-auto rounded-lg border border-[var(--border)] bg-black/40 text-[11px] text-green-200 p-3 font-mono"
        data-testid="logs-output"
      >
        {selected
          ? lines.length > 0
            ? lines.join('\n')
            : '(waiting for log lines…)'
          : '(select a container)'}
        <div ref={linesEndRef} />
      </pre>
    </div>
  );
}
