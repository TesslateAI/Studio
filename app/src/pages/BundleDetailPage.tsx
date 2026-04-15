import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Package } from '@phosphor-icons/react';
import {
  appBundlesApi,
  appVersionsApi,
  type AppVersionDetail,
  type BundleDetail,
} from '../lib/api';
import { useApps } from '../contexts/AppsContext';
import { BundleInstallWizard } from '../components/apps/BundleInstallWizard';

export default function BundleDetailPage() {
  const { bundleId = '' } = useParams<{ bundleId: string }>();
  const navigate = useNavigate();
  const { myInstalls } = useApps();

  const [bundle, setBundle] = useState<BundleDetail | null>(null);
  const [versions, setVersions] = useState<Record<string, AppVersionDetail | null>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);

  const load = useCallback(async () => {
    if (!bundleId) return;
    setLoading(true);
    setError(null);
    try {
      const b = await appBundlesApi.get(bundleId);
      setBundle(b);
      const pairs = await Promise.all(
        b.items.map(async (it) => {
          try {
            const v = await appVersionsApi.get(it.app_version_id);
            return [it.app_version_id, v] as const;
          } catch {
            return [it.app_version_id, null] as const;
          }
        })
      );
      const m: Record<string, AppVersionDetail | null> = {};
      for (const [id, v] of pairs) m[id] = v;
      setVersions(m);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load bundle');
    } finally {
      setLoading(false);
    }
  }, [bundleId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <div className="p-6 text-sm text-[var(--text-muted)]">Loading…</div>;
  }
  if (error || !bundle) {
    return (
      <div className="p-6 text-center">
        <p className="text-sm text-[var(--text-muted)] mb-3">{error ?? 'Bundle not found'}</p>
        <button className="btn" onClick={() => navigate('/apps')}>
          Back to Apps
        </button>
      </div>
    );
  }

  const installedVersionIds = new Set(myInstalls.map((i) => i.app_version_id));

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
            <h1 className="text-lg font-semibold text-[var(--text)]">{bundle.display_name}</h1>
            <p className="text-xs text-[var(--text-subtle)]">
              {bundle.slug} · {bundle.status}
            </p>
          </div>
          <button
            className="btn btn-filled"
            disabled={bundle.items.length === 0}
            onClick={() => setWizardOpen(true)}
          >
            Install bundle
          </button>
        </div>

        <h2 className="text-sm font-semibold text-[var(--text)] mb-2">
          Members ({bundle.items.length})
        </h2>
        <div className="flex flex-col gap-2">
          {bundle.items.map((it) => {
            const v = versions[it.app_version_id];
            const installed = installedVersionIds.has(it.app_version_id);
            return (
              <div
                key={it.app_version_id}
                className="flex items-center gap-3 p-3 border border-[var(--border)] rounded-[var(--radius-small)]"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-mono text-[var(--text)]">
                    {v?.version ? `v${v.version}` : it.app_version_id.slice(0, 12)}
                  </div>
                  <div className="text-[10px] text-[var(--text-subtle)]">
                    order {it.order_index} · {it.required ? 'required' : 'optional'}
                    {it.default_enabled ? ' · default on' : ''}
                  </div>
                </div>
                <span
                  className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                    installed
                      ? 'bg-[var(--surface-hover)] text-[var(--text)]'
                      : 'bg-[var(--surface)] text-[var(--text-subtle)]'
                  }`}
                >
                  {installed ? 'installed' : 'not installed'}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {wizardOpen && (
        <BundleInstallWizard
          bundleId={bundle.id}
          onClose={() => setWizardOpen(false)}
          onDone={() => {
            setWizardOpen(false);
            void load();
          }}
        />
      )}
    </div>
  );
}
