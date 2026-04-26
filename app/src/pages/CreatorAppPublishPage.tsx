import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  appVersionsApi,
  marketplaceAppsApi,
  projectsApi,
  type MarketplaceApp,
  type AppVersionSummary,
  type CompatReport,
} from '../lib/api';
import { useTeam } from '../contexts/TeamContext';
import { useToast } from '../components/ui/Toast';

interface ProjectLite {
  id: string;
  slug: string;
  name: string;
  project_kind?: 'workspace' | 'app_source' | 'app_runtime';
}

interface AxiosLikeError {
  response?: { status?: number; data?: { detail?: string } };
  message?: string;
}

function extractError(err: unknown, fallback: string): string {
  const e = err as AxiosLikeError;
  return e?.response?.data?.detail ?? e?.message ?? fallback;
}

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const SEMVER_RE = /^\d+\.\d+\.\d+(-[a-z0-9]+)?$/;

function skeletonManifest(slug: string, name: string, version: string): string {
  const stub = {
    schema: '2025-01',
    app: {
      slug: slug || 'my-app',
      name: name || 'My App',
      version: version || '0.1.0',
      description: 'Describe your app here.',
    },
    billing: {
      model: 'per_install',
      price_usd: 0,
    },
    surfaces: [
      {
        id: 'main',
        type: 'web',
        entry: '/',
      },
    ],
    state: {
      storage: 'volume',
    },
    listing: {
      category: 'productivity',
      tags: [],
    },
    compatibility: {
      manifest_schemas: ['2025-01'],
      required_features: [],
    },
  };
  return JSON.stringify(stub, null, 2);
}

function compareSemver(a: string, b: string): number {
  const pa = a.split('-')[0].split('.').map(Number);
  const pb = b.split('-')[0].split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    if ((pa[i] ?? 0) !== (pb[i] ?? 0)) return (pa[i] ?? 0) - (pb[i] ?? 0);
  }
  return 0;
}

