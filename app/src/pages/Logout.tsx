import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';

export default function Logout() {
  const navigate = useNavigate();
  const { logout } = useAuth();

  useEffect(() => {
    const performLogout = async () => {
      try {
        await logout();
      } catch {
        // Best-effort — always redirect regardless
      }

      // Clear GitHub-specific tokens
      localStorage.removeItem('github_token');
      localStorage.removeItem('github_oauth_return');

      toast.success('Logged out successfully');
      navigate('/login');
    };

    performLogout();
  }, [logout, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#1a1a1a]">
      <div className="text-white">Logging out...</div>
    </div>
  );
}
