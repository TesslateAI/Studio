import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { NavigationSidebar } from '../components/ui';

const settingsTabs = [
  { label: 'Profile', path: '/settings/profile' },
  { label: 'Preferences', path: '/settings/preferences' },
  { label: 'Security', path: '/settings/security' },
  { label: 'Deployment', path: '/settings/deployment' },
  { label: 'Billing', path: '/settings/billing' },
];

export function SettingsLayout() {
  const location = useLocation();
  const navigate = useNavigate();

  const isActive = (path: string) => location.pathname === path;

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
        <div className="h-10 flex items-center gap-1 flex-shrink-0 border-b border-[var(--border)]" style={{ paddingLeft: '7px', paddingRight: '10px' }}>
          {settingsTabs.map(tab => (
            <button key={tab.path} onClick={() => navigate(tab.path)} className={`btn ${isActive(tab.path) ? 'btn-tab-active' : 'btn-tab'}`}>
              {tab.label}
            </button>
          ))}
        </div>

        {/* Settings page content */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
