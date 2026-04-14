import { useTeam } from '../../contexts/TeamContext';

export type Scope = 'user' | 'project';

interface Props {
  value: Scope;
  onChange: (scope: Scope) => void;
  projectId?: string;
}

/**
 * Two-option scope picker for connector installs (issue #307).
 *
 * - **My account** — install lands on the caller's user and follows them
 *   across every team they belong to. Always available.
 * - **This project** — per-user override pinned to a project. Disabled
 *   unless a projectId is provided and the caller can edit that project.
 *
 * Team-scope install is intentionally not offered — OAuth identities are
 * bound to one user and cannot be shared across members.
 */
export function ScopeSelector({ value, onChange, projectId }: Props) {
  const { can } = useTeam();
  const canProject = can('connectors.manage_project') && !!projectId;

  const options: Array<{ id: Scope; label: string; hint: string; disabled: boolean }> = [
    {
      id: 'user',
      label: 'My account',
      hint: 'Available in every team you belong to. Your OAuth tokens only.',
      disabled: false,
    },
    {
      id: 'project',
      label: 'This project only',
      hint: 'Per-user override pinned to the current project.',
      disabled: !canProject,
    },
  ];

  return (
    <div role="radiogroup" className="space-y-2">
      {options.map((opt) => (
        <label
          key={opt.id}
          className={`flex items-start gap-2 p-2 rounded border cursor-pointer ${
            opt.disabled ? 'opacity-50 cursor-not-allowed' : 'hover:bg-[var(--hover-bg)]'
          }`}
          style={{
            borderColor:
              value === opt.id ? 'var(--accent)' : 'var(--border)',
          }}
        >
          <input
            type="radio"
            name="scope"
            value={opt.id}
            checked={value === opt.id}
            disabled={opt.disabled}
            onChange={() => onChange(opt.id)}
            className="mt-0.5"
          />
          <div>
            <div className="text-sm font-medium text-[var(--text)]">{opt.label}</div>
            <div className="text-xs text-[var(--text-muted)]">{opt.hint}</div>
          </div>
        </label>
      ))}
    </div>
  );
}
