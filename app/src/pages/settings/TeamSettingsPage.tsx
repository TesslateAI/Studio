import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { Check, Trash2, AlertTriangle, LogOut } from 'lucide-react';
import { teamsApi } from '../../lib/api';
import type { Team } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { useTeam } from '../../contexts/TeamContext';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { ImageUpload } from '../../components/ImageUpload';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';

export default function TeamSettingsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { activeTeam, can, loading: teamLoading, refreshTeams } = useTeam();
  const [loading, setLoading] = useState(true);
  const [team, setTeam] = useState<Team | null>(null);
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [showLeaveConfirm, setShowLeaveConfirm] = useState(false);

  const loadTeam = useCallback(async () => {
    if (!activeTeam) return;
    try {
      const data = await teamsApi.get(activeTeam.slug);
      setTeam(data);
      setName(data.name);
      setSlug(data.slug);
      setAvatarUrl(data.avatar_url || null);
    } catch (error) {
      console.error('Failed to load team:', error);
      toast.error('Failed to load team details');
    } finally {
      setLoading(false);
    }
  }, [activeTeam]);

  useEffect(() => {
    if (!teamLoading && activeTeam) {
      loadTeam();
    } else if (!teamLoading && !activeTeam) {
      setLoading(false);
    }
  }, [teamLoading, activeTeam, loadTeam]);

  const handleSave = async () => {
    if (!team) return;
    setSaving(true);
    try {
      const updated = await teamsApi.update(team.slug, {
        name: name !== team.name ? name : undefined,
        slug: slug !== team.slug ? slug : undefined,
        avatar_url: avatarUrl !== team.avatar_url ? avatarUrl : undefined,
      });
      setTeam(updated);
      await refreshTeams();
      toast.success('Team settings updated');
    } catch (error) {
      console.error('Failed to update team:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to update team');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!team || deleteConfirmText !== team.slug) return;
    setDeleting(true);
    try {
      await teamsApi.delete(team.slug);
      toast.success('Team deleted');
      window.location.href = '/dashboard';
    } catch (error) {
      console.error('Failed to delete team:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to delete team');
    } finally {
      setDeleting(false);
    }
  };

  const handleLeave = async () => {
    if (!team) return;
    setLeaving(true);
    try {
      await teamsApi.leave(team.slug);
      toast.success('Left team successfully');
      await refreshTeams();
      navigate('/dashboard');
    } catch (error) {
      console.error('Failed to leave team:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to leave team');
    } finally {
      setLeaving(false);
      setShowLeaveConfirm(false);
    }
  };

  if (loading || teamLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading team settings..." size={60} />
      </div>
    );
  }

  if (!team) {
    return (
      <SettingsSection title="Team Settings" description="No team selected">
        <div className="text-center py-12 text-[var(--text-muted)]">
          <p>Select a team to manage its settings.</p>
        </div>
      </SettingsSection>
    );
  }

  const canEdit = can('team.edit');

  return (
    <SettingsSection
      title="Team Settings"
      description="Manage your team's general information and preferences"
    >
      {/* Personal Team Badge */}
      {team.is_personal && (
        <div className="p-3 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius)]">
          <div className="flex items-start gap-3">
            <div className="w-2 h-2 rounded-full bg-[var(--primary)] mt-1.5 flex-shrink-0" />
            <div className="text-xs text-[var(--text-muted)]">
              <p className="font-medium text-[var(--text)]">Personal Team</p>
              <p className="mt-0.5">
                Your default workspace, created automatically. Invite members and collaborate just like any team.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Avatar */}
      <SettingsGroup title="Team Avatar">
        <div className="px-4 md:px-6 py-4 md:py-6">
          {canEdit ? (
            <ImageUpload
              value={avatarUrl}
              onChange={(dataUrl) => setAvatarUrl(dataUrl || null)}
              maxSizeKB={200}
            />
          ) : (
            <div className="flex items-center gap-3">
              {avatarUrl ? (
                <img
                  src={avatarUrl}
                  alt={team.name}
                  className="w-16 h-16 rounded-full object-cover"
                />
              ) : (
                <div className="w-16 h-16 rounded-full bg-[var(--primary)]/20 flex items-center justify-center text-xl font-bold text-[var(--primary)]">
                  {team.name.charAt(0).toUpperCase()}
                </div>
              )}
            </div>
          )}
        </div>
      </SettingsGroup>

      {/* Basic Info */}
      <SettingsGroup title="General">
        <SettingsItem
          label="Team Name"
          description="The display name for your team"
          control={
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={!canEdit}
              placeholder="My Team"
              className="w-full sm:w-64 px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)] disabled:opacity-50 disabled:cursor-not-allowed"
            />
          }
        />
        <SettingsItem
          label="Team Slug"
          description="URL-friendly identifier (lowercase, hyphens allowed)"
          control={
            <input
              type="text"
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))}
              disabled={!canEdit}
              placeholder="my-team"
              className="w-full sm:w-64 px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)] disabled:opacity-50 disabled:cursor-not-allowed"
            />
          }
        />
        <SettingsItem
          label="Subscription Tier"
          description="Current plan for this team"
          control={
            <span className="px-2 py-0.5 bg-[var(--primary)]/10 text-[var(--primary)] rounded-[var(--radius-small)] text-xs font-medium capitalize">
              {team.subscription_tier}
            </span>
          }
        />
      </SettingsGroup>

      {/* Save Button */}
      {canEdit && (
        <div className="flex justify-end">
          <button
            onClick={handleSave}
            disabled={saving || (name === team.name && slug === team.slug && avatarUrl === team.avatar_url)}
            className="btn btn-filled flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? (
              <>
                <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                Saving...
              </>
            ) : (
              <>
                <Check size={18} />
                Save Changes
              </>
            )}
          </button>
        </div>
      )}

      {/* Leave Team — visible to non-owners on non-personal teams */}
      {!team.is_personal && (
        <SettingsGroup title="Membership">
          <div className="px-4 py-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <p className="text-xs font-medium text-[var(--text)]">Leave Team</p>
                <p className="text-[11px] text-[var(--text-muted)] mt-0.5">
                  Remove yourself from this team. You will lose access to all team projects.
                </p>
              </div>
              {!showLeaveConfirm ? (
                <button
                  onClick={() => setShowLeaveConfirm(true)}
                  className="btn btn-danger flex items-center gap-2 flex-shrink-0"
                >
                  <LogOut size={14} />
                  Leave Team
                </button>
              ) : (
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button
                    onClick={handleLeave}
                    disabled={leaving}
                    className="btn btn-danger flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {leaving ? 'Leaving...' : 'Confirm Leave'}
                  </button>
                  <button
                    onClick={() => setShowLeaveConfirm(false)}
                    className="btn"
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>
          </div>
        </SettingsGroup>
      )}

      {/* Danger Zone */}
      {canEdit && !team.is_personal && /* Only personal teams can't be deleted */ (
        <SettingsGroup title="Danger Zone">
          <div className="px-4 py-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-[var(--status-error)]">Delete Team</p>
                <p className="text-xs text-[var(--text-muted)] mt-0.5">
                  Permanently delete this team and all associated data. This action cannot be undone.
                </p>
              </div>
              <button
                onClick={() => setShowDeleteConfirm(true)}
                className="btn btn-danger flex items-center gap-2 flex-shrink-0"
              >
                <Trash2 size={16} />
                Delete Team
              </button>
            </div>

            {showDeleteConfirm && (
              <div className="mt-4 p-4 bg-[var(--status-error)]/5 border border-[var(--status-error)]/20 rounded-[var(--radius)]">
                <div className="flex items-start gap-3">
                  <AlertTriangle size={20} className="text-[var(--status-error)] mt-0.5 flex-shrink-0" />
                  <div className="flex-1">
                    <p className="text-sm text-[var(--status-error)] font-medium">
                      Are you sure? This will permanently delete the team, all projects, and all data.
                    </p>
                    <p className="text-xs text-[var(--text-muted)] mt-2">
                      Type <span className="font-mono text-[var(--status-error)]">{team.slug}</span> to confirm:
                    </p>
                    <input
                      type="text"
                      value={deleteConfirmText}
                      onChange={(e) => setDeleteConfirmText(e.target.value)}
                      placeholder={team.slug}
                      className="mt-2 w-full px-2 py-1 bg-[var(--bg)] border border-[var(--status-error)]/30 rounded-[var(--radius-small)] text-xs text-[var(--text)] placeholder-[var(--text-subtle)] focus:outline-none focus:border-[var(--status-error)]"
                    />
                    <div className="flex gap-2 mt-3">
                      <button
                        onClick={handleDelete}
                        disabled={deleting || deleteConfirmText !== team.slug}
                        className="btn btn-danger flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {deleting ? 'Deleting...' : 'Permanently Delete'}
                      </button>
                      <button
                        onClick={() => {
                          setShowDeleteConfirm(false);
                          setDeleteConfirmText('');
                        }}
                        className="btn flex items-center gap-2"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </SettingsGroup>
      )}
    </SettingsSection>
  );
}
