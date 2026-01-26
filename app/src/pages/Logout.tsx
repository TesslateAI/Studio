import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

export default function Logout() {
  const navigate = useNavigate();

  useEffect(() => {
    const performLogout = async () => {
      // Clear the session cookie by calling the backend logout endpoint
      // This handles OAuth users who authenticated via cookie
      try {
        await axios.post(`${API_URL}/api/auth/cookie/logout`, {}, {
          withCredentials: true, // Send cookies with request
        });
      } catch {
        // Ignore errors - cookie may already be invalid or user used token auth
      }

      // Clear all auth tokens from localStorage
      localStorage.removeItem('token');
      localStorage.removeItem('refreshToken');
      localStorage.removeItem('github_token');
      localStorage.removeItem('github_oauth_return');

      // Clear any session storage
      sessionStorage.clear();

      // Show success message
      toast.success('Logged out successfully');

      // Redirect to login page
      navigate('/login');
    };

    performLogout();
  }, [navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#1a1a1a]">
      <div className="text-white">Logging out...</div>
    </div>
  );
}
