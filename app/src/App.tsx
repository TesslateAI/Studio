import { BrowserRouter, Routes, Route, Navigate, useNavigate, useParams } from 'react-router-dom';
import toast, { Toaster, ToastBar } from 'react-hot-toast';
import { useState, useEffect, useCallback } from 'react';
import { useHotkeys } from 'react-hotkeys-hook';
import { ThemeProvider, useTheme } from './theme';
import { AuthProvider } from './contexts/AuthContext';
import { ChatPositionProvider } from './contexts/ChatPositionContext';
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
import Project from './pages/Project';
import ProjectSetup from './pages/ProjectSetup';
import { ProjectGraphCanvas } from './pages/ProjectGraphCanvas';
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
import Referrals from './pages/Referrals';
import { SettingsLayout } from './layouts/SettingsLayout';
import { MarketplaceLayout } from './layouts/MarketplaceLayout';
import ProfileSettings from './pages/settings/ProfileSettings';
import PreferencesSettings from './pages/settings/PreferencesSettings';
import SecuritySettings from './pages/settings/SecuritySettings';
import DeploymentSettings from './pages/settings/DeploymentSettings';
import BillingSettings from './pages/settings/BillingSettings';
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
        containerStyle={{
          top: 80, // Clear the header + some margin, works on all screen sizes
        }}
        toastOptions={{
          // Default options
          duration: 4000,
          className: 'custom-toast',
          style: {
            background: 'var(--surface)',
            color: 'var(--text)',
            border: '1px solid rgba(255, 107, 0, 0.2)',
            borderRadius: '16px',
            padding: '16px',
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
            backdropFilter: 'blur(12px)',
            fontSize: '14px',
            fontWeight: '500',
          },
          // Success toast
          success: {
            duration: 3000,
            icon: (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <circle cx="10" cy="10" r="10" fill="#10b981" />
                <path
                  d="M6 10L8.5 12.5L14 7"
                  stroke="white"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            ),
            style: {
              background: 'var(--surface)',
              color: 'var(--text)',
              border: '1px solid rgba(16, 185, 129, 0.3)',
              borderRadius: '16px',
              padding: '16px',
              boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
            },
          },
          // Error toast
          error: {
            duration: 5000,
            icon: (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <circle cx="10" cy="10" r="10" fill="#ef4444" />
                <path
                  d="M7 7L13 13M13 7L7 13"
                  stroke="white"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
            ),
            style: {
              background: 'var(--surface)',
              color: 'var(--text)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              borderRadius: '16px',
              padding: '16px',
              boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
            },
          },
          // Loading toast - custom spinner
          loading: {
            icon: (
              <svg
                width="20"
                height="20"
                viewBox="0 0 50 50"
                style={{
                  animation: 'spin 1s linear infinite',
                }}
              >
                <circle
                  cx="25"
                  cy="25"
                  r="20"
                  fill="none"
                  stroke="rgba(255, 107, 0, 0.3)"
                  strokeWidth="5"
                />
                <circle
                  cx="25"
                  cy="25"
                  r="20"
                  fill="none"
                  stroke="#ff6b00"
                  strokeWidth="5"
                  strokeDasharray="31.4 94.2"
                  strokeLinecap="round"
                />
              </svg>
            ),
            style: {
              background: 'var(--surface)',
              color: 'var(--text)',
              border: '1px solid rgba(255, 107, 0, 0.3)',
              borderRadius: '16px',
              padding: '16px',
              boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
            },
          },
        }}
      >
        {(t) => (
          <ToastBar
            toast={t}
            style={{
              padding: 0,
              background: 'none',
              border: 'none',
              boxShadow: 'none',
            }}
          >
            {({ icon, message }) => (
              <>
                {icon}
                <div style={{ flex: 1 }}>{message}</div>
                {t.type !== 'loading' && (
                  <button
                    onClick={() => toast.dismiss(t.id)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-secondary, #999)',
                      cursor: 'pointer',
                      padding: '2px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      borderRadius: '4px',
                      flexShrink: 0,
                      transition: 'color 0.15s, background 0.15s',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.color = 'var(--text)';
                      e.currentTarget.style.background = 'rgba(255,255,255,0.1)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.color = 'var(--text-secondary, #999)';
                      e.currentTarget.style.background = 'none';
                    }}
                    aria-label="Dismiss notification"
                  >
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
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
              <ProjectGraphCanvas />
            </PrivateRoute>
          }
        />
        <Route
          path="/project/:slug/builder"
          element={
            <PrivateRoute>
              <Project />
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
          <Route path="api-keys" element={<Navigate to="/library?tab=models" replace />} />
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
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
