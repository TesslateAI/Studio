import { useState, useEffect, useCallback } from 'react';
import {
  Search,
  Users,
  Eye,
  Ban,
  Bot,
  Trash2,
  CreditCard,
  Clock,
  Download,
  ChevronLeft,
  ChevronRight,
  X,
  AlertTriangle,
  Check,
  RefreshCw,
} from 'lucide-react';
import { getAuthHeaders } from '../../lib/api';
import toast from 'react-hot-toast';
import { LoadingSpinner } from '../PulsingGridSpinner';
import AgentRunViewer from './AgentRunViewer';

interface UserListItem {
  id: string;
  email: string;
  username: string;
  name: string;
  avatar_url: string | null;
  subscription_tier: string;
  is_active: boolean;
  is_suspended: boolean;
  is_deleted: boolean;
  is_verified: boolean;
  is_superuser: boolean;
  total_credits: number;
  bundled_credits: number;
  purchased_credits: number;
  total_spend: number;
  project_count: number;
  is_creator: boolean;
  last_active_at: string | null;
  created_at: string | null;
}

interface UserDetail extends UserListItem {
  slug: string;
  bio: string | null;
  twitter_handle: string | null;
  github_username: string | null;
  website_url: string | null;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  suspended_at: string | null;
  suspended_reason: string | null;
  deleted_at: string | null;
  deleted_reason: string | null;
  credits_reset_date: string | null;
  referral_code: string | null;
  referred_by: string | null;
  deployed_projects_count: number;
  usage_stats: {
    total_tokens_input: number;
    total_tokens_output: number;
    total_cost_cents: number;
  };
  recent_projects: Array<{ name: string; created_at: string }>;
  updated_at: string | null;
}

