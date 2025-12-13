import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import toast from 'react-hot-toast';
import { useState, useEffect } from 'react';
import { ThemeProvider } from './theme';
import Layout from './components/Layout';
import { DashboardLayout } from './components/DashboardLayout';
import Landing from './pages/Landing';
import NewLandingPage from './pages/NewLandingPage';
import TerminalLandingPage from './pages/TerminalLandingPage';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import Project from './pages/Project';
import { ProjectGraphCanvas } from './pages/ProjectGraphCanvas';
import Marketplace from './pages/Marketplace';
import Library from './pages/Library';
import Feedback from './pages/Feedback';
import AdminDashboard from './pages/AdminDashboard';
import AuthCallback from './pages/AuthCallback';
import OAuthLoginCallback from './pages/OAuthLoginCallback';
import Logout from './pages/Logout';
import Referrals from './pages/Referrals';
import AccountSettings from './pages/AccountSettings';
import { Walkthrough } from './components/Walkthrough';
import { useReferralTracking } from './hooks/useReferralTracking';
import { useTaskNotifications } from './hooks/useTaskNotifications';
import axios from 'axios';
// Billing components
import SubscriptionPlans from './components/billing/SubscriptionPlans';
import BillingDashboard from './components/billing/BillingDashboard';
import UsageDashboard from './components/billing/UsageDashboard';
import TransactionHistory from './components/billing/TransactionHistory';
import MarketplaceSuccess from './pages/MarketplaceSuccess';

const API_URL = import.meta.env.VITE_API_URL || '';

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);

  useEffect(() => {
    // Check authentication by trying to get current user
    // This works for both Bearer token (localStorage) and cookie-based auth
    const checkAuth = async () => {
      try {
        // Check if we have a token in localStorage (regular login)
        const token = localStorage.getItem('token');
        if (token) {
          setIsAuthenticated(true);
          return;
        }

        // No token in localStorage, check if we have a valid cookie (OAuth login)
        const response = await axios.get(`${API_URL}/api/users/me`, {
          withCredentials: true, // Send cookies
        });

        if (response.status === 200) {
          setIsAuthenticated(true);
        } else {
          setIsAuthenticated(false);
        }
      } catch (error) {
        setIsAuthenticated(false);
      }
    };

    checkAuth();
  }, []);

  // Loading state - show nothing while checking
  if (isAuthenticated === null) {
    return null;
  }

  // Not authenticated - redirect to login
  if (!isAuthenticated) {
    return <Navigate to="/login" />;
  }

  // Authenticated - show protected content
  return <>{children}</>;
}

