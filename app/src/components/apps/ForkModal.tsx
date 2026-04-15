import { useState } from 'react';
import { X } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import { marketplaceAppsApi, type MarketplaceApp } from '../../lib/api';
import { useTeam } from '../../contexts/TeamContext';

export interface ForkModalProps {
  appId: string;
  sourceAppVersionId: string;
  onClose: () => void;
  onForked: (newApp: MarketplaceApp & { project_id?: string | null; project_slug?: string | null }) => void;
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
}

export function ForkModal({ appId, sourceAppVersionId, onClose, onForked }: ForkModalProps) {
  const { activeTeam } = useTeam();
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [slugTouched, setSlugTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const effectiveSlug = slugTouched ? slug : slugify(name);

  const canSubmit = name.trim().length > 0 && effectiveSlug.length > 0 && !submitting;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const newApp = await marketplaceAppsApi.fork(appId, {
        source_app_version_id: sourceAppVersionId,
        new_slug: effectiveSlug,
        new_name: name.trim(),
        team_id: activeTeam?.id,
      });
      toast.success(`Forked as ${newApp.name}`);
      onForked(newApp);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to fork app';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Fork app"
    >
      <form
        className="w-full max-w-md bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius)] shadow-xl flex flex-col"
        onSubmit={submit}
      >
        <div className="flex items-center gap-3 p-4 border-b border-[var(--border)]">
          <h2 className="text-sm font-semibold text-[var(--text)] flex-1">Fork this app</h2>
          <button
            type="button"
            className="btn btn-sm"
            onClick={onClose}
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </div>
        <div className="p-4 flex flex-col gap-3 text-sm">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-[var(--text-subtle)]">New app name</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="h-8 px-2 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-small)] text-sm text-[var(--text)]"
              placeholder="My forked app"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-[var(--text-subtle)]">Slug</span>
            <input
              type="text"
              value={effectiveSlug}
              onChange={(e) => {
                setSlugTouched(true);
                setSlug(slugify(e.target.value));
              }}
              required
              pattern="[a-z0-9-]+"
              className="h-8 px-2 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-small)] text-sm text-[var(--text)] font-mono"
              placeholder="my-forked-app"
            />
          </label>
          {error && <p className="text-xs text-[var(--danger, #c00)]">{error}</p>}
        </div>
        <div className="flex items-center gap-2 p-4 border-t border-[var(--border)]">
          <div className="flex-1" />
          <button type="button" className="btn" onClick={onClose} disabled={submitting}>
            Cancel
          </button>
          <button type="submit" className="btn btn-filled" disabled={!canSubmit}>
            {submitting ? 'Forking…' : 'Fork'}
          </button>
        </div>
      </form>
    </div>
  );
}

export default ForkModal;
