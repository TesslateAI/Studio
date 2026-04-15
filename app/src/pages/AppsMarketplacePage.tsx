import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { MagnifyingGlass, Package } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import {
  marketplaceAppsApi,
  type MarketplaceApp,
} from '../lib/api';
import { Pagination } from '../components/marketplace';
import { AppInstallWizard } from '../components/apps/AppInstallWizard';

const PAGE_SIZE = 20;

const CATEGORIES = [
  { id: 'all', label: 'All Categories' },
  { id: 'productivity', label: 'Productivity' },
  { id: 'ai', label: 'AI / ML' },
  { id: 'dev', label: 'Developer Tools' },
  { id: 'data', label: 'Data' },
  { id: 'content', label: 'Content' },
  { id: 'other', label: 'Other' },
];

interface AppCardProps {
  app: MarketplaceApp;
  onInstall: (app: MarketplaceApp) => void;
  onOpen: (app: MarketplaceApp) => void;
}

function AppCard({ app, onInstall, onOpen }: AppCardProps) {
  return (
    <div
      className="flex flex-col gap-3 p-4 rounded-[var(--radius)] bg-[var(--surface)] border border-[var(--border)] hover:border-[var(--border-hover)] transition-colors cursor-pointer"
      onClick={() => onOpen(app)}
      role="article"
      aria-label={`App ${app.name}`}
    >
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-[var(--radius-small)] bg-[var(--surface-hover)] flex items-center justify-center text-[var(--text-muted)]">
          <Package size={20} />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-sm text-[var(--text)] truncate">{app.name}</h3>
          <p className="text-[11px] text-[var(--text-subtle)]">{app.category ?? 'uncategorized'}</p>
        </div>
      </div>
      <p className="text-xs text-[var(--text-muted)] line-clamp-3 min-h-[3em]">
        {app.description ?? 'No description provided.'}
      </p>
      <div className="flex items-center justify-between pt-2 border-t border-[var(--border)]">
        <span className="text-[10px] uppercase tracking-wide text-[var(--text-subtle)]">
          {app.creator_user_id ? 'Community' : 'Official'}
        </span>
        <button
          className="btn btn-filled"
          onClick={(e) => {
            e.stopPropagation();
            onInstall(app);
          }}
        >
          Install
        </button>
      </div>
    </div>
  );
}

export default function AppsMarketplacePage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [query, setQuery] = useState(searchParams.get('q') ?? '');
  const [category, setCategory] = useState(searchParams.get('category') ?? 'all');
  const [page, setPage] = useState(Number(searchParams.get('page') ?? '1') || 1);

  const [apps, setApps] = useState<MarketplaceApp[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [installTargetVersionId, setInstallTargetVersionId] = useState<string | null>(null);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(total / PAGE_SIZE)),
    [total]
  );

  const load = useCallback(
    async (params: { q: string; category: string; page: number }) => {
      setLoading(true);
      setError(null);
      try {
        const result = await marketplaceAppsApi.list({
          q: params.q || undefined,
          category: params.category !== 'all' ? params.category : undefined,
          limit: PAGE_SIZE,
          offset: (params.page - 1) * PAGE_SIZE,
        });
        setApps(result.items);
        setTotal(result.total);
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Failed to load apps';
        setError(msg);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    void load({ q: query, category, page });
    const next = new URLSearchParams();
    if (query) next.set('q', query);
    if (category !== 'all') next.set('category', category);
    if (page !== 1) next.set('page', String(page));
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, category, page]);

  const handleInstall = async (app: MarketplaceApp) => {
    try {
      const versions = await marketplaceAppsApi.listVersions(app.id, { limit: 1 });
      const latest = versions.items[0];
      if (!latest) {
        toast.error('This app has no approved versions yet');
        return;
      }
      setInstallTargetVersionId(latest.id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load versions';
      toast.error(msg);
    }
  };

  const handleOpen = (app: MarketplaceApp) => {
    navigate(`/apps/${app.id}`);
  };

  return (
    <div className="flex-1 overflow-y-auto bg-[var(--bg)]">
      <div className="sticky top-0 z-30 bg-[var(--bg)] border-b border-[var(--border)]">
        <div className="flex items-center gap-3 p-3">
          <h1 className="text-sm font-semibold text-[var(--text)]">Tesslate Apps</h1>
          <span className="text-[10px] text-[var(--text-subtle)]">{total} results</span>
          <div className="flex-1" />
          <div className="relative">
            <MagnifyingGlass
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-subtle)]"
            />
            <input
              type="text"
              placeholder="Search apps..."
              value={query}
              onChange={(e) => {
                setPage(1);
                setQuery(e.target.value);
              }}
              className="w-56 h-8 pl-8 pr-3 bg-[var(--surface)] border border-[var(--border)] rounded-full text-xs text-[var(--text)] focus:outline-none focus:border-[var(--border-hover)]"
              aria-label="Search apps"
            />
          </div>
        </div>
        <div className="flex items-center gap-1 px-3 pb-2 overflow-x-auto scrollbar-none">
          {CATEGORIES.map((cat) => (
            <button
              key={cat.id}
              onClick={() => {
                setPage(1);
                setCategory(cat.id);
              }}
              className={`btn shrink-0 ${category === cat.id ? 'btn-tab-active' : 'btn-tab'}`}
            >
              {cat.label}
            </button>
          ))}
        </div>
      </div>

      <div className="p-4">
        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="h-40 rounded-[var(--radius)] bg-[var(--surface)] animate-pulse"
              />
            ))}
          </div>
        ) : error ? (
          <div className="text-center py-16 rounded-[var(--radius)] bg-[var(--surface)]">
            <p className="text-sm text-[var(--text-muted)] mb-3">{error}</p>
            <button
              className="btn btn-filled"
              onClick={() => void load({ q: query, category, page })}
            >
              Retry
            </button>
          </div>
        ) : apps.length === 0 ? (
          <div className="text-center py-16 rounded-[var(--radius)] bg-[var(--surface)]">
            <Package size={48} className="mx-auto mb-4 text-[var(--text-subtle)]" />
            <p className="text-[var(--text-subtle)]">
              {query ? `No apps matching "${query}"` : 'No apps available'}
            </p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
              {apps.map((app) => (
                <AppCard
                  key={app.id}
                  app={app}
                  onInstall={handleInstall}
                  onOpen={handleOpen}
                />
              ))}
            </div>
            <Pagination
              currentPage={page}
              totalPages={totalPages}
              onPageChange={setPage}
            />
          </>
        )}
      </div>

      {installTargetVersionId && (
        <AppInstallWizard
          appVersionId={installTargetVersionId}
          onClose={() => setInstallTargetVersionId(null)}
          onDone={(_instanceId) => {
            setInstallTargetVersionId(null);
            navigate('/library?tab=apps');
          }}
        />
      )}
    </div>
  );
}
