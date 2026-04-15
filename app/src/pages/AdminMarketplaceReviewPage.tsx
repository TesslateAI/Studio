/**
 * AdminMarketplaceReviewPage
 *
 * Route: /admin/marketplace
 * Gated by useAuth().user.is_superuser. Tabbed UI for marketplace moderation:
 * Submissions, Yank Queue, Stats, Monitoring, Reputation.
 *
 * Note: defense-in-depth gating — the route-level guard should be in App.tsx
 * but we also redirect internally if not a superuser.
 */
import { useMemo, useState, type ReactNode } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';
import { useRequiredAdmin } from '../contexts/AdminContext';
import {
  adminMarketplaceApi,
  type SubmissionQueueItem,
  type YankQueueItem,
  type AdminStats,
} from '../lib/api';

type TabKey = 'submissions' | 'yanks' | 'stats' | 'monitoring' | 'reputation';

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'submissions', label: 'Submissions' },
  { key: 'yanks', label: 'Yank Queue' },
  { key: 'stats', label: 'Stats' },
  { key: 'monitoring', label: 'Monitoring' },
  { key: 'reputation', label: 'Reputation' },
];

const PAGE_SIZE = 20;

export default function AdminMarketplaceReviewPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<TabKey>('submissions');

  if (!user?.is_superuser) return <Navigate to="/dashboard" replace />;

  const admin = useRequiredAdmin();

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <header className="border-b border-[var(--border)] px-8 py-5">
        <h1 className="text-2xl font-semibold">Marketplace Review</h1>
        <p className="text-sm text-[var(--text-muted)] mt-1">
          Submission queue, yanks, monitoring, and creator reputation.
        </p>
      </header>

      <div className="flex gap-6 px-8 border-b border-[var(--border)]">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`py-3 text-sm font-medium transition-colors ${
              tab === t.key
                ? 'text-[var(--text)] border-b-2 border-[var(--primary)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text)]'
            }`}
          >
            {t.label}
          </button>
        ))}
        <div className="ml-auto py-3">
          <button
            onClick={() => {
              void admin.refreshAll();
            }}
            className="text-xs text-[var(--text-muted)] hover:text-[var(--text)]"
          >
            Refresh
          </button>
        </div>
      </div>

      <main className="p-8">
        {admin.error && (
          <div className="mb-4 rounded-md border border-red-500/50 bg-red-500/10 px-3 py-2 text-sm text-red-400">
            {admin.error}
          </div>
        )}
        {tab === 'submissions' && <SubmissionsTab items={admin.submissionQueue} />}
        {tab === 'yanks' && <YankQueueTab items={admin.yankQueue} />}
        {tab === 'stats' && <StatsTab stats={admin.stats} />}
        {tab === 'monitoring' && <MonitoringTab />}
        {tab === 'reputation' && <ReputationTab />}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Submissions tab
// ---------------------------------------------------------------------------

