import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { teamsApi } from '../lib/api';
import type { TeamList } from '../lib/api';
import { useAuth } from './AuthContext';

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
    'agent.view', 'agent.manage',
  ]),
  viewer: new Set([
    'team.view', 'billing.view', 'project.list', 'project.view', 'file.read',
    'container.view', 'chat.view', 'deployment.view', 'git.view', 'kanban.view',
    'snapshot.view', 'credentials.view', 'channel.view', 'mcp.view', 'agent.view',
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
  /** Increments on every team switch — use in useEffect deps to trigger re-fetches. */
  teamSwitchKey: number;
}

const TeamContext = createContext<TeamContextValue | undefined>(undefined);

export function TeamProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [teams, setTeams] = useState<TeamList[]>([]);
  const [activeTeam, setActiveTeam] = useState<TeamList | null>(null);
  const [loading, setLoading] = useState(true);
  const [teamSwitchKey, setTeamSwitchKey] = useState(0);

  const loadTeams = useCallback(async () => {
    if (!isAuthenticated) {
      setTeams([]);
      setActiveTeam(null);
      setLoading(false);
      return;
    }
    try {
      const data = await teamsApi.list();
      setTeams(data);

      const savedSlug = localStorage.getItem('tesslate_active_team');
      const saved = data.find((t: TeamList) => t.slug === savedSlug);
      setActiveTeam(saved || data[0] || null);
    } catch {
      // API error — silently ignore
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated]);

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
        // Increment after backend acknowledges the switch so subsequent
        // API calls (getMyAgents, etc.) hit the correct team scope.
        setTeamSwitchKey((k) => k + 1);
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
      value={{ activeTeam, teams, switchTeam, membership, can, loading, refreshTeams: loadTeams, teamSwitchKey }}
    >
      {children}
    </TeamContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTeam() {
  const ctx = useContext(TeamContext);
  if (!ctx) throw new Error('useTeam must be used within TeamProvider');
  return ctx;
}