export default function CreatorAppPublishPage() {
  const { appId } = useParams<{ appId: string }>();
  const navigate = useNavigate();
  const { activeTeam } = useTeam();
  const { showToast } = useToast();

  const existingAppId = appId && appId !== 'new' ? appId : null;

  const [existingApp, setExistingApp] = useState<MarketplaceApp | null>(null);
  const [existingVersions, setExistingVersions] = useState<AppVersionSummary[]>([]);
  const [projects, setProjects] = useState<ProjectLite[]>([]);
  const [projectId, setProjectId] = useState<string>('');
  const [slug, setSlug] = useState('');
  const [name, setName] = useState('');
  const [version, setVersion] = useState('0.1.0');
  const [manifestText, setManifestText] = useState<string>('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [compat, setCompat] = useState<CompatReport | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);

  // Load existing app details if editing
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      if (existingAppId) {
        try {
          const app = await marketplaceAppsApi.get(existingAppId);
          if (cancelled) return;
          setExistingApp(app);
          setSlug(app.slug);
          setName(app.name);
          const v = await marketplaceAppsApi.listVersions(existingAppId, { limit: 50 });
          if (cancelled) return;
          setExistingVersions(v.items);
        } catch (err) {
          if (!cancelled) setErrors({ form: extractError(err, 'Failed to load app') });
        }
      }
      // Load projects
      try {
        const data = await projectsApi.getAll(activeTeam?.slug);
        if (cancelled) return;
        const list: ProjectLite[] = Array.isArray(data) ? data : (data?.items ?? []);
        setProjects(list);
      } catch {
        /* ignore */
      }
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [existingAppId, activeTeam?.slug]);

  const sourceProjects = useMemo(
    () =>
      projects.filter(
        (p) => p.project_kind === 'workspace' || p.project_kind === 'app_source'
      ),
    [projects]
  );

  const insertSkeleton = () => {
    setManifestText(skeletonManifest(slug, name, version));
  };

  const parseManifest = (): Record<string, unknown> | null => {
    try {
      return JSON.parse(manifestText);
    } catch {
      return null;
    }
  };

  const validate = (): Record<string, string> => {
    const errs: Record<string, string> = {};
    if (!projectId) errs.projectId = 'Select a source project';
    if (!slug) errs.slug = 'Slug is required';
    else if (!SLUG_RE.test(slug)) errs.slug = 'Slug must be kebab-case (e.g., my-app)';
    if (!version) errs.version = 'Version is required';
    else if (!SEMVER_RE.test(version))
      errs.version = 'Version must be semver (e.g., 1.2.3 or 1.2.3-beta)';
    else if (existingVersions.length > 0) {
      const highest = existingVersions.reduce((acc, v) =>
        compareSemver(v.version, acc) > 0 ? v.version : acc,
        existingVersions[0].version
      );
      if (compareSemver(version, highest) <= 0) {
        errs.version = `Version must be greater than ${highest}`;
      }
    }
    if (!manifestText.trim()) errs.manifest = 'Manifest is required';
    else if (parseManifest() === null) errs.manifest = 'Manifest is not valid JSON';
    return errs;
  };

  const previewCompat = async () => {
    const parsed = parseManifest();
    if (!parsed) {
      setErrors((e) => ({ ...e, manifest: 'Manifest is not valid JSON' }));
      return;
    }
    // We don't yet have an app_version_id before publishing, so we do a
    // client-side compatibility sketch using the required_features declared
    // in the manifest.
    const required =
      ((parsed['compatibility'] as Record<string, unknown> | undefined)?.['required_features'] as
        | string[]
        | undefined) ?? [];
    setCompat({
      compatible: required.length === 0,
      missing_features: required,
      unsupported_manifest_schema: false,
      upgrade_required: false,
      server_manifest_schemas: ['2025-01'],
      server_feature_set_hash: 'client-preview',
    });
  };

  const handleFile = async (file: File) => {
    const text = await file.text();
    setManifestText(text);
  };

  const submit = async () => {
    const errs = validate();
    setErrors(errs);
    if (Object.keys(errs).length > 0) return;

    const parsed = parseManifest();
    if (!parsed) return;

    setSubmitting(true);
    try {
      const result = await appVersionsApi.publish({
        project_id: projectId,
        manifest: parsed,
        app_id: existingAppId ?? undefined,
      });
      showToast({
        type: 'success',
        title: 'Published',
        message: `Version ${result.version} submitted for review.`,
      });
      navigate(`/creator/apps/${result.app_id}/versions/${result.app_version_id}`);
    } catch (err) {
      const e = err as AxiosLikeError;
      const status = e?.response?.status;
      const detail = e?.response?.data?.detail ?? '';
      const next: Record<string, string> = {};
      if (status === 409) {
        next.version = detail || 'Duplicate version';
      } else if (status === 422) {
        const m = /feature[:\s]+`?([\w-]+)`?/i.exec(detail);
        if (m) next.manifest = `Missing feature: ${m[1]}`;
        else next.form = detail || 'Validation error';
      } else if (/volume/i.test(detail)) {
        next.projectId = detail;
      } else {
        next.form = extractError(err, 'Publish failed');
      }
      setErrors(next);
      showToast({ type: 'error', title: 'Publish failed', message: next.form || detail });
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return <div className="p-6 text-[var(--text-muted)]">Loading...</div>;
  }

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      <h1 className="text-xl font-semibold text-[var(--text)]">
        {existingApp ? `Publish new version of ${existingApp.name}` : 'Publish New App'}
      </h1>

      {errors.form && <div className="text-sm text-red-500">{errors.form}</div>}

      <div>
        <label className="block text-sm font-medium text-[var(--text)] mb-1">
          Source project
        </label>
        <select
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          className="w-full px-3 py-2 rounded border bg-[var(--surface)] text-[var(--text)]"
          style={{ borderColor: 'var(--border)' }}
        >
          <option value="">Select a project...</option>
          {sourceProjects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} ({p.slug})
            </option>
          ))}
        </select>
        {errors.projectId && (
          <div className="mt-1 text-xs text-red-500">{errors.projectId}</div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1">Slug</label>
          <input
            type="text"
            value={slug}
            readOnly={Boolean(existingApp)}
            onChange={(e) => setSlug(e.target.value)}
            className="w-full px-3 py-2 rounded border bg-[var(--surface)] text-[var(--text)]"
            style={{ borderColor: 'var(--border)' }}
            placeholder="my-app"
          />
          {errors.slug && <div className="mt-1 text-xs text-red-500">{errors.slug}</div>}
        </div>
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1">Version</label>
          <input
            type="text"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            className="w-full px-3 py-2 rounded border bg-[var(--surface)] text-[var(--text)]"
            style={{ borderColor: 'var(--border)' }}
            placeholder="0.1.0"
          />
          {errors.version && <div className="mt-1 text-xs text-red-500">{errors.version}</div>}
        </div>
      </div>

      {!existingApp && (
        <div>
          <label className="block text-sm font-medium text-[var(--text)] mb-1">App Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-3 py-2 rounded border bg-[var(--surface)] text-[var(--text)]"
            style={{ borderColor: 'var(--border)' }}
          />
        </div>
      )}

      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="block text-sm font-medium text-[var(--text)]">Manifest (JSON)</label>
          <div className="flex items-center gap-2 text-xs">
            <button
              type="button"
              onClick={insertSkeleton}
              className="text-[var(--accent)] hover:underline"
            >
              Generate skeleton
            </button>
            <label className="text-[var(--accent)] hover:underline cursor-pointer">
              Upload file
              <input
                type="file"
                accept=".json,application/json"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void handleFile(f);
                }}
                className="hidden"
              />
            </label>
          </div>
        </div>
        <textarea
          value={manifestText}
          onChange={(e) => setManifestText(e.target.value)}
          className="w-full h-72 px-3 py-2 rounded border font-mono text-xs bg-[var(--surface)] text-[var(--text)]"
          style={{ borderColor: 'var(--border)' }}
          placeholder='{ "schema": "2025-01", ... }'
        />
        {errors.manifest && <div className="mt-1 text-xs text-red-500">{errors.manifest}</div>}
      </div>

      {compat && (
        <div
          className="p-3 rounded border text-sm"
          style={{ borderColor: 'var(--border)', backgroundColor: 'var(--surface)' }}
        >
          <div className="font-medium text-[var(--text)] mb-1">
            Compatibility preview: {compat.compatible ? 'OK' : 'Issues'}
          </div>
          {compat.missing_features.length === 0 ? (
            <div className="text-xs text-[var(--text-muted)]">
              No required features declared.
            </div>
          ) : (
            <ul className="text-xs text-[var(--text-muted)]">
              {compat.missing_features.map((f) => (
                <li key={f}>- {f} (will be verified server-side on publish)</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={previewCompat}
          className="px-3 py-2 rounded border text-sm text-[var(--text)]"
          style={{ borderColor: 'var(--border)' }}
        >
          Preview compatibility
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={submitting}
          className="px-4 py-2 rounded bg-[var(--accent)] text-white text-sm disabled:opacity-60"
        >
          {submitting ? 'Publishing...' : 'Publish'}
        </button>
        <button
          type="button"
          onClick={() => navigate('/creator')}
          className="text-sm text-[var(--text-muted)] hover:text-[var(--text)]"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
