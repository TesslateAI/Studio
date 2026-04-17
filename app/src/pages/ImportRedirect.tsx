import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { LoadingSpinner } from '../components/PulsingGridSpinner';

/**
 * ImportRedirect — Deep link entry point for external "Edit in Tesslate" buttons.
 *
 * URL: /import?repo=https://github.com/org/repo
 *
 * - Authenticated: redirects to /dashboard?import_repo=<encoded-url>
 * - Unauthenticated: redirects to /login with state.from preserving the deep link
 * - Missing/invalid repo param: redirects to /dashboard
 */
export default function ImportRedirect() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { isAuthenticated, isLoading } = useAuth();

  const repo = searchParams.get('repo');
  const ALLOWED_HOSTS = ['github.com', 'gitlab.com', 'bitbucket.org'];
  const isValidRepo = (() => {
    if (!repo) return false;
    try {
      const url = new URL(repo);
      return url.protocol === 'https:' && ALLOWED_HOSTS.includes(url.hostname);
    } catch {
      return false;
    }
  })();

  useEffect(() => {
    if (isLoading) return;

    if (!isValidRepo) {
      navigate('/dashboard', { replace: true });
      return;
    }

    if (isAuthenticated) {
      navigate(`/dashboard?import_repo=${encodeURIComponent(repo ?? '')}`, { replace: true });
    } else {
      const returnPath = `/import?repo=${encodeURIComponent(repo ?? '')}`;
      navigate('/login', { state: { from: returnPath }, replace: true });
    }
  }, [isLoading, isAuthenticated, isValidRepo, repo, navigate]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[var(--background)] flex items-center justify-center">
        <LoadingSpinner size={48} />
      </div>
    );
  }

  return null;
}
