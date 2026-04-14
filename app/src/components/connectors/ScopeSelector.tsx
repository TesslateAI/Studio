import { useTeam } from '../../contexts/TeamContext';

type Scope = 'team' | 'user' | 'project';

interface Props {
  value: Scope;
  onChange: (scope: Scope) => void;
  projectId?: string;
}

export function ScopeSelector({ value, onChange, projectId }: Props) {
  const { can } = useTeam();
  const canTeam = can('connectors.manage_team');
  const canProject = can('connectors.manage_project') && !!projectId;

  const options: Array<{ id: Scope; label: string; hint: string; disabled: boolean }> = [
    {
      id: 'team',
      label: 'Team default',
      hint: 'Everyone in the team uses this connector unless they override it.',
      disabled: !canTeam,
    },
    {
      id: 'user',
      label: 'Personal',
      hint: 'Only your chats and agents see this connector.',
      disabled: false,
    },
    {
      id: 'project',
      label: 'This project only',
      hint: 'Scoped to the current project — overrides team or personal.',
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
