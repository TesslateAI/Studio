import { BrowserRouter, Routes, Route, Navigate, useNavigate, useParams } from 'react-router-dom';
import toast, { Toaster, ToastBar } from 'react-hot-toast';
import { useState, useEffect, useCallback } from 'react';
import { useHotkeys } from 'react-hotkeys-hook';
import { ThemeProvider, useTheme } from './theme';
import { AuthProvider } from './contexts/AuthContext';
import { ChatPositionProvider } from './contexts/ChatPositionContext';
import { TeamProvider } from './contexts/TeamContext';
import { CommandProvider } from './contexts/CommandContext';
import { DashboardLayout } from './components/DashboardLayout';
import { PrivateRoute, PublicOnlyRoute } from './components/RouteGuards';
import Landing from './pages/Landing';
import NewLandingPage from './pages/NewLandingPage';
import Login from './pages/Login';
import Register from './pages/Register';
import ForgotPassword from './pages/ForgotPassword';
import ResetPassword from './pages/ResetPassword';
import Dashboard from './pages/Dashboard';
import ProjectPage from './pages/ProjectPage';
import ProjectSetup from './pages/ProjectSetup';
import Marketplace from './pages/Marketplace';
import MarketplaceDetail from './pages/MarketplaceDetail';
import MarketplaceAuthor from './pages/MarketplaceAuthor';
import MarketplaceBrowse from './pages/MarketplaceBrowse';
import Library from './pages/Library';
import Feedback from './pages/Feedback';
import AdminDashboard from './pages/AdminDashboard';
import AuthCallback from './pages/AuthCallback';
import OAuthLoginCallback from './pages/OAuthLoginCallback';
import Logout from './pages/Logout';
import ImportRedirect from './pages/ImportRedirect';
import Chat from './pages/Chat';
import Referrals from './pages/Referrals';
import { SettingsLayout } from './layouts/SettingsLayout';
import { MarketplaceLayout } from './layouts/MarketplaceLayout';
import ProfileSettings from './pages/settings/ProfileSettings';
import PreferencesSettings from './pages/settings/PreferencesSettings';
import SecuritySettings from './pages/settings/SecuritySettings';
import DeploymentSettings from './pages/settings/DeploymentSettings';
import BillingSettings from './pages/settings/BillingSettings';
import ApiKeysSettings from './pages/settings/ApiKeysSettings';
import { useReferralTracking } from './hooks/useReferralTracking';
import { useTaskNotifications } from './hooks/useTaskNotifications';
import { CommandPalette } from './components/CommandPalette';
import { KeyboardShortcutsModal } from './components/KeyboardShortcutsModal';
import MarketplaceSuccess from './pages/MarketplaceSuccess';
import UserProfilePage from './pages/UserProfile';

function CategoryRedirect() {
  const { category } = useParams();
  return <Navigate to={`/marketplace/browse/agent?category=${category}`} replace />;
}

