import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { creatorsApi } from '../lib/api';
import { LoadingSpinner } from '../components/PulsingGridSpinner';

/**
 * Thin resolver for /@username routes.
 * Looks up the creator by username, then redirects to the existing
 * /marketplace/creator/:id page (reuses MarketplaceAuthor).
 */
export default function UserProfilePage() {
  const { username } = useParams<{ username: string }>();
  const navigate = useNavigate();
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!username) {
      navigate('/', { replace: true });
      return;
    }

    let cancelled = false;

    creatorsApi
      .getProfileByUsername(username)
      .then((profile) => {
        if (!cancelled) {
          navigate(`/marketplace/creator/${profile.id}`, { replace: true });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError(true);
          toast.error(`User @${username} not found`);
          navigate('/', { replace: true });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [username, navigate]);

  if (error) return null;

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
      <LoadingSpinner message={`Loading @${username}...`} size={60} />
    </div>
  );
}
