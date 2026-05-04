import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, CaretDown, CaretRight, Package } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import { marketplaceAppsApi, type AppVersionSummary, type MarketplaceApp } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { AppInstallWizard } from '../components/apps/AppInstallWizard';
import { ForkModal } from '../components/apps/ForkModal';

function short(hash: string | null): string {
  if (!hash) return '—';
  return hash.slice(0, 12);
}

interface VersionRowProps {
  version: AppVersionSummary;
  onInstall: (id: string) => void;
}

function VersionRow({ version, onInstall }: VersionRowProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-[var(--border)] rounded-[var(--radius-small)]">
      <button
        className="w-full flex items-center gap-2 p-3 text-left hover:bg-[var(--surface-hover)]"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? <CaretDown size={12} /> : <CaretRight size={12} />}
        <span className="font-mono text-xs text-[var(--text)]">v{version.version}</span>
        <span className="font-mono text-[10px] text-[var(--text-subtle)]">
          {short(version.bundle_hash)}
        </span>
        <span className="flex-1" />
        <span className="text-[10px] text-[var(--text-subtle)]">
          {version.published_at
            ? new Date(version.published_at).toLocaleDateString()
            : 'unpublished'}
        </span>
        <span
          className={`text-[10px] px-1.5 py-0.5 rounded-full ${
            version.approval_state === 'approved'
              ? 'bg-[var(--surface-hover)] text-[var(--text)]'
              : 'bg-[var(--surface)] text-[var(--text-subtle)]'
          }`}
        >
          {version.approval_state}
        </span>
        {version.yanked_at && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[var(--surface)] text-[var(--danger, #c00)]">
            yanked
          </span>
        )}
      </button>
      {open && (
        <div className="p-3 border-t border-[var(--border)] bg-[var(--surface)] text-xs text-[var(--text-muted)]">
          <div className="font-mono break-all mb-1">bundle: {version.bundle_hash ?? '—'}</div>
          <div className="font-mono break-all mb-3">manifest: {version.manifest_hash}</div>
          {version.yanked_reason && (
            <div className="mb-3">Yank reason: {version.yanked_reason}</div>
          )}
          <button
            className="btn btn-filled"
            disabled={
              !(
                version.approval_state === 'approved' ||
                version.approval_state === 'stage1_approved' ||
                version.approval_state === 'stage2_approved'
              ) || !!version.yanked_at
            }
            onClick={() => onInstall(version.id)}
          >
            Install this version
          </button>
        </div>
      )}
    </div>
  );
}

export default function AppDetailPage() {
  const { appId = '' } = useParams<{ appId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const isSuperuser = user?.is_superuser ?? false;

  const [app, setApp] = useState<MarketplaceApp | null>(null);
  const [versions, setVersions] = useState<AppVersionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [installVersionId, setInstallVersionId] = useState<string | null>(null);
  const [forkOpen, setForkOpen] = useState(false);

  const load = useCallback(async () => {
    if (!appId) return;
    setLoading(true);
    setError(null);
    try {
      const [appData, versionsData] = await Promise.all([
        marketplaceAppsApi.get(appId),
        marketplaceAppsApi.listVersions(appId, { limit: 50 }),
      ]);
      setApp(appData);
      setVersions(versionsData.items);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load app';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [appId]);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleVersions = versions.filter((v) => {
    if (isSuperuser) return true;
    if (v.approval_state !== 'approved') return false;
    if (v.yanked_at) return false;
    return true;
  });

  // Backend's installer accepts ``stage1_approved`` and ``stage2_approved``
  // (services/apps/installer.py:_APPROVED_STATES). The model has no plain
  // ``approved`` state — that was a pre-Wave-3 alias. Keep the alias accepted
  // for back-compat with any out-of-band rows that still carry it.
  const latestInstallable = visibleVersions.find(
    (v) =>
      (v.approval_state === 'approved' ||
        v.approval_state === 'stage1_approved' ||
        v.approval_state === 'stage2_approved') &&
      !v.yanked_at
  );

  const canFork = app && (app.forkable === 'true' || app.forkable === 'restricted');

  if (loading) {
    return (
      <div className="p-6">
        <div className="h-8 w-40 bg-[var(--surface)] animate-pulse rounded" />
      </div>
    );
  }

  if (error || !app) {
    return (
      <div className="p-6 text-center">
        <p className="text-sm text-[var(--text-muted)] mb-3">{error ?? 'App not found'}</p>
        <button className="btn" onClick={() => navigate('/apps')}>
          Back to Apps
        </button>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto bg-[var(--bg)]">
      <div className="p-6 max-w-4xl mx-auto">
        <button className="btn btn-sm mb-4" onClick={() => navigate('/apps')}>
          <ArrowLeft size={14} /> Apps
        </button>

        <div className="flex items-start gap-4 mb-6">
          <div className="w-14 h-14 rounded-[var(--radius)] bg-[var(--surface)] flex items-center justify-center text-[var(--text-muted)]">
            <Package size={28} />
          </div>
          <div className="flex-1">
            <h1 className="text-lg font-semibold text-[var(--text)]">{app.name}</h1>
            <p className="text-xs text-[var(--text-subtle)] mb-1">
              {app.category ?? 'uncategorized'} · {app.slug}
            </p>
            <p className="text-sm text-[var(--text-muted)]">
              {app.description ?? 'No description provided.'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 mb-6">
          <button
            className="btn btn-filled"
            disabled={!latestInstallable}
            onClick={() => latestInstallable && setInstallVersionId(latestInstallable.id)}
          >
            Install latest version
          </button>
          {canFork && (
            <button className="btn" onClick={() => setForkOpen(true)}>
              Fork
            </button>
          )}
        </div>

        <h2 className="text-sm font-semibold text-[var(--text)] mb-2">Versions</h2>
        <div className="flex flex-col gap-2">
          {visibleVersions.length === 0 ? (
            <p className="text-xs text-[var(--text-subtle)]">No versions available.</p>
          ) : (
            visibleVersions.map((v) => (
              <VersionRow key={v.id} version={v} onInstall={(id) => setInstallVersionId(id)} />
            ))
          )}
        </div>
      </div>

      {installVersionId && (
        <AppInstallWizard
          appVersionId={installVersionId}
          onClose={() => setInstallVersionId(null)}
          onDone={(_instanceId) => {
            setInstallVersionId(null);
            toast.success('App installed');
            navigate('/library?tab=apps');
          }}
        />
      )}

      {forkOpen && latestInstallable && (
        <ForkModal
          appId={app.id}
          sourceAppVersionId={latestInstallable.id}
          onClose={() => setForkOpen(false)}
          onForked={(newApp) => {
            setForkOpen(false);
            if (newApp.project_slug) {
              navigate(`/project/${newApp.project_slug}`);
            } else {
              navigate(`/apps/${newApp.id}`);
            }
          }}
        />
      )}
    </div>
  );
}