function AppContent() {
  // Track referrals (must be inside BrowserRouter)
  useReferralTracking();

  // Enable task notifications via WebSocket
  useTaskNotifications();

  // Navigation and theme for global shortcuts
  const navigate = useNavigate();
  const { toggleTheme } = useTheme();

  // State for keyboard shortcuts modal
  const [showShortcuts, setShowShortcuts] = useState(false);

  // Global navigation shortcuts
  useHotkeys(
    'mod+l',
    (e) => {
      e.preventDefault();
      navigate('/library');
    },
    { enableOnFormTags: false }
  );

  useHotkeys(
    'mod+d',
    (e) => {
      e.preventDefault();
      navigate('/dashboard');
    },
    { enableOnFormTags: false }
  );

  useHotkeys(
    'mod+j',
    (e) => {
      e.preventDefault();
      navigate('/chat');
    },
    { enableOnFormTags: false }
  );

  useHotkeys(
    'mod+m',
    (e) => {
      e.preventDefault();
      navigate('/marketplace');
    },
    { enableOnFormTags: false }
  );

  useHotkeys(
    'mod+t',
    (e) => {
      e.preventDefault();
      toggleTheme();
    },
    { enableOnFormTags: false }
  );

  useHotkeys(
    'mod+comma',
    (e) => {
      e.preventDefault();
      navigate('/settings');
    },
    { enableOnFormTags: false }
  );

  // Ctrl+/ (or Cmd+/ on Mac) to open keyboard shortcuts panel
  // Using native keydown because react-hotkeys-hook doesn't reliably parse ctrl+/
  const handleShortcutsKey = useCallback((e: KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === '/') {
      e.preventDefault();
      setShowShortcuts((prev) => !prev);
    }
  }, []);

  useEffect(() => {
    document.addEventListener('keydown', handleShortcutsKey);
    return () => document.removeEventListener('keydown', handleShortcutsKey);
  }, [handleShortcutsKey]);

  return (
    <>
      {/* Global Command Palette (Cmd+K) */}
      <CommandPalette onShowShortcuts={() => setShowShortcuts(true)} />

      {/* Keyboard Shortcuts Modal */}
      <KeyboardShortcutsModal open={showShortcuts} onClose={() => setShowShortcuts(false)} />

      <Toaster
        position="top-right"
        containerStyle={{ top: 12, right: 12 }}
        toastOptions={{
          duration: 4000,
          style: {
            background: 'var(--surface)',
            color: 'var(--text)',
            border: 'var(--border-width) solid var(--border-hover)',
            borderRadius: 'var(--radius-medium)',
            padding: '10px 12px',
            fontSize: '12px',
            fontWeight: '500',
            maxWidth: '360px',
          },
          success: {
            duration: 3000,
            icon: (
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: 'var(--status-success)',
                  flexShrink: 0,
                }}
              />
            ),
          },
          error: {
            duration: 5000,
            icon: (
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: 'var(--status-error)',
                  flexShrink: 0,
                }}
              />
            ),
          },
          loading: {
            icon: (
              <span
                style={{
                  width: 14,
                  height: 14,
                  border: '2px solid var(--border)',
                  borderTopColor: 'var(--primary)',
                  borderRadius: '50%',
                  animation: 'spin 1s linear infinite',
                  flexShrink: 0,
                }}
              />
            ),
          },
        }}
      >
        {(t) => (
          <ToastBar
            toast={t}
            style={{ padding: 0, background: 'none', border: 'none', boxShadow: 'none' }}
          >
            {({ icon, message }) => (
              <>
                {icon}
                <div style={{ flex: 1 }}>{message}</div>
                {t.type !== 'loading' && (
                  <button
                    onClick={() => toast.dismiss(t.id)}
                    className="shrink-0 p-0.5 rounded-[var(--radius-small)] text-[var(--text-subtle)] hover:text-[var(--text-muted)] hover:bg-[var(--surface-hover)] transition-colors"
                    aria-label="Dismiss notification"
                  >
                    <svg width="12" height="12" viewBox="0 0 14 14" fill="none">
                      <path
                        d="M3 3L11 11M11 3L3 11"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                      />
                    </svg>
                  </button>
                )}
              </>
            )}
          </ToastBar>
        )}
      </Toaster>
      <Routes>
        <Route path="/" element={<NewLandingPage />} />
        <Route path="/landing-old" element={<Landing />} />
        <Route
          path="/login"
          element={
            <PublicOnlyRoute>
              <Login />
            </PublicOnlyRoute>
          }
        />
        <Route
          path="/register"
          element={
            <PublicOnlyRoute>
              <Register />
            </PublicOnlyRoute>
          }
        />
        <Route path="/import" element={<ImportRedirect />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/logout" element={<Logout />} />
        <Route
          path="/referral"
          element={
            <PrivateRoute>
              <Referrals />
            </PrivateRoute>
          }
        />
        <Route
          path="/referrals"
          element={
            <PrivateRoute>
              <Referrals />
            </PrivateRoute>
          }
        />

        {/* Public @username profile resolver — redirects to /marketplace/creator/{uuid} */}
        <Route path="/@:username" element={<UserProfilePage />} />

        {/* Marketplace Routes - Adaptive layout based on auth state */}
        {/* Non-blocking: defaults to public view, upgrades to authenticated view if logged in */}
        <Route element={<MarketplaceLayout />}>
          <Route path="/marketplace" element={<Marketplace />} />
          <Route path="/marketplace/category/:category" element={<CategoryRedirect />} />
          <Route path="/marketplace/browse/:itemType" element={<MarketplaceBrowse />} />
          <Route path="/marketplace/:slug" element={<MarketplaceDetail />} />
          <Route path="/marketplace/creator/:userId" element={<MarketplaceAuthor />} />
        </Route>

        {/* Dashboard Layout Routes - These share the NavigationSidebar */}
        <Route
          element={
            <PrivateRoute>
              <DashboardLayout />
            </PrivateRoute>
          }
        >
          <Route path="/chat" element={<Chat />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/marketplace/success" element={<MarketplaceSuccess />} />
          <Route path="/library" element={<Library />} />
          <Route path="/feedback" element={<Feedback />} />
        </Route>

        {/* Standalone Routes */}
        <Route
          path="/project/:slug"
          element={
            <PrivateRoute>
              <ProjectPage />
            </PrivateRoute>
          }
        />
        <Route
          path="/project/:slug/builder"
          element={
            <PrivateRoute>
              <ProjectPage />
            </PrivateRoute>
          }
        />
        <Route
          path="/project/:slug/setup"
          element={
            <PrivateRoute>
              <ProjectSetup />
            </PrivateRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <PrivateRoute>
              <AdminDashboard />
            </PrivateRoute>
          }
        />

        {/* Settings Routes - Has its own layout with settings sidebar */}
        <Route
          path="/settings"
          element={
            <PrivateRoute>
              <SettingsLayout />
            </PrivateRoute>
          }
        >
          <Route index element={<Navigate to="/settings/profile" replace />} />
          <Route path="profile" element={<ProfileSettings />} />
          <Route path="preferences" element={<PreferencesSettings />} />
          <Route path="security" element={<SecuritySettings />} />
          <Route path="deployment" element={<DeploymentSettings />} />
          <Route path="api-keys" element={<ApiKeysSettings />} />
          <Route path="billing" element={<BillingSettings />} />
        </Route>

        {/* Billing redirect - all billing is now in /settings/billing */}
        <Route path="/billing/*" element={<Navigate to="/settings/billing" replace />} />
        <Route
          path="/auth/github/callback"
          element={
            <PrivateRoute>
              <AuthCallback />
            </PrivateRoute>
          }
        />
        <Route path="/oauth/callback" element={<OAuthLoginCallback />} />
      </Routes>

      {/* WALKTHROUGH DISABLED - Was causing logout issues */}
    </>
  );
}

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <TeamProvider>
        <ChatPositionProvider>
          <CommandProvider>
            <style>{`
              @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
              }
            `}</style>
            <BrowserRouter>
              <AppContent />
            </BrowserRouter>
          </CommandProvider>
        </ChatPositionProvider>
        </TeamProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
