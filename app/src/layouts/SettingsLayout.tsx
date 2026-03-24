import { useState, useRef, useEffect } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { ChevronDown, Check } from 'lucide-react';
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
  const { activeTeam, teams, switchTeam, can } = useTeam();
  const [teamDropdownOpen, setTeamDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

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

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setTeamDropdownOpen(false);
      }
    };
    if (teamDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [teamDropdownOpen]);

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
        <div
          className="h-10 flex items-center gap-1 flex-shrink-0 border-b border-[var(--border)]"
          style={{ paddingLeft: '7px', paddingRight: '10px' }}
        >
          {settingsTabs.map((tab) => (
            <button
              key={tab.path}
              onClick={() => navigate(tab.path)}
              className={`btn ${isActive(tab.path) ? 'btn-tab-active' : 'btn-tab'}`}
            >
              {tab.label}
            </button>
          ))}

          {/* Team tab with dropdown */}
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => {
                if (!isTeamSection) navigate('/settings/team');
                setTeamDropdownOpen(!teamDropdownOpen);
              }}
              className={`btn ${isTeamSection ? 'btn-tab-active' : 'btn-tab'} gap-1.5`}
            >
              {activeTeam?.name || 'Team'}
              {teams.length > 1 && <ChevronDown size={12} className="opacity-50" />}
            </button>

            {/* Team switcher dropdown */}
            {teamDropdownOpen && teams.length > 1 && (
              <div className="absolute top-full left-0 mt-1 z-50 min-w-[200px] bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] p-1.5 shadow-lg">
                {teams.map(team => (
                  <button
                    key={team.slug}
                    onClick={() => {
                      switchTeam(team.slug);
                      setTeamDropdownOpen(false);
                      if (!isTeamSection) navigate('/settings/team');
                    }}
                    className={`w-full flex items-center gap-2 px-3 py-1.5 rounded-[var(--radius-small)] text-xs transition-colors ${
                      activeTeam?.slug === team.slug
                        ? 'bg-[var(--surface-hover)] text-[var(--text)]'
                        : 'hover:bg-[var(--surface-hover)] text-[var(--text-muted)]'
                    }`}
                  >
                    {/* Team avatar */}
                    {team.avatar_url ? (
                      <img src={team.avatar_url} alt={team.name} className="w-5 h-5 rounded-full object-cover flex-shrink-0" />
                    ) : (
                      <div className="w-5 h-5 rounded-full bg-[var(--primary)]/20 flex items-center justify-center text-[9px] font-bold text-[var(--primary)] flex-shrink-0">
                        {team.name.charAt(0).toUpperCase()}
                      </div>
                    )}
                    <span className="truncate flex-1 text-left">{team.name}</span>
                    {team.is_personal && <span className="text-[10px] text-[var(--text-subtle)]">Personal</span>}
                    {activeTeam?.slug === team.slug && <Check size={12} className="text-[var(--primary)] flex-shrink-0" />}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Team sub-tabs — shown when in /settings/team* */}
        {isTeamSection && (
          <div className="h-9 flex items-center gap-1 flex-shrink-0 border-b border-[var(--border)] bg-[var(--surface)]" style={{ paddingLeft: '7px', paddingRight: '10px' }}>
            {teamSubTabs.map(tab => (
              <button key={tab.path} onClick={() => navigate(tab.path)} className={`btn ${isTeamSubActive(tab.path) ? 'btn-tab-active' : 'btn-tab'} text-xs`}>
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
