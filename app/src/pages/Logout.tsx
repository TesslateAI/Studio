import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';

export default function Logout() {
  const navigate = useNavigate();

  useEffect(() => {
    // Clear all auth tokens
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
  }, [navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#1a1a1a]">
      <div className="text-white">Logging out...</div>
    </div>
  );
}
