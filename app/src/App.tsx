import { BrowserRouter, Routes, Route, Navigate, useNavigate, useParams } from 'react-router-dom';
import toast, { Toaster, ToastBar } from 'react-hot-toast';
import { useState, useEffect, useCallback } from 'react';
import { useHotkeys } from 'react-hotkeys-hook';
import { ThemeProvider, useTheme } from './theme';
import { AuthProvider } from './contexts/AuthContext';
import { ChatPositionProvider } from './contexts/ChatPositionContext';
import { TeamProvider } from './contexts/TeamContext';
import { AppsProvider } from './contexts/AppsContext';
import { WalletProvider } from './contexts/WalletContext';
import { AdminProvider } from './contexts/AdminContext';
import { CommandProvider } from './contexts/CommandContext';
import { FeatureFlagProvider } from './contexts/FeatureFlagContext';
import { useFeatureFlags } from './contexts/useFeatureFlag';
import { DashboardLayout } from './components/DashboardLayout';
import { PrivateRoute, PublicOnlyRoute } from './components/RouteGuards';
import Landing from './pages/Landing';
import NewLandingPage from './pages/NewLandingPage';
import Login from './pages/Login';
import MagicLinkConsume from './pages/MagicLinkConsume';
import Register from './pages/Register';
import ForgotPassword from './pages/ForgotPassword';
import ResetPassword from './pages/ResetPassword';
import Dashboard from './pages/Dashboard';
import Home from './pages/Home';
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
import TeamSettingsPage from './pages/settings/TeamSettingsPage';
import TeamMembersPage from './pages/settings/TeamMembersPage';
import AuditLogPage from './pages/settings/AuditLogPage';
import ConnectionsSettings from './pages/settings/ConnectionsSettings';
import ChannelsSettings from './pages/settings/ChannelsSettings';
import SchedulesSettings from './pages/settings/SchedulesSettings';
import InviteAcceptPage from './pages/InviteAcceptPage';
import { useReferralTracking } from './hooks/useReferralTracking';
import { useTaskNotifications } from './hooks/useTaskNotifications';
import { CommandPalette } from './components/CommandPalette';
import { KeyboardShortcutsModal } from './components/KeyboardShortcutsModal';
import MarketplaceSuccess from './pages/MarketplaceSuccess';
import UserProfilePage from './pages/UserProfile';
// Tesslate Apps (Waves 4-5)
import AppsMarketplacePage from './pages/AppsMarketplacePage';
import AppDetailPage from './pages/AppDetailPage';
import BundleDetailPage from './pages/BundleDetailPage';
import MyAppsPage from './pages/MyAppsPage';
import AppWorkspacePage from './pages/AppWorkspacePage';
import AppSourceBrowserPage from './pages/AppSourceBrowserPage';
import ForkPage from './pages/ForkPage';
import CreatorStudioPage from './pages/CreatorStudioPage';
import CreatorAppPublishPage from './pages/CreatorAppPublishPage';
import CreatorBillingPage from './pages/CreatorBillingPage';
import AdminMarketplaceReviewPage from './pages/AdminMarketplaceReviewPage';
import AdminSubmissionWorkbenchPage from './pages/AdminSubmissionWorkbenchPage';
import AdminYankCenterPage from './pages/AdminYankCenterPage';
import AdminCreatorReputationPage from './pages/AdminCreatorReputationPage';
import AdminAdversarialSuitePage from './pages/AdminAdversarialSuitePage';

function CategoryRedirect() {
  const { category } = useParams();
  return <Navigate to={`/marketplace/browse/agent?category=${category}`} replace />;
}

function LandingRoute() {
  const { flags, loading } = useFeatureFlags();
  // While flags are loading, render the landing page to match the `true`
  // default — avoids a redirect flicker for the common case.
  if (!loading && flags.enable_landing_page === false) {
    return <Navigate to="/login" replace />;
  }
  return <NewLandingPage />;
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
        <Route path="/" element={<LandingRoute />} />
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
        <Route path="/auth/magic" element={<MagicLinkConsume />} />
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
          <Route path="/home" element={<Home />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/marketplace/success" element={<MarketplaceSuccess />} />
          <Route path="/library" element={<Library />} />
          <Route path="/feedback" element={<Feedback />} />

          {/* Tesslate Apps — browse/detail/install (order matters: bundles and installed before :appId) */}
          <Route path="/apps" element={<AppsMarketplacePage />} />
          <Route path="/apps/bundles/:bundleId" element={<BundleDetailPage />} />
          <Route path="/apps/installed" element={<MyAppsPage />} />
          <Route path="/apps/installed/:appInstanceId/workspace" element={<AppWorkspacePage />} />
          <Route path="/apps/:appId/source" element={<AppSourceBrowserPage />} />
          <Route path="/apps/:appId/fork" element={<ForkPage />} />
          <Route path="/apps/:appId" element={<AppDetailPage />} />

          {/* Creator Studio */}
          <Route path="/creator" element={<CreatorStudioPage />} />
          <Route path="/creator/publish/:appId" element={<CreatorAppPublishPage />} />
          <Route path="/creator/billing" element={<CreatorBillingPage />} />

          {/* Admin Marketplace */}
          <Route path="/admin/marketplace" element={<AdminMarketplaceReviewPage />} />
          <Route path="/admin/marketplace/submissions/:submissionId" element={<AdminSubmissionWorkbenchPage />} />
          <Route path="/admin/marketplace/yanks" element={<AdminYankCenterPage />} />
          <Route path="/admin/marketplace/reputation" element={<AdminCreatorReputationPage />} />
          <Route path="/admin/marketplace/adversarial" element={<AdminAdversarialSuitePage />} />
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
          {/* /settings/connectors moved to Library → Connectors (#307). */}
          <Route path="connectors" element={<Navigate to="/library?tab=connectors" replace />} />
          <Route path="api-keys" element={<ApiKeysSettings />} />
          <Route path="billing" element={<Navigate to="/settings/team/billing" replace />} />
          <Route path="messaging" element={<ConnectionsSettings />} />
          <Route path="messaging/channels" element={<ChannelsSettings />} />
          <Route path="messaging/schedules" element={<SchedulesSettings />} />
          <Route path="team" element={<TeamSettingsPage />} />
          <Route path="team/members" element={<TeamMembersPage />} />
          <Route path="team/billing" element={<BillingSettings />} />
          <Route path="team/audit-log" element={<AuditLogPage />} />
        </Route>

        {/* Billing redirect - all billing is now under team */}
        <Route path="/billing/*" element={<Navigate to="/settings/team/billing" replace />} />
        <Route
          path="/auth/github/callback"
          element={
            <PrivateRoute>
              <AuthCallback />
            </PrivateRoute>
          }
        />
        <Route path="/oauth/callback" element={<OAuthLoginCallback />} />
        <Route path="/invite/:token" element={<InviteAcceptPage />} />
      </Routes>

      {/* WALKTHROUGH DISABLED - Was causing logout issues */}
    </>
  );
}

function App() {
  return (
    <ThemeProvider>
      <FeatureFlagProvider>
        <AuthProvider>
          <TeamProvider>
            <AppsProvider>
              <WalletProvider>
                <AdminProvider>
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
                </AdminProvider>
              </WalletProvider>
            </AppsProvider>
          </TeamProvider>
        </AuthProvider>
      </FeatureFlagProvider>
    </ThemeProvider>
  );
}

export default App;
