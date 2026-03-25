import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { Users, Check, AlertTriangle, Clock } from 'lucide-react';
import { teamsApi } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { useTeam } from '../contexts/TeamContext';
import { LoadingSpinner } from '../components/PulsingGridSpinner';

interface InviteDetails {
  team_name: string;
  team_slug: string;
  team_avatar_url: string | null;
  role: string;
  invite_type: string;
  expires_at: string;
  is_valid: boolean;
}

export default function InviteAcceptPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const { switchTeam, refreshTeams } = useTeam();
  const [loading, setLoading] = useState(true);
  const [invite, setInvite] = useState<InviteDetails | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);
  const [accepted, setAccepted] = useState(false);

  const loadInvite = useCallback(async () => {
    if (!token) {
      setError('Invalid invitation link');
      setLoading(false);
      return;
    }
    try {
      const details = await teamsApi.getInviteDetails(token);
      setInvite(details);
    } catch (error) {
      console.error('Failed to load invite:', error);
      const err = error as { response?: { status?: number; data?: { detail?: string } } };
      if (err.response?.status === 404) {
        setError('This invitation does not exist or has been revoked.');
      } else {
        setError(err.response?.data?.detail || 'Failed to load invitation details');
      }
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (!authLoading) {
      if (!user) {
        // Redirect to login with invite token preserved
        navigate('/login', { replace: true, state: { from: `/invite/${token}` } });
        return;
      }
      loadInvite();
    }
  }, [authLoading, user, token, navigate, loadInvite]);

  const handleAccept = async () => {
    if (!token) return;
    setAccepting(true);
    try {
      const result = await teamsApi.acceptInvite(token);
      setAccepted(true);
      toast.success(`Joined ${result.team_name} as ${result.role}`);
      // Refresh team list and switch to the invited team
      await refreshTeams();
      await switchTeam(result.team_slug);
      setTimeout(() => {
        navigate('/dashboard', { replace: true });
      }, 1500);
    } catch (error) {
      console.error('Failed to accept invite:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to accept invitation');
    } finally {
      setAccepting(false);
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'long',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const roleColors: Record<string, string> = {
    admin: 'text-amber-400 bg-amber-400/10 border-amber-400/20',
    editor: 'text-blue-400 bg-blue-400/10 border-blue-400/20',
    viewer: 'text-gray-400 bg-gray-400/10 border-gray-400/20',
  };

  if (loading || authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading invitation..." size={60} />
      </div>
    );
  }

  // Error state
  if (error || !invite) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)] p-4">
        <div className="max-w-md w-full bg-[var(--surface-hover)] border border-[var(--border)] rounded-2xl p-8 text-center">
          <div className="w-16 h-16 rounded-full bg-red-500/10 flex items-center justify-center mx-auto mb-4">
            <AlertTriangle size={32} className="text-red-400" />
          </div>
          <h1 className="text-lg font-semibold text-[var(--text)] mb-2">
            Invalid Invitation
          </h1>
          <p className="text-sm text-[var(--text-muted)] mb-6">
            {error || 'This invitation link is invalid or has expired.'}
          </p>
          <button
            onClick={() => navigate('/dashboard')}
            className="px-6 py-3 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-lg font-medium transition-all"
          >
            Go to Dashboard
          </button>
        </div>
      </div>
    );
  }

  // Expired/invalid invite
  if (!invite.is_valid) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)] p-4">
        <div className="max-w-md w-full bg-[var(--surface-hover)] border border-[var(--border)] rounded-2xl p-8 text-center">
          <div className="w-16 h-16 rounded-full bg-amber-500/10 flex items-center justify-center mx-auto mb-4">
            <Clock size={32} className="text-amber-400" />
          </div>
          <h1 className="text-lg font-semibold text-[var(--text)] mb-2">
            Invitation Expired
          </h1>
          <p className="text-sm text-[var(--text-muted)] mb-6">
            This invitation to join <span className="font-medium text-[var(--text)]">{invite.team_name}</span> has expired or reached its usage limit.
          </p>
          <button
            onClick={() => navigate('/dashboard')}
            className="px-6 py-3 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-lg font-medium transition-all"
          >
            Go to Dashboard
          </button>
        </div>
      </div>
    );
  }

  // Accepted state
  if (accepted) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)] p-4">
        <div className="max-w-md w-full bg-[var(--surface-hover)] border border-[var(--border)] rounded-2xl p-8 text-center">
          <div className="w-16 h-16 rounded-full bg-green-500/10 flex items-center justify-center mx-auto mb-4">
            <Check size={32} className="text-green-400" />
          </div>
          <h1 className="text-lg font-semibold text-[var(--text)] mb-2">
            Welcome to {invite.team_name}!
          </h1>
          <p className="text-sm text-[var(--text-muted)]">
            Redirecting to your dashboard...
          </p>
        </div>
      </div>
    );
  }

  // Normal invite accept view
  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)] p-4">
      <div className="max-w-md w-full bg-[var(--surface-hover)] border border-[var(--border)] rounded-2xl p-8">
        {/* Team avatar */}
        <div className="flex justify-center mb-6">
          {invite.team_avatar_url ? (
            <img
              src={invite.team_avatar_url}
              alt={invite.team_name}
              className="w-20 h-20 rounded-full object-cover border-2 border-[var(--border)]"
            />
          ) : (
            <div className="w-20 h-20 rounded-full bg-[var(--primary)]/20 flex items-center justify-center border-2 border-[var(--border)]">
              <Users size={36} className="text-[var(--primary)]" />
            </div>
          )}
        </div>

        {/* Title */}
        <div className="text-center mb-6">
          <h1 className="text-lg font-semibold text-[var(--text)] mb-1">
            You've been invited to join
          </h1>
          <p className="text-xl font-bold text-[var(--primary)]">{invite.team_name}</p>
        </div>

        {/* Details */}
        <div className="space-y-3 mb-6">
          <div className="flex items-center justify-between px-4 py-2.5 bg-white/5 rounded-lg">
            <span className="text-sm text-[var(--text-muted)]">Role</span>
            <span
              className={`px-3 py-1 rounded-lg text-xs font-medium capitalize border ${roleColors[invite.role] || 'text-[var(--text)] bg-white/5 border-white/10'}`}
            >
              {invite.role}
            </span>
          </div>
          <div className="flex items-center justify-between px-4 py-2.5 bg-white/5 rounded-lg">
            <span className="text-sm text-[var(--text-muted)]">Expires</span>
            <span className="text-sm text-[var(--text)]">
              {formatDate(invite.expires_at)}
            </span>
          </div>
        </div>

        {/* Accept button */}
        <button
          onClick={handleAccept}
          disabled={accepting}
          className="w-full px-6 py-3 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-semibold transition-all flex items-center justify-center gap-2 min-h-[48px]"
        >
          {accepting ? (
            <>
              <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              Accepting...
            </>
          ) : (
            <>
              <Check size={18} />
              Accept Invitation
            </>
          )}
        </button>

        {/* Decline */}
        <button
          onClick={() => navigate('/dashboard')}
          className="w-full mt-3 px-6 py-2.5 text-[var(--text-muted)] hover:text-[var(--text)] text-sm font-medium transition-all text-center"
        >
          Decline and go to Dashboard
        </button>
      </div>
    </div>
  );
}
