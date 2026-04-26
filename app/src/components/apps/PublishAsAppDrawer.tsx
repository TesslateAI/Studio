import { useEffect, useMemo, useState } from 'react';
import { X, CheckCircle, Warning, XCircle, Code, Rocket } from '@phosphor-icons/react';
import Editor from '@monaco-editor/react';
import toast from 'react-hot-toast';
import { publishApi } from '../../lib/api';
import type {
  ChecklistItem,
  ChecklistStatus,
  PublishDraftResponse,
} from '../../types/publish';

interface Props {
  /** Project slug — drives the publish endpoints. */
  projectSlug: string;
  /** Project name — drawer header. */
  projectName: string;
  /** Pre-fetched draft (from the toolbar button). When null, the drawer fetches its own. */
  initialDraft?: PublishDraftResponse | null;
  onClose: () => void;
  /**
   * Called after a successful publish. Parent should refresh project info so
   * the toolbar button reflects the project's new app_source role.
   */
  onPublished?: (result: { appId: string; versionId: string }) => void;
}

const STATUS_ICONS: Record<ChecklistStatus, React.ReactElement> = {
  pass: <CheckCircle size={18} weight="fill" className="text-emerald-500 shrink-0" />,
  warn: <Warning size={18} weight="fill" className="text-amber-500 shrink-0" />,
  fail: <XCircle size={18} weight="fill" className="text-red-500 shrink-0" />,
};

const STATUS_LABELS: Record<ChecklistStatus, string> = {
  pass: 'Ready',
  warn: 'Review',
  fail: 'Blocking',
};

/**
 * Right-side drawer for publishing the active project as a Tesslate App.
 *
 * Flow:
 *   1. Fetch the inferred draft (manifest + checklist) on open.
 *   2. Render the checklist with status icons + Fix buttons (where supported).
 *   3. Optional Monaco YAML editor for hand-editing before publish.
 *   4. "Publish to Marketplace" submits the (possibly edited) manifest to
 *      /api/projects/{slug}/publish-app, which round-trips through the
 *      existing publisher.publish_version() pipeline.
 */
