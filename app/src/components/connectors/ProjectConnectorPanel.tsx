import { useCallback, useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { ArrowUUpLeft, GitBranch, Plug } from '@phosphor-icons/react';
import { marketplaceApi } from '../../lib/api';
import { LoadingSpinner } from '../PulsingGridSpinner';
import { useTeam } from '../../contexts/TeamContext';

interface InstalledConfig {
  id: string;
  server_name?: string | null;
  server_slug?: string | null;
  is_active: boolean;
  scope_level?: string;
}

interface Props {
  projectId: string;
}

/**
 * Lists effective connectors for a project and lets admins/editors override a
 * team or personal connector into a project-scoped copy, or remove an
 * existing override.
 */
export function ProjectConnectorPanel({ projectId }: Props) {
  const { can } = useTeam();
  const canManage = can('connectors.manage_project');
  const [configs, setConfigs] = useState<InstalledConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await marketplaceApi.getInstalledMcpServers();
      setConfigs(list);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to load connectors');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const override = async (c: InstalledConfig) => {
    setWorking(c.id);
    try {
      await marketplaceApi.overrideMcpForProject(c.id, projectId);
      toast.success(`Override created for ${c.server_name || 'connector'}`);
      await load();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to override');
    } finally {
      setWorking(null);
    }
  };

  const removeOverride = async (c: InstalledConfig) => {
    if (!window.confirm(`Remove project override for ${c.server_name}? Falls back to team/personal default.`)) {
      return;
    }
    setWorking(c.id);
    try {
      await marketplaceApi.removeProjectMcpOverride(c.id);
      toast.success('Override removed');
      await load();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to remove override');
    } finally {
      setWorking(null);
    }
  };

  if (loading) return <div className="p-6"><LoadingSpinner /></div>;

  const projectRows = configs.filter((c) => c.scope_level === 'project');
  const inheritedRows = configs.filter((c) => c.scope_level !== 'project');

  return (
    <div className="p-6 max-w-3xl">
      <div className="flex items-start gap-2 mb-4">
        <GitBranch size={18} />
        <div>
          <h2 className="text-base font-semibold text-[var(--text)]">Project connectors</h2>
          <p className="text-xs text-[var(--text-muted)]">
            Connectors scoped to this project override team or personal ones with the same provider.
          </p>
        </div>
      </div>

      {/* Project-scoped overrides */}
      <section className="mb-6">
        <div className="text-xs font-semibold uppercase text-[var(--text-muted)] mb-2">
          Project overrides
        </div>
        {projectRows.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)] italic">
            No project-specific overrides yet.
          </p>
        ) : (
          <ul className="space-y-1">
            {projectRows.map((c) => (
              <li
                key={c.id}
                className="flex items-center justify-between px-3 py-2 border rounded"
                style={{ borderColor: 'var(--border)' }}
              >
                <span className="text-sm text-[var(--text)] flex items-center gap-2">
                  <Plug size={14} /> {c.server_name || c.server_slug}
                </span>
                {canManage && (
                  <button
                    onClick={() => removeOverride(c)}
                    disabled={working === c.id}
                    className="text-xs px-2 py-1 rounded border flex items-center gap-1 disabled:opacity-50"
                    style={{ borderColor: 'var(--border)' }}
                  >
                    <ArrowUUpLeft size={12} /> Remove override
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Inherited — team + personal */}
      <section>
        <div className="text-xs font-semibold uppercase text-[var(--text-muted)] mb-2">
          Inherited
        </div>
        {inheritedRows.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)] italic">
            No inherited connectors. Connect one from Settings → Connectors.
          </p>
        ) : (
          <ul className="space-y-1">
            {inheritedRows.map((c) => (
              <li
                key={c.id}
                className="flex items-center justify-between px-3 py-2 border rounded"
                style={{ borderColor: 'var(--border)' }}
              >
                <span className="text-sm text-[var(--text)] flex items-center gap-2">
                  <Plug size={14} /> {c.server_name || c.server_slug}
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--hover-bg)] text-[var(--text-muted)]">
                    {c.scope_level || 'user'}
                  </span>
                </span>
                {canManage && (
                  <button
                    onClick={() => override(c)}
                    disabled={working === c.id}
                    className="text-xs px-2 py-1 rounded border disabled:opacity-50"
                    style={{ borderColor: 'var(--border)' }}
                  >
                    {working === c.id ? 'Overriding...' : 'Override for project'}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
