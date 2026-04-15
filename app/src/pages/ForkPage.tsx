import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import { ArrowLeft } from '@phosphor-icons/react';
import {
  marketplaceAppsApi,
  type AppVersionSummary,
  type MarketplaceApp,
} from '../lib/api';
import { CardSurface } from '../components/cards/CardSurface';
import { useTeam } from '../contexts/TeamContext';

const SLUG_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export default function ForkPage() {
  const { appId } = useParams<{ appId: string }>();
  const navigate = useNavigate();
  const { activeTeam } = useTeam();

  const [source, setSource] = useState<MarketplaceApp | null>(null);
  const [versions, setVersions] = useState<AppVersionSummary[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [newSlug, setNewSlug] = useState('');
  const [newName, setNewName] = useState('');
  const [description, setDescription] = useState('');
  const [sourceAppVersionId, setSourceAppVersionId] = useState<string>('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!appId) return;
    let cancelled = false;
    (async () => {
      try {
        const [a, v] = await Promise.all([
          marketplaceAppsApi.get(appId),
          marketplaceAppsApi.listVersions(appId, { limit: 50 }),
        ]);
        if (cancelled) return;
        setSource(a);
        const approved = v.items.filter((x) => x.approval_state === 'approved' && !x.yanked_at);
        setVersions(approved);
        if (approved[0]) setSourceAppVersionId(approved[0].id);
        if (!newName) setNewName(`${a.name} fork`);
        if (!newSlug) setNewSlug(`${a.slug}-fork`);
      } catch {
        if (!cancelled) setLoadError('Failed to load source app');
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appId]);

  const slugError = useMemo(() => {
    if (!newSlug) return 'Slug is required';
    if (!SLUG_RE.test(newSlug))
      return 'Use lowercase letters, numbers, and hyphens only (e.g. my-app)';
    return null;
  }, [newSlug]);

  const nameError = useMemo(() => (!newName.trim() ? 'Name is required' : null), [newName]);
  const versionError = useMemo(
    () => (!sourceAppVersionId ? 'Pick a source version' : null),
    [sourceAppVersionId]
  );

  const canSubmit =
    !submitting && !slugError && !nameError && !versionError && source !== null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || !source) return;
    setSubmitting(true);
    try {
      const forked = await marketplaceAppsApi.fork(source.id, {
        source_app_version_id: sourceAppVersionId,
        new_slug: newSlug,
        new_name: newName.trim(),
        team_id: activeTeam?.id,
      });
      toast.success(`Forked ${source.name}`);
      if (forked.project_slug) {
        navigate(`/project/${forked.project_slug}`);
      } else {
        navigate(`/apps/${forked.id}`);
      }
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to fork app';
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  if (loadError) {
    return (
      <div className="p-8 text-sm text-red-400" data-testid="fork-error">
        {loadError}
      </div>
    );
  }
  if (!source) {
    return (
      <div className="p-8 text-sm text-[var(--muted)]" data-testid="fork-loading">
        Loading…
      </div>
    );
  }

  return (
    <div className="max-w-xl mx-auto p-6 md:p-8" data-testid="fork-page">
      <button
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1.5 text-sm text-[var(--muted)] hover:text-[var(--text)] mb-4"
      >
        <ArrowLeft className="w-4 h-4" />
        Back
      </button>

      <h1 className="font-heading text-2xl font-semibold text-[var(--text)] mb-1">
        Fork {source.name}
      </h1>
      <p className="text-sm text-[var(--muted)] mb-6">
        Create your own copy. You can edit, publish new versions, and set visibility.
      </p>

      <CardSurface variant="featured" disableHoverLift>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-xs uppercase tracking-wide text-[var(--muted)] mb-1.5">
              New slug
            </label>
            <input
              value={newSlug}
              onChange={(e) => setNewSlug(e.target.value.toLowerCase())}
              placeholder="my-app-fork"
              className="w-full px-3 py-2 rounded-lg bg-[var(--surface-hover)] border border-[var(--border)] text-sm text-[var(--text)] focus:outline-none focus:border-[var(--primary)]"
              data-testid="fork-slug-input"
            />
            {slugError && <div className="text-xs text-red-400 mt-1">{slugError}</div>}
          </div>

          <div>
            <label className="block text-xs uppercase tracking-wide text-[var(--muted)] mb-1.5">
              New name
            </label>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="My App Fork"
              className="w-full px-3 py-2 rounded-lg bg-[var(--surface-hover)] border border-[var(--border)] text-sm text-[var(--text)] focus:outline-none focus:border-[var(--primary)]"
              data-testid="fork-name-input"
            />
            {nameError && <div className="text-xs text-red-400 mt-1">{nameError}</div>}
          </div>

          <div>
            <label className="block text-xs uppercase tracking-wide text-[var(--muted)] mb-1.5">
              Description (optional)
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 rounded-lg bg-[var(--surface-hover)] border border-[var(--border)] text-sm text-[var(--text)] focus:outline-none focus:border-[var(--primary)]"
            />
          </div>

          <div>
            <label className="block text-xs uppercase tracking-wide text-[var(--muted)] mb-1.5">
              Source version
            </label>
            <select
              value={sourceAppVersionId}
              onChange={(e) => setSourceAppVersionId(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-[var(--surface-hover)] border border-[var(--border)] text-sm text-[var(--text)] focus:outline-none focus:border-[var(--primary)]"
              data-testid="fork-version-select"
            >
              {versions.length === 0 && <option value="">No approved versions</option>}
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  v{v.version}
                </option>
              ))}
            </select>
            {versionError && <div className="text-xs text-red-400 mt-1">{versionError}</div>}
          </div>

          <div className="flex items-center gap-3 pt-2">
            <button
              type="button"
              onClick={() => navigate(-1)}
              className="flex-1 py-2.5 rounded-lg bg-white/5 border border-white/10 text-[var(--text)] text-sm font-semibold hover:bg-white/10 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="flex-1 py-2.5 rounded-lg bg-[var(--primary)] text-white text-sm font-semibold hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition"
              data-testid="fork-submit"
            >
              {submitting ? 'Forking…' : 'Fork app'}
            </button>
          </div>
        </form>
      </CardSurface>
    </div>
  );
}
