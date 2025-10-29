import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import toast from 'react-hot-toast';
import { useState, useEffect } from 'react';
import { ThemeProvider } from './theme';
import Layout from './components/Layout';
import Landing from './pages/Landing';
import NewLandingPage from './pages/NewLandingPage';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import Project from './pages/Project';
import Marketplace from './pages/Marketplace';
import Library from './pages/Library';
import AdminDashboard from './pages/AdminDashboard';
import AuthCallback from './pages/AuthCallback';
import Logout from './pages/Logout';
import Referrals from './pages/Referrals';
import { Walkthrough } from './components/Walkthrough';
import { useReferralTracking } from './hooks/useReferralTracking';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

async function validateAndRefreshToken(): Promise<boolean> {
  const token = localStorage.getItem('token');
  const refreshToken = localStorage.getItem('refreshToken');

  if (!token && !refreshToken) {
    return false;
  }

  if (!token && refreshToken) {
    try {
      const response = await axios.post(`${API_URL}/api/auth/refresh`, {
        refresh_token: refreshToken,
      });

      const { access_token, refresh_token: newRefreshToken } = response.data;
      localStorage.setItem('token', access_token);
      if (newRefreshToken) {
        localStorage.setItem('refreshToken', newRefreshToken);
      }
      return true;
    } catch (error) {
      localStorage.removeItem('token');
      localStorage.removeItem('refreshToken');
      return false;
    }
  }

  return true;
}

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token');
  const refreshToken = localStorage.getItem('refreshToken');

  // If we have either token, assume authenticated
  // The axios interceptor will handle refresh on API calls
  if (token || refreshToken) {
    return <>{children}</>;
  }

  return <Navigate to="/login" />;
}

function AppContent() {
  // Track referrals (must be inside BrowserRouter)
  useReferralTracking();

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
          <Route path="/" element={<NewLandingPage />} />
          <Route path="/landing-old" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/logout" element={<Logout />} />
          <Route path="/referral" element={<Referrals />} />
          <Route path="/referrals" element={<Referrals />} />
          <Route
            path="/dashboard"
            element={
              <PrivateRoute>
                <Dashboard />
              </PrivateRoute>
            }
          />
          <Route
            path="/project/:slug"
            element={
              <PrivateRoute>
                <Project />
              </PrivateRoute>
            }
          />
          <Route
            path="/marketplace"
            element={
              <PrivateRoute>
                <Marketplace />
              </PrivateRoute>
            }
          />
          <Route
            path="/library"
            element={
              <PrivateRoute>
                <Library />
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
          <Route
            path="/auth/github/callback"
            element={
              <PrivateRoute>
                <AuthCallback />
              </PrivateRoute>
            }
          />
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