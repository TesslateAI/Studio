import { useState, useEffect, useCallback } from 'react';
import toast from 'react-hot-toast';
import {
  Users,
  UserPlus,
  Link2,
  Trash2,
  ChevronDown,
  Copy,
  Clock,
  X,
  Mail,
} from 'lucide-react';
import { teamsApi } from '../../lib/api';
import type { TeamMember } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { useTeam } from '../../contexts/TeamContext';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { SettingsSection, SettingsGroup } from '../../components/settings';

interface Invitation {
  id: string;
  email: string;
  role: string;
  invite_type: string;
  token: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  max_uses: number | null;
  use_count: number;
  created_at: string;
}

type InviteMode = 'email' | 'link' | null;

export default function TeamMembersPage() {
  const { user } = useAuth();
  const { activeTeam, can, loading: teamLoading } = useTeam();
  const [loading, setLoading] = useState(true);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [inviteMode, setInviteMode] = useState<InviteMode>(null);

  // Invite by email form
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('editor');
  const [inviting, setInviting] = useState(false);

  // Invite link form
  const [linkRole, setLinkRole] = useState('editor');
  const [linkMaxUses, setLinkMaxUses] = useState<string>('');
  const [linkExpDays, setLinkExpDays] = useState('30');
  const [creatingLink, setCreatingLink] = useState(false);
  const [generatedLink, setGeneratedLink] = useState<string | null>(null);

  // Role change
  const [changingRole, setChangingRole] = useState<string | null>(null);

  // Remove member
  const [removingMember, setRemovingMember] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!activeTeam) return;
    try {
      const [membersData, invitationsData] = await Promise.all([
        teamsApi.listMembers(activeTeam.slug),
        can('team.invite')
          ? teamsApi.listInvitations(activeTeam.slug)
          : Promise.resolve([]),
      ]);
      setMembers(membersData);
      setInvitations(invitationsData);
    } catch (error) {
      console.error('Failed to load team data:', error);
      toast.error('Failed to load team members');
    } finally {
      setLoading(false);
    }
  }, [activeTeam, can]);

  useEffect(() => {
    if (!teamLoading && activeTeam) {
      loadData();
    } else if (!teamLoading && !activeTeam) {
      setLoading(false);
    }
  }, [teamLoading, activeTeam, loadData]);

  const handleInviteEmail = async () => {
    if (!activeTeam || !inviteEmail) return;
    setInviting(true);
    try {
      await teamsApi.inviteByEmail(activeTeam.slug, {
        email: inviteEmail,
        role: inviteRole,
      });
      toast.success(`Invitation sent to ${inviteEmail}`);
      setInviteEmail('');
      setInviteMode(null);
      await loadData();
    } catch (error) {
      console.error('Failed to send invite:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to send invitation');
    } finally {
      setInviting(false);
    }
  };

  const handleCreateLink = async () => {
    if (!activeTeam) return;
    setCreatingLink(true);
    try {
      const result = await teamsApi.createInviteLink(activeTeam.slug, {
        role: linkRole,
        max_uses: linkMaxUses ? parseInt(linkMaxUses, 10) : undefined,
        expires_in_days: parseInt(linkExpDays, 10),
      });
      const link = `${window.location.origin}/invite/${result.token}`;
      setGeneratedLink(link);
      toast.success('Invite link created');
      await loadData();
    } catch (error) {
      console.error('Failed to create invite link:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to create invite link');
    } finally {
      setCreatingLink(false);
    }
  };

  const handleCopyLink = () => {
    if (generatedLink) {
      navigator.clipboard.writeText(generatedLink);
      toast.success('Link copied to clipboard');
    }
  };

  const handleRoleChange = async (userId: string, newRole: string) => {
    if (!activeTeam) return;
    setChangingRole(userId);
    try {
      await teamsApi.updateMemberRole(activeTeam.slug, userId, { role: newRole });
      toast.success('Role updated');
      await loadData();
    } catch (error) {
      console.error('Failed to update role:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to update role');
    } finally {
      setChangingRole(null);
    }
  };

  const handleRemoveMember = async (userId: string) => {
    if (!activeTeam) return;
    setRemovingMember(userId);
    try {
      await teamsApi.removeMember(activeTeam.slug, userId);
      toast.success('Member removed');
      await loadData();
    } catch (error) {
      console.error('Failed to remove member:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to remove member');
    } finally {
      setRemovingMember(null);
    }
  };

  const handleRevokeInvitation = async (invitationId: string) => {
    if (!activeTeam) return;
    try {
      await teamsApi.revokeInvitation(activeTeam.slug, invitationId);
      toast.success('Invitation revoked');
      await loadData();
    } catch (error) {
      console.error('Failed to revoke invitation:', error);
      toast.error('Failed to revoke invitation');
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const roleColors: Record<string, string> = {
    admin: 'text-[var(--primary)] bg-[var(--primary)]/10',
    editor: 'text-[var(--text)] bg-[var(--surface)]',
    viewer: 'text-[var(--text-muted)] bg-[var(--surface)]',
  };

  if (loading || teamLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading members..." size={60} />
      </div>
    );
  }

  if (!activeTeam) {
    return (
      <SettingsSection title="Team Members" description="No team selected">
        <div className="text-center py-12 text-[var(--text-muted)]">
          <p>Select a team to manage members.</p>
        </div>
      </SettingsSection>
    );
  }

  const canInvite = can('team.invite');
  const canRemove = can('team.remove_member');
  const pendingInvitations = invitations.filter(
    (inv) => !inv.accepted_at && !inv.revoked_at && new Date(inv.expires_at) > new Date()
  );

  return (
    <SettingsSection
      title="Team Members"
      description="Manage who has access to this team and their roles"
    >
      {/* Invite Actions */}
      {canInvite && (
        <div className="flex gap-2">
          <button
            onClick={() => {
              setInviteMode(inviteMode === 'email' ? null : 'email');
              setGeneratedLink(null);
            }}
            className="btn btn-filled flex items-center gap-2"
          >
            <UserPlus size={16} />
            Invite Member
          </button>
          <button
            onClick={() => {
              setInviteMode(inviteMode === 'link' ? null : 'link');
              setGeneratedLink(null);
            }}
            className="btn flex items-center gap-2"
          >
            <Link2 size={16} />
            Create Invite Link
          </button>
        </div>
      )}

      {/* Email Invite Form */}
      {inviteMode === 'email' && (
        <SettingsGroup title="Invite by Email">
          <div className="px-4 py-4 space-y-3">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-subtle)]" />
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="email@example.com"
                  className="w-full pl-9 pr-3 py-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)] placeholder-[var(--text-subtle)]"
                />
              </div>
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value)}
                className="px-3 py-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
              >
                <option value="admin">Admin</option>
                <option value="editor">Editor</option>
                <option value="viewer">Viewer</option>
              </select>
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleInviteEmail}
                disabled={inviting || !inviteEmail}
                className="btn btn-filled"
              >
                {inviting ? 'Sending...' : 'Send Invitation'}
              </button>
              <button
                onClick={() => setInviteMode(null)}
                className="btn"
              >
                Cancel
              </button>
            </div>
          </div>
        </SettingsGroup>
      )}

      {/* Link Invite Form */}
      {inviteMode === 'link' && (
        <SettingsGroup title="Create Invite Link">
          <div className="px-4 py-4 space-y-3">
            <div className="flex gap-2">
              <select
                value={linkRole}
                onChange={(e) => setLinkRole(e.target.value)}
                className="px-3 py-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
              >
                <option value="admin">Admin</option>
                <option value="editor">Editor</option>
                <option value="viewer">Viewer</option>
              </select>
              <input
                type="number"
                value={linkMaxUses}
                onChange={(e) => setLinkMaxUses(e.target.value)}
                placeholder="Max uses (optional)"
                min={1}
                className="flex-1 px-3 py-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)] placeholder-[var(--text-subtle)]"
              />
              <select
                value={linkExpDays}
                onChange={(e) => setLinkExpDays(e.target.value)}
                className="px-3 py-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
              >
                <option value="1">1 day</option>
                <option value="7">7 days</option>
                <option value="30">30 days</option>
                <option value="90">90 days</option>
                <option value="365">1 year</option>
              </select>
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleCreateLink}
                disabled={creatingLink}
                className="btn btn-filled"
              >
                {creatingLink ? 'Creating...' : 'Generate Link'}
              </button>
              <button
                onClick={() => {
                  setInviteMode(null);
                  setGeneratedLink(null);
                }}
                className="btn"
              >
                Cancel
              </button>
            </div>
            {generatedLink && (
              <div className="flex items-center gap-2 p-3 bg-[var(--status-success)]/10 border border-[var(--status-success)]/20 rounded-[var(--radius-small)]">
                <input
                  type="text"
                  value={generatedLink}
                  readOnly
                  className="flex-1 bg-transparent text-xs text-[var(--status-success)] outline-none"
                />
                <button
                  onClick={handleCopyLink}
                  className="p-1.5 hover:bg-[var(--surface-hover)] rounded transition-all"
                >
                  <Copy size={16} className="text-[var(--status-success)]" />
                </button>
              </div>
            )}
          </div>
        </SettingsGroup>
      )}

      {/* Members List */}
      <SettingsGroup title={`Members (${members.length})`}>
        {members.length === 0 ? (
          <div className="px-4 py-8 text-center text-[var(--text-muted)]">
            <Users size={32} className="mx-auto mb-2 opacity-40" />
            <p className="text-sm">No members found</p>
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {members.map((member) => (
              <div
                key={member.id}
                className="flex items-center gap-3 px-4 py-3 hover:bg-[var(--surface)] transition-colors"
              >
                {/* Avatar */}
                <div className="flex-shrink-0">
                  {member.user_avatar_url ? (
                    <img
                      src={member.user_avatar_url}
                      alt={member.user_name || ''}
                      className="w-8 h-8 rounded-full object-cover"
                    />
                  ) : (
                    <div className="w-8 h-8 rounded-full bg-[var(--primary)]/20 flex items-center justify-center text-xs font-bold text-[var(--primary)]">
                      {(member.user_name || member.user_email || '?').charAt(0).toUpperCase()}
                    </div>
                  )}
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-[var(--text)] truncate">
                    {member.user_name || 'Unknown'}
                  </p>
                  <p className="text-xs text-[var(--text-muted)] truncate">
                    {member.user_email}
                  </p>
                </div>

                {/* Joined date */}
                <div className="hidden sm:block text-xs text-[var(--text-muted)]">
                  {formatDate(member.joined_at)}
                </div>

                {/* Role */}
                {canRemove && member.user_id !== user?.id ? (
                  <div className="relative">
                    <select
                      value={member.role}
                      onChange={(e) => handleRoleChange(member.user_id, e.target.value)}
                      disabled={changingRole === member.user_id}
                      className={`appearance-none pl-2 pr-6 py-0.5 rounded-[var(--radius-small)] text-xs font-medium capitalize cursor-pointer focus:outline-none focus:border-[var(--border-hover)] disabled:opacity-50 ${roleColors[member.role] || 'text-[var(--text)] bg-[var(--surface)]'}`}
                    >
                      <option value="admin">Admin</option>
                      <option value="editor">Editor</option>
                      <option value="viewer">Viewer</option>
                    </select>
                    <ChevronDown
                      size={12}
                      className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none opacity-60"
                    />
                  </div>
                ) : (
                  <span
                    className={`px-3 py-1 rounded-[var(--radius-small)] text-xs font-medium capitalize ${roleColors[member.role] || 'text-[var(--text)] bg-[var(--surface)]'}`}
                  >
                    {member.role}
                  </span>
                )}

                {/* Remove button */}
                {canRemove && member.user_id !== user?.id && (
                  <button
                    onClick={() => handleRemoveMember(member.user_id)}
                    disabled={removingMember === member.user_id}
                    className="p-1.5 hover:bg-[var(--status-error)]/10 text-[var(--text-muted)] hover:text-[var(--status-error)] rounded-[var(--radius-small)] transition-all disabled:opacity-50"
                    title="Remove member"
                  >
                    {removingMember === member.user_id ? (
                      <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                      </svg>
                    ) : (
                      <Trash2 size={14} />
                    )}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </SettingsGroup>

      {/* Pending Invitations */}
      {canInvite && pendingInvitations.length > 0 && (
        <SettingsGroup title={`Pending Invitations (${pendingInvitations.length})`}>
          <div className="divide-y divide-[var(--border)]">
            {pendingInvitations.map((inv) => (
              <div
                key={inv.id}
                className="flex items-center gap-3 px-4 py-3 hover:bg-[var(--surface)] transition-colors"
              >
                {/* Icon */}
                <div className="flex-shrink-0">
                  <div className="w-8 h-8 rounded-full bg-[var(--surface)] flex items-center justify-center">
                    {inv.invite_type === 'email' ? (
                      <Mail size={14} className="text-[var(--text-muted)]" />
                    ) : (
                      <Link2 size={14} className="text-[var(--text-muted)]" />
                    )}
                  </div>
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-[var(--text)] truncate">
                    {inv.invite_type === 'email' ? inv.email : 'Invite Link'}
                  </p>
                  <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
                    <Clock size={12} />
                    <span>Expires {formatDate(inv.expires_at)}</span>
                    {inv.max_uses != null && (
                      <span>
                        ({inv.use_count}/{inv.max_uses} uses)
                      </span>
                    )}
                  </div>
                </div>

                {/* Role badge */}
                <span
                  className={`px-3 py-1 rounded-[var(--radius-small)] text-xs font-medium capitalize ${roleColors[inv.role] || 'text-[var(--text)] bg-[var(--surface)]'}`}
                >
                  {inv.role}
                </span>

                {/* Revoke button */}
                <button
                  onClick={() => handleRevokeInvitation(inv.id)}
                  className="p-1.5 hover:bg-[var(--status-error)]/10 text-[var(--text-muted)] hover:text-[var(--status-error)] rounded-[var(--radius-small)] transition-all"
                  title="Revoke invitation"
                >
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
        </SettingsGroup>
      )}
    </SettingsSection>
  );
}
