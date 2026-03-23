import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { teamsApi } from '../lib/api';
import type { TeamList } from '../lib/api';

/** Client-side mirror of backend ROLE_PERMISSIONS for UX-only gating. */
const ROLE_PERMISSIONS: Record<string, Set<string>> = {
  admin: new Set(['*']),
  editor: new Set([
    'team.view', 'billing.view', 'billing.usage', 'project.list', 'project.create',
    'project.view', 'project.edit', 'project.settings', 'file.read', 'file.write',
    'file.delete', 'container.view', 'container.create', 'container.edit',
    'container.start_stop', 'chat.view', 'chat.send', 'chat.delete',
    'deployment.view', 'deployment.create', 'git.view', 'git.write',
    'kanban.view', 'kanban.edit', 'snapshot.view', 'snapshot.create',
    'snapshot.restore', 'terminal.access', 'credentials.view', 'credentials.manage',
    'channel.view', 'channel.manage', 'mcp.view', 'mcp.manage',
    'agent.view', 'agent.manage', 'audit.view',
  ]),
  viewer: new Set([
    'team.view', 'billing.view', 'project.list', 'project.view', 'file.read',
    'container.view', 'chat.view', 'deployment.view', 'git.view', 'kanban.view',
    'snapshot.view', 'channel.view', 'mcp.view', 'agent.view', 'audit.view',
  ]),
};

interface TeamContextValue {
  activeTeam: TeamList | null;
  teams: TeamList[];
  switchTeam: (teamSlug: string) => Promise<void>;
  membership: { role: string } | null;
  /** Frontend-only permission check (UX gating — backend always enforces). */
  can: (permission: string) => boolean;
  loading: boolean;
  refreshTeams: () => Promise<void>;
}

const TeamContext = createContext<TeamContextValue | undefined>(undefined);

export function TeamProvider({ children }: { children: React.ReactNode }) {
  const [teams, setTeams] = useState<TeamList[]>([]);
  const [activeTeam, setActiveTeam] = useState<TeamList | null>(null);
  const [loading, setLoading] = useState(true);

  const loadTeams = useCallback(async () => {
    try {
      const data = await teamsApi.list();
      setTeams(data);

      const savedSlug = localStorage.getItem('tesslate_active_team');
      const saved = data.find((t) => t.slug === savedSlug);
      setActiveTeam(saved || data[0] || null);
    } catch {
      // Not logged in or API error — silently ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTeams();
  }, [loadTeams]);

  const switchTeam = useCallback(
    async (teamSlug: string) => {
      const team = teams.find((t) => t.slug === teamSlug);
      if (team) {
        setActiveTeam(team);
        localStorage.setItem('tesslate_active_team', teamSlug);
        try {
          await teamsApi.switch(teamSlug);
        } catch {
          /* non-blocking */
        }
      }
    },
    [teams]
  );

  const membership = activeTeam?.role ? { role: activeTeam.role } : null;

  const can = useCallback(
    (permission: string) => {
      if (!membership) return false;
      const perms = ROLE_PERMISSIONS[membership.role];
      if (!perms) return false;
      if (perms.has('*')) return true;
      return perms.has(permission);
    },
    [membership]
  );

  return (
    <TeamContext.Provider
      value={{ activeTeam, teams, switchTeam, membership, can, loading, refreshTeams: loadTeams }}
    >
      {children}
    </TeamContext.Provider>
  );
}

export function useTeam() {
  const ctx = useContext(TeamContext);
  if (!ctx) throw new Error('useTeam must be used within TeamProvider');
  return ctx;
}