interface UsersResponse {
  users: UserListItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

interface AgentRunItem {
  message_id: string;
  chat_id: string;
  project_name: string | null;
  project_slug: string | null;
  created_at: string;
  completion_reason: string | null;
  error: string | null;
  iterations: number;
  tool_calls_made: number;
  agent_type: string | null;
}

export default function UserManagement() {
  const [users, setUsers] = useState<UserListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [pages, setPages] = useState(0);

  // Filters
  const [search, setSearch] = useState('');
  const [tierFilter, setTierFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  // Modal states
  const [selectedUser, setSelectedUser] = useState<UserDetail | null>(null);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [showSuspendModal, setShowSuspendModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [showCreditsModal, setShowCreditsModal] = useState(false);

  // Agent runs state
  const [detailTab, setDetailTab] = useState<'details' | 'agent-runs'>('details');
  const [agentRuns, setAgentRuns] = useState<AgentRunItem[]>([]);
  const [agentRunsLoading, setAgentRunsLoading] = useState(false);
  const [agentRunsPage, setAgentRunsPage] = useState(1);
  const [agentRunsPages, setAgentRunsPages] = useState(0);
  const [agentRunsTotal, setAgentRunsTotal] = useState(0);
  const [agentRunsFilter, setAgentRunsFilter] = useState('');
  const [viewingRunId, setViewingRunId] = useState<string | null>(null);

  // Action states
  const [actionLoading, setActionLoading] = useState(false);
  const [suspendReason, setSuspendReason] = useState('');
  const [deleteConfirmEmail, setDeleteConfirmEmail] = useState('');
  const [deleteReason, setDeleteReason] = useState('');
  const [creditsAmount, setCreditsAmount] = useState(0);
  const [creditsReason, setCreditsReason] = useState('');

  const loadUsers = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (search) params.append('search', search);
      if (tierFilter) params.append('tier', tierFilter);
      if (statusFilter) params.append('status', statusFilter);
      params.append('page', page.toString());
      params.append('page_size', pageSize.toString());

      const response = await fetch(`/api/admin/users?${params.toString()}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load users');

      const data: UsersResponse = await response.json();
      setUsers(data.users);
      setTotal(data.total);
      setPages(data.pages);
    } catch (error) {
      console.error('Failed to load users:', error);
      toast.error('Failed to load users');
    } finally {
      setLoading(false);
    }
  }, [search, tierFilter, statusFilter, page, pageSize]);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  const loadUserDetail = async (userId: string) => {
    try {
      const response = await fetch(`/api/admin/users/${userId}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load user details');

      const data: UserDetail = await response.json();
      setSelectedUser(data);
      setDetailTab('details');
      setAgentRuns([]);
      setAgentRunsPage(1);
      setAgentRunsPages(0);
      setAgentRunsTotal(0);
      setAgentRunsFilter('');
      setShowDetailModal(true);
    } catch (error) {
      console.error('Failed to load user details:', error);
      toast.error('Failed to load user details');
    }
  };

  const loadAgentRuns = async (userId: string, page: number = 1, filterOverride?: string) => {
    try {
      setAgentRunsLoading(true);
      const params = new URLSearchParams();
      params.append('page', page.toString());
      params.append('page_size', '15');
      const filter = filterOverride !== undefined ? filterOverride : agentRunsFilter;
      if (filter) params.append('completion_reason', filter);

      const response = await fetch(`/api/admin/users/${userId}/agent-runs?${params.toString()}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load agent runs');

      const data = await response.json();
      setAgentRuns(data.items);
      setAgentRunsTotal(data.total);
      setAgentRunsPages(data.pages);
      setAgentRunsPage(page);
    } catch (error) {
      console.error('Failed to load agent runs:', error);
      toast.error('Failed to load agent runs');
    } finally {
      setAgentRunsLoading(false);
    }
  };

  const handleSuspend = async () => {
    if (!selectedUser || !suspendReason.trim()) return;

    try {
      setActionLoading(true);
      const response = await fetch(`/api/admin/users/${selectedUser.id}/suspend`, {
        method: 'POST',
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify({ reason: suspendReason, notify_user: false }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to suspend user');
      }

      toast.success('User suspended successfully');
      setShowSuspendModal(false);
      setSuspendReason('');
      loadUsers();
    } catch (error) {
      console.error('Failed to suspend user:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to suspend user');
    } finally {
      setActionLoading(false);
    }
  };

  const handleUnsuspend = async (userId: string) => {
    try {
      const response = await fetch(`/api/admin/users/${userId}/unsuspend`, {
        method: 'POST',
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to unsuspend user');

      toast.success('User unsuspended successfully');
      loadUsers();
    } catch (error) {
      console.error('Failed to unsuspend user:', error);
      toast.error('Failed to unsuspend user');
    }
  };

  const handleDelete = async () => {
    if (!selectedUser || deleteConfirmEmail.toLowerCase() !== selectedUser.email.toLowerCase()) {
      toast.error('Email confirmation does not match');
      return;
    }
    if (!deleteReason.trim()) return;

    try {
      setActionLoading(true);
      const response = await fetch(`/api/admin/users/${selectedUser.id}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify({
          confirmation_email: deleteConfirmEmail,
          reason: deleteReason,
          notify_user: false,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to delete user');
      }

      toast.success('User deleted successfully');
      setShowDeleteModal(false);
      setDeleteConfirmEmail('');
      setDeleteReason('');
      loadUsers();
    } catch (error) {
      console.error('Failed to delete user:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to delete user');
    } finally {
      setActionLoading(false);
    }
  };

  const handleAdjustCredits = async () => {
    if (!selectedUser || !creditsReason.trim()) return;

    try {
      setActionLoading(true);
      const response = await fetch(`/api/admin/users/${selectedUser.id}/credits/adjust`, {
        method: 'POST',
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify({ amount: creditsAmount, reason: creditsReason }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to adjust credits');
      }

      const result = await response.json();
      toast.success(`Credits adjusted: ${result.old_balance} → ${result.new_balance}`);
      setShowCreditsModal(false);
      setCreditsAmount(0);
      setCreditsReason('');
      loadUsers();
    } catch (error) {
      console.error('Failed to adjust credits:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to adjust credits');
    } finally {
      setActionLoading(false);
    }
  };

  const handleExport = async () => {
    try {
      const params = new URLSearchParams();
      if (search) params.append('search', search);
      if (tierFilter) params.append('tier', tierFilter);
      if (statusFilter) params.append('status', statusFilter);

      const response = await fetch(`/api/admin/users/export?${params.toString()}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to export users');

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'users_export.csv';
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      toast.success('Export downloaded');
    } catch (error) {
      console.error('Failed to export users:', error);
      toast.error('Failed to export users');
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'Never';
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getStatusBadge = (user: UserListItem) => {
    if (user.is_deleted) {
      return (
        <span className="px-2 py-1 rounded text-xs bg-gray-500/20 text-gray-400">Deleted</span>
      );
    }
    if (user.is_suspended) {
      return (
        <span className="px-2 py-1 rounded text-xs bg-red-500/20 text-red-400">Suspended</span>
      );
    }
    if (!user.is_active) {
      return (
        <span className="px-2 py-1 rounded text-xs bg-yellow-500/20 text-yellow-400">Inactive</span>
      );
    }
    return <span className="px-2 py-1 rounded text-xs bg-green-500/20 text-green-400">Active</span>;
  };

  const getTierBadge = (tier: string) => {
    const colors: Record<string, string> = {
      free: 'bg-gray-500/20 text-gray-300',
      basic: 'bg-blue-500/20 text-blue-400',
      pro: 'bg-purple-500/20 text-purple-400',
      ultra: 'bg-yellow-500/20 text-yellow-400',
    };
    return (
      <span className={`px-2 py-1 rounded text-xs capitalize ${colors[tier] || colors.free}`}>
        {tier}
      </span>
    );
  };

  if (loading && users.length === 0) {
    return (
      <div className="flex items-center justify-center py-12">
        <LoadingSpinner message="Loading users..." size={60} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <Users className="text-blue-500" size={24} />
          <h2 className="text-2xl font-bold text-white">User Management</h2>
          <span className="text-gray-400 text-sm">({total} users)</span>
        </div>
        <button
          onClick={handleExport}
          className="bg-gray-700 hover:bg-gray-600 text-white px-4 py-2 rounded-lg flex items-center space-x-2 text-sm"
        >
          <Download size={16} />
          <span>Export CSV</span>
        </button>
      </div>

      {/* Search and Filters */}
      <div className="bg-gray-800 rounded-lg p-4 border border-[var(--text)]/15">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="md:col-span-2">
            <div className="relative">
              <Search
                className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
                size={18}
              />
              <input
                type="text"
                placeholder="Search by email, username, or name..."
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                className="w-full bg-gray-700 text-white rounded-lg pl-10 pr-4 py-2 border border-[var(--text)]/20"
              />
            </div>
          </div>
          <select
            value={tierFilter}
            onChange={(e) => {
              setTierFilter(e.target.value);
              setPage(1);
            }}
            className="bg-gray-700 text-white rounded-lg px-3 py-2 border border-[var(--text)]/20 [&>option]:bg-gray-700"
          >
            <option value="">All Tiers</option>
            <option value="free">Free</option>
            <option value="basic">Basic</option>
            <option value="pro">Pro</option>
            <option value="ultra">Ultra</option>
          </select>
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
            className="bg-gray-700 text-white rounded-lg px-3 py-2 border border-[var(--text)]/20 [&>option]:bg-gray-700"
          >
            <option value="">All Status</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
            <option value="deleted">Deleted</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
      </div>

      {/* Users Table */}
      <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-750 border-b border-[var(--text)]/15">
              <tr>
                <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">User</th>
                <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Tier</th>
                <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Status</th>
                <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Credits</th>
                <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Projects</th>
                <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">
                  Last Active
                </th>
                <th className="text-right px-6 py-3 text-gray-400 font-medium text-sm">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700">
              {users.map((user) => (
                <tr key={user.id} className="hover:bg-gray-700/50 transition-colors">
                  <td className="px-6 py-4">
                    <div className="flex items-center space-x-3">
                      {user.avatar_url ? (
                        <img src={user.avatar_url} alt="" className="w-10 h-10 rounded-full" />
                      ) : (
                        <div className="w-10 h-10 rounded-full bg-gray-600 flex items-center justify-center text-white font-medium">
                          {user.name?.charAt(0).toUpperCase() ||
                            user.username?.charAt(0).toUpperCase()}
                        </div>
                      )}
                      <div>
                        <div className="text-white font-medium">{user.name || user.username}</div>
                        <div className="text-gray-400 text-sm">@{user.username}</div>
                        <div className="text-gray-500 text-xs">{user.email}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">{getTierBadge(user.subscription_tier)}</td>
                  <td className="px-6 py-4">{getStatusBadge(user)}</td>
                  <td className="px-6 py-4">
                    <div className="text-white">{user.total_credits.toLocaleString()}</div>
                    <div className="text-gray-500 text-xs">
                      ${(user.total_spend / 100).toFixed(2)} spent
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-white">{user.project_count}</span>
                    {user.is_creator && (
                      <span className="ml-2 text-xs text-purple-400">Creator</span>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-gray-300 text-sm">{formatDate(user.last_active_at)}</span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end space-x-2">
                      <button
                        onClick={() => loadUserDetail(user.id)}
                        className="p-2 hover:bg-gray-600 rounded text-gray-400 hover:text-white"
                        title="View details"
                      >
                        <Eye size={16} />
                      </button>
                      {!user.is_superuser && !user.is_deleted && (
                        <>
                          {user.is_suspended ? (
                            <button
                              onClick={() => handleUnsuspend(user.id)}
                              className="p-2 hover:bg-green-600/20 rounded text-green-400 hover:text-green-300"
                              title="Unsuspend"
                            >
                              <Check size={16} />
                            </button>
                          ) : (
                            <button
                              onClick={() => {
                                loadUserDetail(user.id).then(() => setShowSuspendModal(true));
                              }}
                              className="p-2 hover:bg-yellow-600/20 rounded text-yellow-400 hover:text-yellow-300"
                              title="Suspend"
                            >
                              <Ban size={16} />
                            </button>
                          )}
                          <button
                            onClick={() => {
                              loadUserDetail(user.id).then(() => setShowCreditsModal(true));
                            }}
                            className="p-2 hover:bg-blue-600/20 rounded text-blue-400 hover:text-blue-300"
                            title="Adjust credits"
                          >
                            <CreditCard size={16} />
                          </button>
                          <button
                            onClick={() => {
                              loadUserDetail(user.id).then(() => setShowDeleteModal(true));
                            }}
                            className="p-2 hover:bg-red-600/20 rounded text-red-400 hover:text-red-300"
                            title="Delete"
                          >
                            <Trash2 size={16} />
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {users.length === 0 && (
            <div className="text-center py-12 text-gray-400">
              No users found matching your criteria
            </div>
          )}
        </div>

        {/* Pagination */}
        {pages > 1 && (
          <div className="flex items-center justify-between px-6 py-4 border-t border-[var(--text)]/15">
            <span className="text-gray-400 text-sm">
              Showing {(page - 1) * pageSize + 1} - {Math.min(page * pageSize, total)} of {total}
            </span>
            <div className="flex items-center space-x-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="p-2 hover:bg-gray-700 rounded disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronLeft size={18} />
              </button>
              <span className="text-white px-4">
                Page {page} of {pages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(pages, p + 1))}
                disabled={page === pages}
                className="p-2 hover:bg-gray-700 rounded disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronRight size={18} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* User Detail Modal */}
      {showDetailModal && selectedUser && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15 max-w-2xl w-full max-h-[80vh] overflow-y-auto">
            <div className="p-6 border-b border-[var(--text)]/15 flex items-center justify-between">
              <h3 className="text-xl font-bold text-white">User Details</h3>
              <button
                onClick={() => setShowDetailModal(false)}
                className="text-gray-400 hover:text-white"
              >
                <X size={20} />
              </button>
            </div>
            {/* Tabs */}
            <div className="border-b border-[var(--text)]/15 px-6">
              <div className="flex space-x-6">
                <button
                  onClick={() => setDetailTab('details')}
                  className={`py-3 border-b-2 transition-colors text-sm font-medium ${
                    detailTab === 'details'
                      ? 'border-blue-500 text-blue-500'
                      : 'border-transparent text-gray-400 hover:text-white'
                  }`}
                >
                  Details
                </button>
                <button
                  onClick={() => {
                    setDetailTab('agent-runs');
                    if (agentRuns.length === 0 && selectedUser) {
                      loadAgentRuns(selectedUser.id);
                    }
                  }}
                  className={`py-3 border-b-2 transition-colors text-sm font-medium flex items-center space-x-2 ${
                    detailTab === 'agent-runs'
                      ? 'border-blue-500 text-blue-500'
                      : 'border-transparent text-gray-400 hover:text-white'
                  }`}
                >
                  <Bot size={14} />
                  <span>Agent Runs</span>
                </button>
              </div>
            </div>
            {detailTab === 'details' && (
              <div className="p-6 space-y-6">
                {/* Profile Header */}
                <div className="flex items-center space-x-4">
                  {selectedUser.avatar_url ? (
                    <img src={selectedUser.avatar_url} alt="" className="w-16 h-16 rounded-full" />
                  ) : (
                    <div className="w-16 h-16 rounded-full bg-gray-600 flex items-center justify-center text-white text-2xl font-medium">
                      {selectedUser.name?.charAt(0).toUpperCase()}
                    </div>
                  )}
                  <div>
                    <h4 className="text-white font-medium text-lg">{selectedUser.name}</h4>
                    <p className="text-gray-400">@{selectedUser.username}</p>
                    <p className="text-gray-500 text-sm">{selectedUser.email}</p>
                  </div>
                </div>

                {/* Status Cards */}
                <div className="grid grid-cols-3 gap-4">
                  <div className="bg-gray-700/50 rounded-lg p-4">
                    <div className="text-gray-400 text-sm">Tier</div>
                    <div className="text-white font-medium capitalize">
                      {selectedUser.subscription_tier}
                    </div>
                  </div>
                  <div className="bg-gray-700/50 rounded-lg p-4">
                    <div className="text-gray-400 text-sm">Total Credits</div>
                    <div className="text-white font-medium">
                      {selectedUser.total_credits.toLocaleString()}
                    </div>
                  </div>
                  <div className="bg-gray-700/50 rounded-lg p-4">
                    <div className="text-gray-400 text-sm">Total Spend</div>
                    <div className="text-white font-medium">
                      ${(selectedUser.total_spend / 100).toFixed(2)}
                    </div>
                  </div>
                </div>

                {/* Details */}
                <div className="space-y-3">
                  <div className="flex justify-between">
                    <span className="text-gray-400">Status</span>
                    {getStatusBadge(selectedUser)}
                  </div>
                  {selectedUser.suspended_reason && (
                    <div className="flex justify-between">
                      <span className="text-gray-400">Suspension Reason</span>
                      <span className="text-red-400 text-sm">{selectedUser.suspended_reason}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span className="text-gray-400">Projects</span>
                    <span className="text-white">
                      {selectedUser.project_count} ({selectedUser.deployed_projects_count} deployed)
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Token Usage</span>
                    <span className="text-white">
                      {(
                        selectedUser.usage_stats.total_tokens_input +
                        selectedUser.usage_stats.total_tokens_output
                      ).toLocaleString()}{' '}
                      tokens
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Credits Reset</span>
                    <span className="text-white">
                      {formatDate(selectedUser.credits_reset_date)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Last Active</span>
                    <span className="text-white">{formatDate(selectedUser.last_active_at)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Created</span>
                    <span className="text-white">{formatDate(selectedUser.created_at)}</span>
                  </div>
                </div>

                {/* Recent Projects */}
                {selectedUser.recent_projects.length > 0 && (
                  <div>
                    <h5 className="text-white font-medium mb-2">Recent Projects</h5>
                    <div className="space-y-2">
                      {selectedUser.recent_projects.map((p, i) => (
                        <div key={i} className="flex justify-between text-sm">
                          <span className="text-gray-300">{p.name}</span>
                          <span className="text-gray-500">{formatDate(p.created_at)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            {detailTab === 'agent-runs' && (
              <div className="p-6 space-y-4">
                {/* Filter */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-3">
                    <select
                      value={agentRunsFilter}
                      onChange={(e) => {
                        const newFilter = e.target.value;
                        setAgentRunsFilter(newFilter);
                        if (selectedUser) {
                          loadAgentRuns(selectedUser.id, 1, newFilter);
                        }
                      }}
                      className="bg-gray-700 text-white text-sm rounded-lg px-3 py-2 border border-[var(--text)]/15"
                    >
                      <option value="">All Statuses</option>
                      <option value="task_complete_signal">Completed</option>
                      <option value="error">Error</option>
                      <option value="cancelled">Cancelled</option>
                      <option value="resource_limit_exceeded">Resource Limit</option>
                      <option value="credit_deduction_failed">Credit Failed</option>
                    </select>
                    <span className="text-gray-500 text-sm">{agentRunsTotal} runs</span>
                  </div>
                  <button
                    onClick={() => selectedUser && loadAgentRuns(selectedUser.id, agentRunsPage)}
                    className="text-gray-400 hover:text-white transition-colors"
                    title="Refresh"
                  >
                    <RefreshCw size={16} className={agentRunsLoading ? 'animate-spin' : ''} />
                  </button>
                </div>

                {/* Table */}
                {agentRunsLoading ? (
                  <div className="flex justify-center py-8">
                    <LoadingSpinner />
                  </div>
                ) : agentRuns.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">No agent runs found</div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead className="bg-gray-750 border-b border-[var(--text)]/15">
                        <tr>
                          <th className="text-left text-gray-400 text-xs font-medium px-4 py-3">
                            Project
                          </th>
                          <th className="text-left text-gray-400 text-xs font-medium px-4 py-3">
                            Date
                          </th>
                          <th className="text-left text-gray-400 text-xs font-medium px-4 py-3">
                            Status
                          </th>
                          <th className="text-right text-gray-400 text-xs font-medium px-4 py-3">
                            Iterations
                          </th>
                          <th className="text-right text-gray-400 text-xs font-medium px-4 py-3">
                            Tool Calls
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-700">
                        {agentRuns.map((run) => (
                          <tr
                            key={run.message_id}
                            onClick={() => setViewingRunId(run.message_id)}
                            className="hover:bg-gray-700/50 transition-colors cursor-pointer"
                          >
                            <td className="px-4 py-3 text-gray-300 text-sm">
                              {run.project_name || (
                                <span className="text-gray-500 italic">No project</span>
                              )}
                            </td>
                            <td className="px-4 py-3 text-gray-400 text-sm">
                              <div className="flex items-center space-x-1">
                                <Clock size={12} />
                                <span>{new Date(run.created_at).toLocaleString()}</span>
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              {(() => {
                                const reason = run.completion_reason;
                                if (reason === 'task_complete_signal')
                                  return (
                                    <span className="px-2 py-0.5 rounded-full text-xs bg-green-500/20 text-green-400">
                                      Completed
                                    </span>
                                  );
                                if (reason === 'error')
                                  return (
                                    <span className="px-2 py-0.5 rounded-full text-xs bg-red-500/20 text-red-400">
                                      Error
                                    </span>
                                  );
                                if (reason === 'cancelled')
                                  return (
                                    <span className="px-2 py-0.5 rounded-full text-xs bg-yellow-500/20 text-yellow-400">
                                      Cancelled
                                    </span>
                                  );
                                if (reason === 'resource_limit_exceeded')
                                  return (
                                    <span className="px-2 py-0.5 rounded-full text-xs bg-orange-500/20 text-orange-400">
                                      Resource Limit
                                    </span>
                                  );
                                if (reason === 'credit_deduction_failed')
                                  return (
                                    <span className="px-2 py-0.5 rounded-full text-xs bg-orange-500/20 text-orange-400">
                                      Credit Failed
                                    </span>
                                  );
                                return (
                                  <span className="px-2 py-0.5 rounded-full text-xs bg-gray-500/20 text-gray-400">
                                    {reason || 'Unknown'}
                                  </span>
                                );
                              })()}
                            </td>
                            <td className="px-4 py-3 text-gray-300 text-sm text-right">
                              {run.iterations}
                            </td>
                            <td className="px-4 py-3 text-gray-300 text-sm text-right">
                              {run.tool_calls_made}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Pagination */}
                {agentRunsPages > 1 && (
                  <div className="flex items-center justify-between pt-2">
                    <span className="text-gray-500 text-sm">
                      Page {agentRunsPage} of {agentRunsPages}
                    </span>
                    <div className="flex items-center space-x-2">
                      <button
                        onClick={() =>
                          selectedUser && loadAgentRuns(selectedUser.id, agentRunsPage - 1)
                        }
                        disabled={agentRunsPage <= 1}
                        className="p-1 text-gray-400 hover:text-white disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <ChevronLeft size={16} />
                      </button>
                      <button
                        onClick={() =>
                          selectedUser && loadAgentRuns(selectedUser.id, agentRunsPage + 1)
                        }
                        disabled={agentRunsPage >= agentRunsPages}
                        className="p-1 text-gray-400 hover:text-white disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <ChevronRight size={16} />
                      </button>
                    </div>
                  </div>
                )}

                {/* Error preview */}
                {agentRuns.some((r) => r.error) && (
                  <div className="text-xs text-gray-500 italic">
                    Click a row to view the full step-by-step execution trace
                  </div>
                )}
              </div>
            )}
            <div className="p-6 border-t border-[var(--text)]/15 flex justify-end">
              <button
                onClick={() => setShowDetailModal(false)}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Suspend Modal */}
      {showSuspendModal && selectedUser && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15 max-w-md w-full">
            <div className="p-6 border-b border-[var(--text)]/15">
              <div className="flex items-center space-x-3">
                <AlertTriangle className="text-yellow-500" size={24} />
                <h3 className="text-xl font-bold text-white">Suspend User</h3>
              </div>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-gray-300">
                You are about to suspend <strong>{selectedUser.username}</strong>. They will not be
                able to log in until unsuspended.
              </p>
              <div>
                <label className="block text-gray-400 text-sm mb-2">Reason (required)</label>
                <textarea
                  value={suspendReason}
                  onChange={(e) => setSuspendReason(e.target.value)}
                  className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20"
                  rows={3}
                  placeholder="Enter reason for suspension..."
                />
              </div>
            </div>
            <div className="p-6 border-t border-[var(--text)]/15 flex justify-end space-x-3">
              <button
                onClick={() => {
                  setShowSuspendModal(false);
                  setSuspendReason('');
                }}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={handleSuspend}
                disabled={actionLoading || !suspendReason.trim()}
                className="px-4 py-2 bg-yellow-600 hover:bg-yellow-700 text-white rounded-lg disabled:opacity-50 flex items-center space-x-2"
              >
                {actionLoading && <RefreshCw size={16} className="animate-spin" />}
                <span>Suspend User</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Modal */}
      {showDeleteModal && selectedUser && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15 max-w-md w-full">
            <div className="p-6 border-b border-[var(--text)]/15">
              <div className="flex items-center space-x-3">
                <Trash2 className="text-red-500" size={24} />
                <h3 className="text-xl font-bold text-white">Delete User</h3>
              </div>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-gray-300">
                This will soft-delete <strong>{selectedUser.username}</strong>'s account. Data will
                be permanently removed after 30 days.
              </p>
              <div>
                <label className="block text-gray-400 text-sm mb-2">
                  Type <strong>{selectedUser.email}</strong> to confirm
                </label>
                <input
                  type="email"
                  value={deleteConfirmEmail}
                  onChange={(e) => setDeleteConfirmEmail(e.target.value)}
                  className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20"
                  placeholder="Enter email to confirm"
                />
              </div>
              <div>
                <label className="block text-gray-400 text-sm mb-2">Reason (required)</label>
                <textarea
                  value={deleteReason}
                  onChange={(e) => setDeleteReason(e.target.value)}
                  className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20"
                  rows={3}
                  placeholder="Enter reason for deletion..."
                />
              </div>
            </div>
            <div className="p-6 border-t border-[var(--text)]/15 flex justify-end space-x-3">
              <button
                onClick={() => {
                  setShowDeleteModal(false);
                  setDeleteConfirmEmail('');
                  setDeleteReason('');
                }}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={
                  actionLoading ||
                  deleteConfirmEmail.toLowerCase() !== selectedUser.email.toLowerCase() ||
                  !deleteReason.trim()
                }
                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg disabled:opacity-50 flex items-center space-x-2"
              >
                {actionLoading && <RefreshCw size={16} className="animate-spin" />}
                <span>Delete User</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Credits Modal */}
      {showCreditsModal && selectedUser && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15 max-w-md w-full">
            <div className="p-6 border-b border-[var(--text)]/15">
              <div className="flex items-center space-x-3">
                <CreditCard className="text-blue-500" size={24} />
                <h3 className="text-xl font-bold text-white">Adjust Credits</h3>
              </div>
            </div>
            <div className="p-6 space-y-4">
              <div className="bg-gray-700/50 rounded-lg p-4">
                <div className="text-gray-400 text-sm">Current Balance</div>
                <div className="text-white text-2xl font-bold">
                  {selectedUser.total_credits.toLocaleString()}
                </div>
                <div className="text-gray-500 text-sm">
                  Bundled: {selectedUser.bundled_credits} | Purchased:{' '}
                  {selectedUser.purchased_credits}
                </div>
              </div>
              <div>
                <label className="block text-gray-400 text-sm mb-2">
                  Amount (positive to add, negative to remove)
                </label>
                <input
                  type="number"
                  value={creditsAmount}
                  onChange={(e) => setCreditsAmount(parseInt(e.target.value) || 0)}
                  className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20"
                  placeholder="e.g., 100 or -50"
                />
              </div>
              <div>
                <label className="block text-gray-400 text-sm mb-2">Reason (required)</label>
                <textarea
                  value={creditsReason}
                  onChange={(e) => setCreditsReason(e.target.value)}
                  className="w-full bg-gray-700 text-white rounded-lg px-4 py-2 border border-[var(--text)]/20"
                  rows={2}
                  placeholder="Enter reason for adjustment..."
                />
              </div>
              {creditsAmount !== 0 && (
                <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3">
                  <p className="text-blue-400 text-sm">
                    New balance: {selectedUser.purchased_credits + creditsAmount}
                  </p>
                </div>
              )}
            </div>
            <div className="p-6 border-t border-[var(--text)]/15 flex justify-end space-x-3">
              <button
                onClick={() => {
                  setShowCreditsModal(false);
                  setCreditsAmount(0);
                  setCreditsReason('');
                }}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={handleAdjustCredits}
                disabled={actionLoading || creditsAmount === 0 || !creditsReason.trim()}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:opacity-50 flex items-center space-x-2"
              >
                {actionLoading && <RefreshCw size={16} className="animate-spin" />}
                <span>Adjust Credits</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Agent Run Viewer Modal */}
      {viewingRunId && (
        <AgentRunViewer messageId={viewingRunId} onClose={() => setViewingRunId(null)} />
      )}
    </div>
  );
}
