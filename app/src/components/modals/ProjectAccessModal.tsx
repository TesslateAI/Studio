import { useState, useEffect, useCallback } from 'react';
import { X, Eye, EyeSlash, Users, CaretDown, Trash, UserPlus, MagnifyingGlass } from '@phosphor-icons/react';
import { teamsApi } from '../../lib/api';
import type { TeamMember, ProjectMember } from '../../lib/api';
import { useTeam } from '../../contexts/TeamContext';
import toast from 'react-hot-toast';

interface ProjectAccessModalProps {
  isOpen: boolean;
  onClose: () => void;
  projectSlug: string;
  projectName: string;
  currentVisibility: 'team' | 'private';
  onVisibilityChange: (visibility: 'team' | 'private') => void;
  onMembersChange?: () => void;
}

export function ProjectAccessModal({
  isOpen,
  onClose,
  projectSlug,
  projectName,
  currentVisibility,
  onVisibilityChange,
  onMembersChange,
}: ProjectAccessModalProps) {
  const { activeTeam } = useTeam();
  const [visibility, setVisibility] = useState(currentVisibility);
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [projectMembers, setProjectMembers] = useState<ProjectMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [addingMember, setAddingMember] = useState<string | null>(null);
  const [removingMember, setRemovingMember] = useState<string | null>(null);
  const [changingRole, setChangingRole] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  const loadData = useCallback(async () => {
    if (!activeTeam) return;
    setLoading(true);
    try {
      const [members, projMembers] = await Promise.all([
        teamsApi.listMembers(activeTeam.slug),
        teamsApi.listProjectMembers(activeTeam.slug, projectSlug),
      ]);
      setTeamMembers(members);
      setProjectMembers(projMembers);
    } catch {
      toast.error('Failed to load access settings');
    } finally {
      setLoading(false);
    }
  }, [activeTeam, projectSlug]);

  useEffect(() => {
    if (isOpen) loadData();
  }, [isOpen, loadData]);

  useEffect(() => {
    setVisibility(currentVisibility);
  }, [currentVisibility]);

  const handleVisibilityChange = async (newVisibility: 'team' | 'private') => {
    if (!activeTeam) return;
    try {
      await teamsApi.updateProjectVisibility(activeTeam.slug, projectSlug, newVisibility);
      setVisibility(newVisibility);
      onVisibilityChange(newVisibility);
      toast.success(`Project is now ${newVisibility === 'team' ? 'visible to all team members' : 'private'}`);
    } catch {
      toast.error('Failed to update visibility');
    }
  };

  const handleAddMember = async (userId: string, role: string = 'editor') => {
    if (!activeTeam) return;
    setAddingMember(userId);
    try {
      await teamsApi.addProjectMember(activeTeam.slug, projectSlug, userId, role);
      await loadData();
      onMembersChange?.();
      toast.success('Member added to project');
    } catch (error) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to add member');
    } finally {
      setAddingMember(null);
    }
  };

  const handleRemoveMember = async (userId: string) => {
    if (!activeTeam) return;
    setRemovingMember(userId);
    try {
      await teamsApi.removeProjectMember(activeTeam.slug, projectSlug, userId);
      await loadData();
      onMembersChange?.();
      toast.success('Member removed from project');
    } catch {
      toast.error('Failed to remove member');
    } finally {
      setRemovingMember(null);
    }
  };

  const handleRoleChange = async (userId: string, role: string) => {
    if (!activeTeam) return;
    setChangingRole(userId);
    try {
      await teamsApi.updateProjectMemberRole(activeTeam.slug, projectSlug, userId, role);
      await loadData();
      onMembersChange?.();
    } catch {
      toast.error('Failed to update role');
    } finally {
      setChangingRole(null);
    }
  };

  if (!isOpen) return null;

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-50" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="w-full max-w-lg bg-[var(--surface)] border rounded-[var(--radius)] overflow-hidden"
          style={{ borderWidth: 'var(--border-width)', borderColor: 'var(--border-hover)' }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--border)]">
            <div>
              <h2 className="text-sm font-semibold text-[var(--text)]">Project Access</h2>
              <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{projectName}</p>
            </div>
            <button onClick={onClose} className="p-1 hover:bg-[var(--surface-hover)] rounded-[var(--radius-small)] transition-colors">
              <X size={16} className="text-[var(--text-muted)]" />
            </button>
          </div>

          {/* Content */}
          <div className="px-5 py-4 space-y-5 max-h-[70vh] overflow-y-auto">
            {/* Visibility Toggle */}
            <div>
              <label className="text-[11px] font-medium text-[var(--text-muted)] uppercase tracking-wider mb-2 block">Visibility</label>
              <div className="flex gap-2">
                <button
                  onClick={() => handleVisibilityChange('team')}
                  className={`flex-1 flex items-center gap-2 px-3 py-2.5 rounded-[var(--radius-small)] border text-xs font-medium transition-colors ${
                    visibility === 'team'
                      ? 'border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]'
                      : 'border-[var(--border)] bg-[var(--bg)] text-[var(--text-muted)] hover:border-[var(--border-hover)]'
                  }`}
                >
                  <Eye size={16} />
                  <div className="text-left">
                    <div>Team Visible</div>
                    <div className="text-[10px] opacity-60 font-normal">All team members can access</div>
                  </div>
                </button>
                <button
                  onClick={() => handleVisibilityChange('private')}
                  className={`flex-1 flex items-center gap-2 px-3 py-2.5 rounded-[var(--radius-small)] border text-xs font-medium transition-colors ${
                    visibility === 'private'
                      ? 'border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]'
                      : 'border-[var(--border)] bg-[var(--bg)] text-[var(--text-muted)] hover:border-[var(--border-hover)]'
                  }`}
                >
                  <EyeSlash size={16} />
                  <div className="text-left">
                    <div>Private</div>
                    <div className="text-[10px] opacity-60 font-normal">Only added members can access</div>
                  </div>
                </button>
              </div>
              {visibility === 'team' && (
                <p className="text-[10px] text-[var(--text-subtle)] mt-2">
                  Team members use their team role by default. Add members below to override their role on this project.
                </p>
              )}
              {visibility === 'private' && (
                <p className="text-[10px] text-[var(--text-subtle)] mt-2">
                  Only team admins and explicitly added members can access this project.
                </p>
              )}
            </div>

            {/* Search */}
            <div className="relative">
              <MagnifyingGlass size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-subtle)]" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search members..."
                className="w-full pl-8 pr-3 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)] placeholder-[var(--text-subtle)]"
              />
            </div>

            {/* Team Members — unified list with project override controls */}
            <div>
              <label className="text-[11px] font-medium text-[var(--text-muted)] uppercase tracking-wider mb-2 block">
                Team Members ({teamMembers.length})
              </label>

              {loading ? (
                <div className="py-6 text-center text-[var(--text-subtle)] text-xs">Loading...</div>
              ) : (
                <div className="min-h-[200px] max-h-64 overflow-y-auto space-y-0.5 rounded-[var(--radius-small)] border border-[var(--border)] bg-[var(--bg)]">
                  {teamMembers
                    .filter((tm) => {
                      if (!search) return true;
                      const q = search.toLowerCase();
                      return (tm.user_name || '').toLowerCase().includes(q) || (tm.user_email || '').toLowerCase().includes(q);
                    })
                    .map((tm) => {
                      const pm = projectMembers.find((p) => p.user_id === tm.user_id);
                      const hasOverride = !!pm;
                      const isTeamAdmin = tm.role === 'admin';

                      return (
                        <div key={tm.user_id} className="flex items-center gap-2.5 px-3 py-2 hover:bg-[var(--surface-hover)] transition-colors">
                          {/* Avatar */}
                          <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[9px] font-bold flex-shrink-0 ${
                            hasOverride ? 'bg-[var(--primary)]/20 text-[var(--primary)]' : 'bg-[var(--surface-hover)] text-[var(--text-muted)]'
                          }`}>
                            {(tm.user_name || tm.user_email || '?').charAt(0).toUpperCase()}
                          </div>

                          {/* Name + info */}
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-medium text-[var(--text)] truncate">{tm.user_name || tm.user_email}</p>
                            <p className="text-[10px] text-[var(--text-subtle)] truncate">
                              {isTeamAdmin ? 'Team admin — always has access' : `${tm.role} on team`}
                              {hasOverride && !isTeamAdmin && ' · project override'}
                            </p>
                          </div>

                          {/* Role control */}
                          {isTeamAdmin ? (
                            <span className="text-[10px] text-[var(--text-subtle)] flex-shrink-0">Admin</span>
                          ) : hasOverride ? (
                            <>
                              <div className="relative flex-shrink-0">
                                <select
                                  value={pm.role}
                                  onChange={(e) => handleRoleChange(pm.user_id, e.target.value)}
                                  disabled={changingRole === pm.user_id}
                                  className="appearance-none pl-2 pr-5 py-0.5 rounded-[var(--radius-small)] text-[10px] font-medium capitalize bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] focus:outline-none focus:border-[var(--border-hover)] disabled:opacity-50 cursor-pointer"
                                >
                                  <option value="editor">Editor</option>
                                  <option value="viewer">Viewer</option>
                                </select>
                                <CaretDown size={10} className="absolute right-1.5 top-1/2 -translate-y-1/2 pointer-events-none text-[var(--text-subtle)]" />
                              </div>
                              <button
                                onClick={() => handleRemoveMember(pm.user_id)}
                                disabled={removingMember === pm.user_id}
                                className="p-1 hover:bg-[var(--status-error)]/10 text-[var(--text-subtle)] hover:text-[var(--status-error)] rounded-[var(--radius-small)] transition-colors disabled:opacity-50 flex-shrink-0"
                                title="Remove project override"
                              >
                                <Trash size={12} />
                              </button>
                            </>
                          ) : (
                            <button
                              onClick={() => handleAddMember(tm.user_id)}
                              disabled={addingMember === tm.user_id}
                              className="btn btn-sm flex items-center gap-1 disabled:opacity-50 flex-shrink-0"
                            >
                              <UserPlus size={10} />
                              Add
                            </button>
                          )}
                        </div>
                      );
                    })}
                  {teamMembers.length === 0 && (
                    <div className="py-6 text-center text-[var(--text-subtle)] text-xs">
                      <Users size={20} className="mx-auto mb-1.5 opacity-40" />
                      No team members found
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Footer */}
          <div className="px-5 py-3 border-t border-[var(--border)] flex justify-end">
            <button onClick={onClose} className="btn">Done</button>
          </div>
        </div>
      </div>
    </>
  );
}
