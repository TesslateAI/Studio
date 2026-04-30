import { useEffect, useState } from 'react';
import { projectsApi } from '../../../lib/api';
import type { AutomationWorkspaceScope } from '../../../types/automations';

interface Props {
  scope: AutomationWorkspaceScope;
  targetProjectId: string;
  onChange: (next: { scope: AutomationWorkspaceScope; targetProjectId: string }) => void;
}

interface ProjectRow {
  id: string;
  name: string;
}

const SCOPE_OPTIONS: Array<{ value: AutomationWorkspaceScope; label: string; help: string }> = [
  {
    value: 'none',
    label: 'No files needed',
    help: 'The automation just runs an action — no project files involved.',
  },
  {
    value: 'user_automation_workspace',
    label: 'In my personal automation folder',
    help: 'Use a private folder shared across your automations.',
  },
  {
    value: 'team_automation_workspace',
    label: "In our team's automation folder",
    help: 'Use a shared folder visible to everyone on the team.',
  },
  {
    value: 'target_project',
    label: 'Inside one of my projects',
    help: 'Run inside an existing project. Pick the project below.',
  },
];

export function WorkspacePicker({ scope, targetProjectId, onChange }: Props) {
  const [projects, setProjects] = useState<ProjectRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pasteMode, setPasteMode] = useState(false);

  useEffect(() => {
    if (scope !== 'target_project') return;
    let cancelled = false;
    projectsApi
      .getAll()
      .then((data: unknown) => {
        if (cancelled) return;
        const list = (Array.isArray(data) ? data : []) as Array<{
          id?: string;
          name?: string;
          slug?: string;
        }>;
        setProjects(
          list
            .filter((p) => p.id && (p.name || p.slug))
            .map((p) => ({
              id: String(p.id),
              name: p.name ?? p.slug ?? String(p.id),
            }))
        );
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err?.message || 'Failed to load projects');
        setProjects([]);
      });
    return () => {
      cancelled = true;
    };
  }, [scope]);

  const setScope = (next: AutomationWorkspaceScope) =>
    onChange({ scope: next, targetProjectId: next === 'target_project' ? targetProjectId : '' });

  const setTargetProjectId = (next: string) =>
    onChange({ scope: 'target_project', targetProjectId: next });

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="block text-xs font-medium text-[var(--text)] mb-1">
          Where should it run?
        </span>
        <select
          value={scope}
          onChange={(e) => setScope(e.target.value as AutomationWorkspaceScope)}
          className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
        >
          {SCOPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <span className="mt-1 block text-[10px] text-[var(--text-subtle)]">
          {SCOPE_OPTIONS.find((o) => o.value === scope)?.help}
        </span>
      </label>

      {scope === 'target_project' && (
        <div className="space-y-1.5">
          {!pasteMode ? (
            <label className="block">
              <span className="block text-xs font-medium text-[var(--text)] mb-1">
                Which project?
              </span>
              {projects === null ? (
                <div className="text-[11px] text-[var(--text-subtle)]">Loading projects…</div>
              ) : projects.length > 0 ? (
                <select
                  value={targetProjectId}
                  onChange={(e) => setTargetProjectId(e.target.value)}
                  className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
                >
                  <option value="">— Pick a project —</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              ) : (
                <p className="text-[11px] text-[var(--text-subtle)]">
                  No projects found. Create a project first, or paste a project UUID below.
                </p>
              )}
              {loadError && (
                <span className="mt-1 block text-[10px] text-[var(--status-error)]">
                  {loadError} — try the paste-UUID fallback below.
                </span>
              )}
            </label>
          ) : (
            <label className="block">
              <span className="block text-xs font-medium text-[var(--text)] mb-1">
                Project UUID
              </span>
              <input
                type="text"
                value={targetProjectId}
                onChange={(e) => setTargetProjectId(e.target.value)}
                placeholder="3f29b54e-…-9c0a"
                className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
              />
            </label>
          )}
          <button
            type="button"
            onClick={() => setPasteMode((v) => !v)}
            className="text-[10px] text-[var(--text-subtle)] hover:text-[var(--text)] underline"
          >
            {pasteMode ? 'Pick from my projects instead' : 'Paste a project UUID instead'}
          </button>
        </div>
      )}
    </div>
  );
}
