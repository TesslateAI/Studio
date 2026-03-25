import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { NavigationSidebar } from '../components/ui';
import { useTeam } from '../contexts/TeamContext';

const settingsTabs = [
  { label: 'Profile', path: '/settings/profile' },
  { label: 'Preferences', path: '/settings/preferences' },
  { label: 'Security', path: '/settings/security' },
  { label: 'Deployment', path: '/settings/deployment' },
  { label: 'API Keys', path: '/settings/api-keys' },
];

export function SettingsLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { activeTeam, can } = useTeam();

  const isTeamSection = location.pathname.startsWith('/settings/team');

  const isActive = (path: string) => location.pathname === path;

  const isTeamSubActive = (path: string) =>
    path === '/settings/team'
      ? location.pathname === '/settings/team'
      : location.pathname === path;

  // Build team sub-tabs based on role
  const teamSubTabs = [
    { label: 'General', path: '/settings/team' },
    { label: 'Members', path: '/settings/team/members' },
    ...(can('billing.view') ? [{ label: 'Billing', path: '/settings/team/billing' }] : []),
    ...(can('audit.view') ? [{ label: 'Audit Log', path: '/settings/team/audit-log' }] : []),
  ];

  return (
    <div className="h-screen flex overflow-hidden bg-[var(--sidebar-bg)]">
      {/* Navigation Sidebar */}
      <div className="flex-shrink-0 h-full">
        <NavigationSidebar activePage="settings" />
      </div>

      {/* Main Content Area — floating panel */}
      <div
        className="flex-1 flex flex-col overflow-hidden app-panel"
        style={{
          borderRadius: 'var(--radius)',
          margin: 'var(--app-margin)',
          marginLeft: 0,
          border: 'var(--border-width) solid var(--border)',
          backgroundColor: 'var(--bg)',
        }}
      >
        {/* Settings sub-nav toolbar */}
        <div className="h-10 flex items-center gap-6 flex-shrink-0 border-b border-[var(--border)]" style={{ paddingLeft: '11px', paddingRight: '10px' }}>
          {settingsTabs.map(tab => (
            <button
              key={tab.path}
              onClick={() => navigate(tab.path)}
              className={`text-sm font-medium transition-colors ${
                isActive(tab.path)
                  ? 'text-[var(--text)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)]'
              }`}
            >
              {tab.label}
            </button>
          ))}

          {/* Team tab — simple button, team switching is in sidebar */}
          <button
            onClick={() => { if (!isTeamSection) navigate('/settings/team'); }}
            className={`text-sm font-medium transition-colors ${
              isTeamSection
                ? 'text-[var(--text)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text)]'
            }`}
          >
            {activeTeam?.name || 'Team'}
          </button>
        </div>

        {/* Team sub-tabs — shown when in /settings/team* */}
        {isTeamSection && (
          <div className="h-9 flex items-center gap-6 flex-shrink-0 border-b border-[var(--border)]" style={{ paddingLeft: '11px', paddingRight: '10px' }}>
            {teamSubTabs.map(tab => (
              <button
                key={tab.path}
                onClick={() => navigate(tab.path)}
                className={`text-sm font-medium transition-colors ${
                  isTeamSubActive(tab.path)
                    ? 'text-[var(--text)]'
                    : 'text-[var(--text-muted)] hover:text-[var(--text)]'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        )}

        {/* Settings page content */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