function SubmissionsTab({ items }: { items: SubmissionQueueItem[] }) {
  const navigate = useNavigate();
  const [page, setPage] = useState(0);

  const pageItems = useMemo(
    () => items.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [items, page]
  );
  const totalPages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));

  if (!items.length) {
    return <EmptyState message="No submissions in queue." />;
  }

  return (
    <div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[var(--text-muted)] border-b border-[var(--border)]">
            <th className="py-2 pr-4">Submitter</th>
            <th className="py-2 pr-4">App / Version</th>
            <th className="py-2 pr-4">Stage</th>
            <th className="py-2 pr-4">SLA</th>
            <th className="py-2 pr-4">Checks</th>
          </tr>
        </thead>
        <tbody>
          {pageItems.map((row) => (
            <tr
              key={row.submission_id}
              data-testid={`submission-row-${row.submission_id}`}
              className="border-b border-[var(--border)] cursor-pointer hover:bg-[var(--surface-hover)]"
              onClick={() =>
                navigate(`/admin/marketplace/submissions/${row.submission_id}`)
              }
            >
              <td className="py-2 pr-4 font-mono text-xs">
                {row.app_id.slice(0, 8)}
              </td>
              <td className="py-2 pr-4">
                {row.app_name || row.app_id}
                <span className="text-[var(--text-muted)] ml-2">
                  {row.version ?? '—'}
                </span>
              </td>
              <td className="py-2 pr-4">
                <StageBadge stage={row.stage} />
              </td>
              <td className="py-2 pr-4 text-xs">
                <SLACountdown deadline={row.sla_deadline_at} />
              </td>
              <td className="py-2 pr-4 text-xs">{row.check_count}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="flex items-center gap-2 mt-4 text-xs text-[var(--text-muted)]">
        <button
          disabled={page === 0}
          onClick={() => setPage((p) => Math.max(0, p - 1))}
          className="px-2 py-1 rounded border border-[var(--border)] disabled:opacity-50"
        >
          Previous
        </button>
        <span>
          {page + 1} / {totalPages}
        </span>
        <button
          disabled={page + 1 >= totalPages}
          onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
          className="px-2 py-1 rounded border border-[var(--border)] disabled:opacity-50"
        >
          Next
        </button>
      </div>
    </div>
  );
}

function StageBadge({ stage }: { stage: string }) {
  const colors: Record<string, string> = {
    stage0: 'bg-slate-500/20 text-slate-300',
    stage1: 'bg-blue-500/20 text-blue-300',
    stage2: 'bg-purple-500/20 text-purple-300',
    stage3: 'bg-amber-500/20 text-amber-300',
    approved: 'bg-emerald-500/20 text-emerald-300',
    rejected: 'bg-red-500/20 text-red-300',
  };
  const cls = colors[stage] ?? 'bg-[var(--surface-hover)] text-[var(--text-muted)]';
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {stage}
    </span>
  );
}

function SLACountdown({ deadline }: { deadline: string | null }) {
  if (!deadline) return <span className="text-[var(--text-muted)]">—</span>;
  const ms = new Date(deadline).getTime() - Date.now();
  if (Number.isNaN(ms)) return <span>—</span>;
  const overdue = ms < 0;
  const hours = Math.floor(Math.abs(ms) / 3_600_000);
  const minutes = Math.floor((Math.abs(ms) % 3_600_000) / 60_000);
  return (
    <span className={overdue ? 'text-red-400' : 'text-[var(--text)]'}>
      {overdue ? 'Overdue ' : ''}
      {hours}h {minutes}m
    </span>
  );
}

// ---------------------------------------------------------------------------
// Yank Queue tab (small summary, full UI is AdminYankCenterPage)
// ---------------------------------------------------------------------------

function YankQueueTab({ items }: { items: YankQueueItem[] }) {
  const navigate = useNavigate();
  if (!items.length) return <EmptyState message="No pending yanks." />;
  return (
    <div>
      <button
        onClick={() => navigate('/admin/marketplace/yanks')}
        className="mb-4 text-sm text-[var(--primary)] underline"
      >
        Open full yank center
      </button>
      <ul className="space-y-2">
        {items.slice(0, 10).map((y) => (
          <li
            key={y.id}
            className="rounded border border-[var(--border)] p-3 text-sm flex justify-between"
          >
            <span>
              <span className="font-mono text-xs mr-2">{y.app_version_id.slice(0, 8)}</span>
              {y.reason}
            </span>
            <span className="text-xs text-[var(--text-muted)]">{y.severity}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stats tab
// ---------------------------------------------------------------------------

function StatsTab({ stats }: { stats: AdminStats | null }) {
  if (!stats) return <EmptyState message="No stats available." />;

  const cards: Array<{ label: string; value: number }> = [
    { label: 'Apps total', value: stats.apps_total },
    { label: 'Apps approved', value: stats.apps_approved },
    { label: 'Apps pending', value: stats.apps_pending },
    { label: 'Yanks pending', value: stats.yanks_pending },
    { label: 'Submissions in flight', value: stats.submissions_in_flight },
    { label: 'Monitoring runs (24h)', value: stats.monitoring_runs_24h },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
      {cards.map((c) => (
        <div
          key={c.label}
          className="rounded-xl border border-[var(--border)] p-4 bg-[var(--surface)]"
        >
          <div className="text-xs text-[var(--text-muted)] uppercase tracking-wide">
            {c.label}
          </div>
          <div className="text-3xl font-semibold mt-1">{c.value}</div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Monitoring tab
// ---------------------------------------------------------------------------

function MonitoringTab() {
  const [appVersionId, setAppVersionId] = useState('');
  const [kind, setKind] = useState('smoke');
  const [busy, setBusy] = useState(false);

  const onStart = async () => {
    if (!appVersionId) {
      toast.error('app_version_id required');
      return;
    }
    setBusy(true);
    try {
      const r = await adminMarketplaceApi.startMonitoringRun({
        app_version_id: appVersionId,
        kind,
      });
      toast.success(`Started run ${r.run_id}`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-xl">
      <p className="text-sm text-[var(--text-muted)] mb-4">
        Trigger monitoring runs manually. A list of recent runs requires a
        backend endpoint that is not yet exposed.
      </p>
      <div className="space-y-3">
        <LabeledInput
          label="App version id"
          value={appVersionId}
          onChange={setAppVersionId}
        />
        <LabeledInput label="Kind" value={kind} onChange={setKind} />
        <button
          disabled={busy}
          onClick={() => void onStart()}
          className="px-4 py-2 rounded bg-[var(--primary)] text-white text-sm disabled:opacity-50"
        >
          Start monitoring run
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Reputation tab
// ---------------------------------------------------------------------------

function ReputationTab() {
  const navigate = useNavigate();
  return (
    <div>
      <p className="text-sm text-[var(--text-muted)] mb-3">
        Full reputation management lives on its own page.
      </p>
      <button
        onClick={() => navigate('/admin/marketplace/reputation')}
        className="px-4 py-2 rounded bg-[var(--primary)] text-white text-sm"
      >
        Open reputation center
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

function EmptyState({ message }: { message: string }): ReactNode {
  return <div className="text-sm text-[var(--text-muted)] py-8 text-center">{message}</div>;
}

function LabeledInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="block text-xs uppercase tracking-wide text-[var(--text-muted)] mb-1">
        {label}
      </span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-sm"
      />
    </label>
  );
}
