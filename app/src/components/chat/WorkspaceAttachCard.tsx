import { useMemo, useState } from 'react';
import { FolderOpen, Plus, Search, X, Box } from 'lucide-react';
import type { WorkspaceCandidate } from '@/types/agent';
import { workspaceAttachApi, projectsApi } from '@/lib/api';

/**
 * Mode 'agent-prompt' — rendered inline in the message list when the
 * orchestrator emits a `workspace_attach_required` SSE event. Submits via
 * `POST /api/chat/workspace-attach/{input_id}/submit`.
 *
 * Mode 'upload-prompt' — rendered locally when the user clicks "Upload file"
 * in the PlusMenu while the chat has no workspace. Resolves locally; the
 * caller's `onResolve(projectId)` re-runs the queued upload.
 */
export type WorkspaceAttachCardMode = 'agent-prompt' | 'upload-prompt';

interface BaseProps {
  mode: WorkspaceAttachCardMode;
  candidates: WorkspaceCandidate[];
  reason?: string;
  /** Called after a successful local resolve (upload-prompt mode) so the
   * caller can proceed with the queued upload. */
  onResolve?: (projectId: string) => void;
  /** Called when the user dismisses without choosing. */
  onClose?: () => void;
}

interface AgentPromptProps extends BaseProps {
  mode: 'agent-prompt';
  inputId: string;
}

interface UploadPromptProps extends BaseProps {
  mode: 'upload-prompt';
}

export function WorkspaceAttachCard(props: AgentPromptProps | UploadPromptProps) {
  const { mode, candidates, reason, onResolve, onClose } = props;
  const [filter, setFilter] = useState('');
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return candidates;
    return candidates.filter(
      (c) => c.name.toLowerCase().includes(q) || c.slug.toLowerCase().includes(q)
    );
  }, [candidates, filter]);

  const submitCancel = async () => {
    if (mode === 'agent-prompt') {
      try {
        await workspaceAttachApi.cancel(props.inputId);
      } catch {
        /* best-effort; the card still dismisses locally */
      }
    }
    onClose?.();
  };

  const submitAttach = async (project: WorkspaceCandidate) => {
    setSubmitting(true);
    setError(null);
    try {
      if (mode === 'agent-prompt') {
        await workspaceAttachApi.submit(props.inputId, {
          action: 'attach',
          project_id: project.id,
        });
      }
      onResolve?.(project.id);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Failed to attach workspace');
    } finally {
      setSubmitting(false);
    }
  };

  const submitCreateEmpty = async () => {
    const name = newName.trim() || 'New workspace';
    setSubmitting(true);
    setError(null);
    try {
      if (mode === 'agent-prompt') {
        await workspaceAttachApi.submit(props.inputId, {
          action: 'create_empty',
          name,
        });
        // The agent-side tool will perform the create + emit
        // workspace_attach_resumed; the chat's project_id is set there.
        onResolve?.('');
      } else {
        const result = await projectsApi.create(name, '', 'empty');
        const created = result?.project?.id || result?.id;
        if (!created) throw new Error('Empty workspace creation returned no id');
        onResolve?.(created);
      }
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Failed to create empty workspace');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="bg-blue-500/10 border-2 border-blue-500/30 rounded-lg p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-start gap-3">
          <FolderOpen className="w-5 h-5 text-blue-500 flex-shrink-0 mt-0.5" />
          <div>
            <h4 className="font-semibold text-[var(--text)] mb-1">
              {mode === 'agent-prompt' ? 'Attach a workspace' : 'Pick a workspace for this upload'}
            </h4>
            <p className="text-sm text-[var(--text)]/70">
              {reason ||
                (mode === 'agent-prompt'
                  ? 'The agent needs storage to continue.'
                  : 'Files attach to a workspace. Pick one or create an empty workspace.')}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={submitCancel}
          aria-label="Dismiss"
          className="text-[var(--text)]/50 hover:text-[var(--text)] transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {!creating && (
        <>
          <div className="relative mb-3">
            <Search className="w-4 h-4 absolute left-2 top-2.5 text-[var(--text)]/40" />
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Search workspaces"
              className="w-full pl-8 pr-3 py-2 bg-black/10 border border-[var(--border)] rounded-md text-sm text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:border-blue-500/60"
            />
          </div>

          <div className="max-h-64 overflow-y-auto rounded-md border border-[var(--border)] divide-y divide-[var(--border)]">
            {filtered.length === 0 && (
              <div className="px-3 py-6 text-sm text-[var(--text)]/50 text-center">
                No workspaces match "{filter}"
              </div>
            )}
            {filtered.map((c) => (
              <button
                key={c.id}
                type="button"
                disabled={submitting}
                onClick={() => submitAttach(c)}
                className="w-full px-3 py-2 flex items-center justify-between gap-3 text-left hover:bg-blue-500/5 transition-colors disabled:opacity-60"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <Box className="w-4 h-4 text-[var(--text)]/60 flex-shrink-0" />
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-[var(--text)] truncate">{c.name}</div>
                    <div className="text-xs text-[var(--text)]/50 truncate">{c.slug}</div>
                  </div>
                </div>
                <div className="flex flex-shrink-0 items-center gap-1">
                  {c.created_via === 'empty' && (
                    <span className="text-[10px] uppercase tracking-wide bg-blue-500/20 text-blue-500 px-1.5 py-0.5 rounded">
                      empty
                    </span>
                  )}
                  {c.created_via === 'template' && (
                    <span className="text-[10px] uppercase tracking-wide bg-purple-500/20 text-purple-500 px-1.5 py-0.5 rounded">
                      template
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={() => setCreating(true)}
            className="w-full mt-3 px-3 py-2 bg-blue-500/15 hover:bg-blue-500/25 border border-blue-500/40 rounded-md text-blue-500 text-sm font-medium transition-all flex items-center justify-center gap-2"
          >
            <Plus className="w-4 h-4" /> Create empty workspace
          </button>
        </>
      )}

      {creating && (
        <div className="space-y-2">
          <label className="text-xs uppercase tracking-wide text-[var(--text)]/60">
            Workspace name
          </label>
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="e.g. Notes"
            className="w-full px-3 py-2 bg-black/10 border border-[var(--border)] rounded-md text-sm text-[var(--text)] focus:outline-none focus:border-blue-500/60"
          />
          <div className="flex gap-2">
            <button
              type="button"
              onClick={submitCreateEmpty}
              disabled={submitting}
              className="flex-1 px-3 py-2 bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/40 rounded-md text-blue-500 text-sm font-medium transition-all disabled:opacity-60"
            >
              {submitting ? 'Creating…' : 'Create'}
            </button>
            <button
              type="button"
              onClick={() => setCreating(false)}
              disabled={submitting}
              className="px-3 py-2 border border-[var(--border)] rounded-md text-sm text-[var(--text)]/70 hover:bg-black/5 transition-colors"
            >
              Back
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="mt-3 px-3 py-2 bg-red-500/10 border border-red-500/30 rounded-md text-xs text-red-500">
          {error}
        </div>
      )}
    </div>
  );
}