function AppContent() {
  // Track referrals (must be inside BrowserRouter)
  useReferralTracking();

  // Enable task notifications via WebSocket
  useTaskNotifications();

  return (
    <>
        <Toaster
          position="top-right"
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
                  <circle cx="10" cy="10" r="10" fill="#10b981"/>
                  <path d="M6 10L8.5 12.5L14 7" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
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
                  <circle cx="10" cy="10" r="10" fill="#ef4444"/>
                  <path d="M7 7L13 13M13 7L7 13" stroke="white" strokeWidth="2" strokeLinecap="round"/>
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
                    animation: 'spin 1s linear infinite'
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
        />
        <Routes>
          <Route path="/" element={<TerminalLandingPage />} />
          <Route path="/landing-new" element={<NewLandingPage />} />
          <Route path="/landing-old" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/logout" element={<Logout />} />
          <Route path="/referral" element={<Referrals />} />
          <Route path="/referrals" element={<Referrals />} />

          {/* Dashboard Layout Routes - These share the NavigationSidebar */}
          <Route
            element={
              <PrivateRoute>
                <DashboardLayout />
              </PrivateRoute>
            }
          >
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/marketplace" element={<Marketplace />} />
            <Route path="/marketplace/success" element={<MarketplaceSuccess />} />
            <Route path="/library" element={<Library />} />
            <Route path="/feedback" element={<Feedback />} />
            <Route path="/settings" element={<AccountSettings />} />
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
            path="/admin"
            element={
              <PrivateRoute>
                <AdminDashboard />
              </PrivateRoute>
            }
          />
          {/* Account Settings Route */}
          <Route
            path="/settings"
            element={
              <PrivateRoute>
                <AccountSettings />
              </PrivateRoute>
            }
          />
          {/* Billing Routes */}
          <Route
            path="/billing"
            element={
              <PrivateRoute>
                <BillingDashboard />
              </PrivateRoute>
            }
          />
          <Route
            path="/billing/plans"
            element={
              <PrivateRoute>
                <SubscriptionPlans />
              </PrivateRoute>
            }
          />
          <Route
            path="/billing/usage"
            element={
              <PrivateRoute>
                <UsageDashboard />
              </PrivateRoute>
            }
          />
          <Route
            path="/billing/transactions"
            element={
              <PrivateRoute>
                <TransactionHistory />
              </PrivateRoute>
            }
          />
          {/* Success/Cancel redirect pages */}
          <Route
            path="/billing/success"
            element={
              <PrivateRoute>
                <div className="min-h-screen flex items-center justify-center bg-gray-50">
                  <div className="bg-white rounded-lg shadow-lg p-8 max-w-md text-center">
                    <div className="mb-4">
                      <svg className="mx-auto h-16 w-16 text-green-500" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                      </svg>
                    </div>
                    <h2 className="text-2xl font-bold text-gray-900 mb-2">Payment Successful!</h2>
                    <p className="text-gray-600 mb-6">Your payment has been processed successfully.</p>
                    <a href="/billing" className="inline-block px-6 py-3 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition">
                      Go to Billing Dashboard
                    </a>
                  </div>
                </div>
              </PrivateRoute>
            }
          />
          <Route
            path="/billing/credits/success"
            element={
              <PrivateRoute>
                <div className="min-h-screen flex items-center justify-center bg-gray-50">
                  <div className="bg-white rounded-lg shadow-lg p-8 max-w-md text-center">
                    <div className="mb-4">
                      <svg className="mx-auto h-16 w-16 text-green-500" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                      </svg>
                    </div>
                    <h2 className="text-2xl font-bold text-gray-900 mb-2">Credits Added!</h2>
                    <p className="text-gray-600 mb-6">Your credits have been added to your account successfully.</p>
                    <a href="/library?tab=credits" className="inline-block px-6 py-3 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition">
                      View Credits
                    </a>
                  </div>
                </div>
              </PrivateRoute>
            }
          />
          <Route
            path="/billing/credits/success"
            element={
              <PrivateRoute>
                <div className="min-h-screen flex items-center justify-center bg-gray-50">
                  <div className="bg-white rounded-lg shadow-lg p-8 max-w-md text-center">
                    <div className="mb-4">
                      <svg className="mx-auto h-16 w-16 text-green-500" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                      </svg>
                    </div>
                    <h2 className="text-2xl font-bold text-gray-900 mb-2">Credits Added!</h2>
                    <p className="text-gray-600 mb-6">Your credits have been added to your account successfully.</p>
                    <a href="/library?tab=credits" className="inline-block px-6 py-3 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition">
                      View Credits
                    </a>
                  </div>
                </div>
              </PrivateRoute>
            }
          />
          <Route
            path="/billing/cancel"
            element={
              <PrivateRoute>
                <div className="min-h-screen flex items-center justify-center bg-gray-50">
                  <div className="bg-white rounded-lg shadow-lg p-8 max-w-md text-center">
                    <div className="mb-4">
                      <svg className="mx-auto h-16 w-16 text-yellow-500" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                      </svg>
                    </div>
                    <h2 className="text-2xl font-bold text-gray-900 mb-2">Payment Cancelled</h2>
                    <p className="text-gray-600 mb-6">Your payment was cancelled. No charges have been made.</p>
                    <a href="/billing" className="inline-block px-6 py-3 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition">
                      Go to Billing Dashboard
                    </a>
                  </div>
                </div>
              </PrivateRoute>
            }
          />
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
      <style>{`
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
      <BrowserRouter>
        <AppContent />
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;