export default function PublishAsAppDrawer({
  projectSlug,
  projectName,
  initialDraft = null,
  onClose,
  onPublished,
}: Props) {
  const [draft, setDraft] = useState<PublishDraftResponse | null>(initialDraft);
  const [yamlText, setYamlText] = useState<string>(initialDraft?.yaml ?? '');
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(initialDraft === null);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch the draft if the parent didn't pre-load it.
  useEffect(() => {
    if (initialDraft) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    publishApi
      .draft(projectSlug)
      .then((d) => {
        if (cancelled) return;
        setDraft(d);
        setYamlText(d.yaml);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setError(e.message ?? 'Failed to load publish draft');
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [initialDraft, projectSlug]);

  // Re-check the manifest after the user edits YAML. The inferrer endpoint
  // doesn't validate edited content directly — for Phase 5 we re-fetch the
  // baseline draft, which lets the checklist re-render with the current
  // project state. Future work: add a /publish-app/validate endpoint that
  // takes the user's YAML and returns a fresh checklist.
  const handleRecheck = async () => {
    setLoading(true);
    setError(null);
    try {
      const fresh = await publishApi.draft(projectSlug);
      setDraft(fresh);
      // Preserve the user's YAML edits — the checklist refreshes but the
      // editor content remains theirs.
    } catch (e) {
      const err = e as Error;
      setError(err.message ?? 'Failed to re-check manifest');
    } finally {
      setLoading(false);
    }
  };

  const handlePublish = async () => {
    if (!draft) return;
    setPublishing(true);
    setError(null);
    try {
      const result = await publishApi.publish(projectSlug, {
        manifest: yamlText,
        app_id: draft.existing_app_id ?? null,
      });
      toast.success(
        `Published ${projectName} v${result.version} to marketplace`,
        { duration: 4000 }
      );
      onPublished?.({ appId: result.app_id, versionId: result.app_version_id });
      onClose();
    } catch (e) {
      const err = e as { response?: { data?: { detail?: unknown } }; message?: string };
      const detail = err.response?.data?.detail;
      const msg =
        typeof detail === 'string'
          ? detail
          : detail && typeof detail === 'object'
            ? JSON.stringify(detail)
            : (err.message ?? 'Publish failed');
      setError(msg);
      toast.error('Publish failed — see drawer for details');
    } finally {
      setPublishing(false);
    }
  };

  const blocking = useMemo(
    () => (draft?.checklist ?? []).some((c) => c.status === 'fail'),
    [draft]
  );

  return (
    <>
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
        data-testid="publish-drawer-backdrop"
      />
      <aside
        className="fixed right-0 top-0 bottom-0 w-full max-w-[640px] bg-[var(--surface)] border-l border-[var(--border)] z-50 flex flex-col shadow-2xl"
        data-testid="publish-as-app-drawer"
        role="dialog"
        aria-label="Publish as App"
      >
        {/* Header */}
        <header className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2 min-w-0">
            <Rocket size={20} weight="fill" className="text-[var(--primary)] shrink-0" />
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-[var(--text)] truncate">
                Publish {projectName} as App
              </h2>
              <p className="text-xs text-[var(--text)]/60">
                Manifest schema 2026-05
                {draft?.existing_app_id ? ' · Republish' : ' · First publish'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded hover:bg-[var(--bg)] text-[var(--text)]/70 hover:text-[var(--text)]"
            aria-label="Close publish drawer"
          >
            <X size={20} />
          </button>
        </header>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {loading && (
            <div className="p-6 text-sm text-[var(--text)]/60">Loading publish draft…</div>
          )}

          {!loading && error && (
            <div className="m-5 p-4 rounded-md border border-red-500/40 bg-red-500/10 text-sm text-red-700 dark:text-red-300 whitespace-pre-wrap">
              {error}
            </div>
          )}

          {!loading && draft && (
            <>
              <section className="p-5 border-b border-[var(--border)]">
                <h3 className="text-sm font-semibold text-[var(--text)] mb-3">
                  Pre-publish checklist
                </h3>
                <ul className="space-y-2">
                  {draft.checklist.map((item) => (
                    <ChecklistRow key={item.id} item={item} onEditYaml={() => setEditing(true)} />
                  ))}
                </ul>
              </section>

              <section className="p-5">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-[var(--text)] flex items-center gap-2">
                    <Code size={16} />
                    Manifest YAML
                  </h3>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setEditing((v) => !v)}
                      className="text-xs px-2 py-1 rounded border border-[var(--border)] text-[var(--text)]/80 hover:bg-[var(--bg)]"
                    >
                      {editing ? 'Hide editor' : 'Edit YAML'}
                    </button>
                    <button
                      type="button"
                      onClick={handleRecheck}
                      disabled={loading}
                      className="text-xs px-2 py-1 rounded border border-[var(--border)] text-[var(--text)]/80 hover:bg-[var(--bg)] disabled:opacity-50"
                    >
                      Re-check
                    </button>
                  </div>
                </div>
                {editing ? (
                  <div className="border border-[var(--border)] rounded-md overflow-hidden h-[420px]">
                    <Editor
                      defaultLanguage="yaml"
                      value={yamlText}
                      onChange={(v) => setYamlText(v ?? '')}
                      theme="vs-dark"
                      options={{
                        minimap: { enabled: false },
                        fontSize: 12,
                        lineNumbers: 'on',
                        scrollBeyondLastLine: false,
                        wordWrap: 'on',
                      }}
                    />
                  </div>
                ) : (
                  <pre className="text-xs text-[var(--text)]/80 bg-[var(--bg)] border border-[var(--border)] rounded-md p-3 overflow-auto max-h-[260px] whitespace-pre-wrap">
                    {yamlText}
                  </pre>
                )}
              </section>
            </>
          )}
        </div>

        {/* Footer */}
        <footer className="px-5 py-4 border-t border-[var(--border)] flex items-center justify-between gap-3 bg-[var(--surface)]">
          <span className="text-xs text-[var(--text)]/60">
            {blocking
              ? 'Blocking checklist items must be resolved before publishing.'
              : 'All required checks pass.'}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-sm rounded border border-[var(--border)] text-[var(--text)] hover:bg-[var(--bg)]"
              disabled={publishing}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handlePublish}
              disabled={publishing || loading || !draft || blocking}
              className="px-3 py-1.5 text-sm rounded bg-[var(--primary)] text-white hover:opacity-90 disabled:opacity-40 flex items-center gap-1.5"
              data-testid="publish-to-marketplace-btn"
            >
              <Rocket size={14} weight="fill" />
              {publishing ? 'Publishing…' : 'Publish to Marketplace'}
            </button>
          </div>
        </footer>
      </aside>
    </>
  );
}

interface ChecklistRowProps {
  item: ChecklistItem;
  onEditYaml: () => void;
}

function ChecklistRow({ item, onEditYaml }: ChecklistRowProps) {
  const showFix = item.status !== 'pass' && item.fix_action;
  return (
    <li className="flex items-start gap-3 p-3 rounded-md border border-[var(--border)] bg-[var(--bg)]/40">
      {STATUS_ICONS[item.status]}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-[var(--text)]">{item.title}</span>
          <span
            className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded ${
              item.status === 'pass'
                ? 'text-emerald-600 bg-emerald-500/10'
                : item.status === 'warn'
                  ? 'text-amber-600 bg-amber-500/10'
                  : 'text-red-600 bg-red-500/10'
            }`}
          >
            {STATUS_LABELS[item.status]}
          </span>
        </div>
        <p className="text-xs text-[var(--text)]/70 mt-1 leading-relaxed">{item.detail}</p>
        {showFix && (
          <div className="mt-2">
            <button
              type="button"
              onClick={onEditYaml}
              className="text-xs px-2 py-1 rounded border border-[var(--border)] text-[var(--text)]/80 hover:bg-[var(--surface)]"
            >
              Fix in YAML editor
            </button>
          </div>
        )}
      </div>
    </li>
  );
}
