import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  marketplaceAppsApi,
  projectsApi,
  type MarketplaceApp,
  type AppVersionSummary,
} from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { CreatorBillingPanel } from './CreatorBillingPage';

type TabKey = 'apps' | 'drafts' | 'submissions' | 'billing';

interface CreatorUser {
  id: string;
  creator_stripe_account_id?: string | null;
}

function extractError(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { detail?: string } }; message?: string };
  return e?.response?.data?.detail ?? e?.message ?? fallback;
}

function StageBadge({ state }: { state: string }) {
  const colors: Record<string, string> = {
    draft: 'bg-gray-500',
    pending: 'bg-yellow-500',
    approved: 'bg-green-500',
    rejected: 'bg-red-500',
    yanked: 'bg-orange-500',
  };
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs text-white ${colors[state] ?? 'bg-gray-500'}`}
    >
      {state}
    </span>
  );
}

function AppCard({
  app,
  onManage,
  latestState,
}: {
  app: MarketplaceApp;
  onManage: () => void;
  latestState?: string;
}) {
  const rep = (app.reputation as { score?: number } | null)?.score ?? 0;
  return (
    <div
      className="p-4 rounded-lg border flex flex-col gap-2"
      style={{
        borderColor: 'var(--border)',
        backgroundColor: 'var(--surface)',
      }}
    >
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-[var(--text)]">{app.name}</h3>
        <StageBadge state={latestState ?? app.state} />
      </div>
      <div className="text-xs text-[var(--text-muted)]">{app.slug}</div>
      <div className="text-sm text-[var(--text-muted)] line-clamp-2">
        {app.description ?? 'No description'}
      </div>
      <div className="flex items-center justify-between text-xs text-[var(--text-muted)] mt-2">
        <span>Reputation: {rep}</span>
        <button
          onClick={onManage}
          className="text-[var(--accent)] hover:underline"
          type="button"
        >
          Manage versions
        </button>
      </div>
    </div>
  );
}

/**
 * Project picker that opens the source project's workspace. The publish
 * flow lives entirely on the architecture canvas (Publish-as-App drawer),
 * so this dropdown's only job is to navigate the creator to the right
 * project — the canvas's "Publish as App" button handles the rest. The
 * backend promotes `workspace → app_source` automatically on first
 * publish, so no client-side kind flip is needed here.
 */
type ProjectKind = 'workspace' | 'app_source' | 'app_runtime';

function PublishNewButton() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [projects, setProjects] = useState<Array<{
    id: string;
    slug: string;
    name: string;
    project_kind: ProjectKind;
  }>>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || projects.length > 0) return;
    setLoading(true);
    setError(null);
    projectsApi
      .getAll()
      .then(
        (
          all: Array<{ id: string; slug: string; name: string; project_kind: ProjectKind }>
        ) => {
          const eligible = all
            .filter(
              (p) => p.project_kind === 'workspace' || p.project_kind === 'app_source'
            )
            .map((p) => ({
              id: p.id,
              slug: p.slug,
              name: p.name,
              project_kind: p.project_kind,
            }));
          setProjects(eligible);
        }
      )
      .catch((err) => setError(extractError(err, 'Failed to load projects')))
      .finally(() => setLoading(false));
  }, [open, projects.length]);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="px-3 py-2 rounded bg-[var(--accent)] text-white text-sm"
        type="button"
      >
        Publish from project ▾
      </button>
      {open && (
        <div
          className="absolute right-0 mt-1 min-w-[260px] rounded border bg-[var(--bg)] shadow-lg z-50"
          style={{ borderColor: 'var(--border)' }}
        >
          <div className="px-3 py-2 text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
            Open project to publish
          </div>
          {loading && (
            <div className="px-3 py-2 text-xs text-[var(--text-muted)]">Loading…</div>
          )}
          {error && (
            <div className="px-3 py-2 text-xs text-red-500">{error}</div>
          )}
          {!loading && !error && projects.length === 0 && (
            <div className="px-3 py-2 text-xs text-[var(--text-muted)]">
              No eligible projects.
            </div>
          )}
          <div className="max-h-64 overflow-y-auto">
            {projects.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => {
                  setOpen(false);
                  navigate(`/project/${p.slug}`);
                }}
                className="w-full text-left px-3 py-2 text-sm hover:bg-[var(--surface)] flex items-center justify-between gap-2"
              >
                <span className="truncate">{p.name}</span>
                {p.project_kind === 'app_source' && (
                  <span className="text-[10px] text-[var(--text-subtle)]">source</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


export default function CreatorStudioPage() {
  const { user } = useAuth();
  const creatorUser = user as (typeof user & CreatorUser) | null;
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const initialTab = (searchParams.get('tab') as TabKey) || 'apps';
  const [tab, setTab] = useState<TabKey>(initialTab);
  const [apps, setApps] = useState<MarketplaceApp[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [versionsByApp, setVersionsByApp] = useState<Record<string, AppVersionSummary[]>>({});

  const hasStripe = Boolean(creatorUser?.creator_stripe_account_id);

  const selectTab = useCallback(
    (t: TabKey) => {
      setTab(t);
      const next = new URLSearchParams(searchParams);
      next.set('tab', t);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  useEffect(() => {
    if (!creatorUser?.id) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    marketplaceAppsApi
      .list({ creator_user_id: creatorUser.id, limit: 100 })
      .then(async (res) => {
        if (cancelled) return;
        setApps(res.items);
        // Fetch versions for each app (for submissions tab / latest state)
        const out: Record<string, AppVersionSummary[]> = {};
        await Promise.all(
          res.items.map(async (a) => {
            try {
              const v = await marketplaceAppsApi.listVersions(a.id, { limit: 20 });
              out[a.id] = v.items;
            } catch {
              out[a.id] = [];
            }
          })
        );
        if (!cancelled) setVersionsByApp(out);
      })
      .catch((err) => {
        if (!cancelled) setError(extractError(err, 'Failed to load apps'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [creatorUser?.id]);

  const draftApps = useMemo(() => apps.filter((a) => a.state === 'draft'), [apps]);

  const allVersions = useMemo(() => {
    const rows: Array<{ app: MarketplaceApp; version: AppVersionSummary }> = [];
    for (const app of apps) {
      for (const v of versionsByApp[app.id] ?? []) {
        rows.push({ app, version: v });
      }
    }
    rows.sort((a, b) => (b.version.created_at ?? '').localeCompare(a.version.created_at ?? ''));
    return rows;
  }, [apps, versionsByApp]);

  if (!creatorUser) {
    return (
      <div className="p-8 text-[var(--text-muted)]">Sign in to access Creator Studio.</div>
    );
  }

  if (!hasStripe) {
    return (
      <div className="p-8 max-w-xl mx-auto text-center">
        <h1 className="text-2xl font-semibold text-[var(--text)] mb-3">Become a creator</h1>
        <p className="text-[var(--text-muted)] mb-6">
          Publish apps to the Tesslate marketplace and earn revenue. Set up Stripe Connect to
          continue.
        </p>
        <button
          onClick={() => navigate('/settings')}
          className="px-4 py-2 rounded bg-[var(--accent)] text-white"
          type="button"
        >
          Go to Settings
        </button>
      </div>
    );
  }

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'apps', label: 'My Apps' },
    { key: 'drafts', label: 'Drafts' },
    { key: 'submissions', label: 'Submissions' },
    { key: 'billing', label: 'Billing' },
  ];

  return (
    <div className="h-full flex flex-col">
      <div
        className="flex items-center justify-between px-6 py-4 border-b"
        style={{ borderColor: 'var(--border)' }}
      >
        <div>
          <h1 className="text-xl font-semibold text-[var(--text)]">Creator Studio</h1>
          <p className="text-sm text-[var(--text-muted)]">
            Manage your marketplace apps, submissions, and earnings.
          </p>
        </div>
        <PublishNewButton />
      </div>

      <div
        className="flex gap-6 px-6 h-10 items-center border-b"
        style={{ borderColor: 'var(--border)' }}
      >
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => selectTab(t.key)}
            className={`text-sm font-medium transition-colors ${
              tab === t.key
                ? 'text-[var(--text)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text)]'
            }`}
            type="button"
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {error && <div className="mb-4 text-sm text-red-500">{error}</div>}
        {loading && <div className="text-sm text-[var(--text-muted)]">Loading...</div>}

        {tab === 'apps' && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {apps.length === 0 && !loading && (
              <div className="text-sm text-[var(--text-muted)]">
                You haven't published any apps yet.
              </div>
            )}
            {apps.map((app) => {
              const versions = versionsByApp[app.id] ?? [];
              const latest = versions[0]?.approval_state;
              return (
                <AppCard
                  key={app.id}
                  app={app}
                  latestState={latest}
                  onManage={() => navigate(`/creator/apps/${app.id}/versions`)}
                />
              );
            })}
          </div>
        )}

        {tab === 'drafts' && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {draftApps.length === 0 && !loading && (
              <div className="text-sm text-[var(--text-muted)]">No drafts.</div>
            )}
            {/*
              Drafts are MarketplaceApps that never reached `approved` state.
              Publishing a new version requires the source project workspace
              (where the Publish-as-App drawer lives), but MarketplaceApp
              doesn't carry a back-pointer to its source project today, so
              we surface the draft + send the creator to "Manage versions"
              for visibility. Re-publishing is initiated from the project's
              architecture canvas.
            */}
            {draftApps.map((app) => (
              <div
                key={app.id}
                className="p-4 rounded-lg border"
                style={{ borderColor: 'var(--border)', backgroundColor: 'var(--surface)' }}
              >
                <h3 className="font-semibold text-[var(--text)]">{app.name}</h3>
                <div className="text-xs text-[var(--text-muted)] mb-2">{app.slug}</div>
                <button
                  onClick={() => navigate(`/creator/apps/${app.id}/versions`)}
                  className="text-sm text-[var(--accent)] hover:underline"
                  type="button"
                >
                  Manage versions
                </button>
              </div>
            ))}
          </div>
        )}

        {tab === 'submissions' && (
          <div className="space-y-2">
            <div className="text-xs text-[var(--text-muted)] mb-2">
              Note: Showing version approval states. A dedicated /api/app-submissions/mine
              endpoint is not yet available.
            </div>
            {allVersions.length === 0 && !loading && (
              <div className="text-sm text-[var(--text-muted)]">No submissions.</div>
            )}
            {allVersions.map(({ app, version }) => (
              <div
                key={version.id}
                className="p-3 rounded border flex items-center justify-between"
                style={{ borderColor: 'var(--border)', backgroundColor: 'var(--surface)' }}
              >
                <div>
                  <div className="font-medium text-[var(--text)]">
                    {app.name} v{version.version}
                  </div>
                  <div className="text-xs text-[var(--text-muted)]">
                    {version.created_at?.slice(0, 10)}
                  </div>
                </div>
                <StageBadge state={version.approval_state} />
              </div>
            ))}
          </div>
        )}

        {tab === 'billing' && <CreatorBillingPanel />}
      </div>
    </div>
  );
}

