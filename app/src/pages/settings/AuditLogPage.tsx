import { useState, useEffect, useCallback } from 'react';
import toast from 'react-hot-toast';
import {
  FileText,
  ChevronLeft,
  ChevronRight,
  Filter,
  X,
  Calendar,
} from 'lucide-react';
import { teamsApi } from '../../lib/api';
import { useTeam } from '../../contexts/TeamContext';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { SettingsSection, SettingsGroup } from '../../components/settings';

interface AuditLogEntry {
  id: string;
  team_id: string;
  project_id: string | null;
  user_id: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

interface AuditFilters {
  action: string;
  user_id: string;
  from_date: string;
  to_date: string;
}

const PER_PAGE = 50;

const ACTION_CATEGORIES: Record<string, string> = {
  'team.created': 'Team',
  'team.updated': 'Team',
  'team.deleted': 'Team',
  'member.invited': 'Members',
  'member.joined': 'Members',
  'member.removed': 'Members',
  'member.role_changed': 'Members',
  'project.created': 'Projects',
  'project.deleted': 'Projects',
  'project.started': 'Projects',
  'project.stopped': 'Projects',
  'billing.subscription_changed': 'Billing',
  'billing.credits_purchased': 'Billing',
};

const ACTION_COLORS: Record<string, string> = {
  Team: 'text-[var(--primary)] bg-[var(--primary)]/10',
  Members: 'text-[var(--text)] bg-[var(--surface)]',
  Projects: 'text-[var(--status-success)] bg-[var(--status-success)]/10',
  Billing: 'text-[var(--status-warning)] bg-[var(--status-warning)]/10',
};

export default function AuditLogPage() {
  const { activeTeam, membership, loading: teamLoading } = useTeam();
  const [loading, setLoading] = useState(true);
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [filters, setFilters] = useState<AuditFilters>({
    action: '',
    user_id: '',
    from_date: '',
    to_date: '',
  });

  const isAdmin = membership?.role === 'admin';

  const loadAuditLog = useCallback(async () => {
    if (!activeTeam) return;
    setLoading(true);
    try {
      const params: Record<string, string | number> = {
        page,
        per_page: PER_PAGE,
      };
      if (filters.action) params.action = filters.action;
      if (filters.user_id) params.user_id = filters.user_id;
      if (filters.from_date) params.from_date = new Date(filters.from_date).toISOString();
      if (filters.to_date) params.to_date = new Date(filters.to_date).toISOString();

      const data = await teamsApi.getAuditLog(activeTeam.slug, params);
      setEntries(data);
      setHasMore(data.length === PER_PAGE);
    } catch (error) {
      console.error('Failed to load audit log:', error);
      toast.error('Failed to load audit log');
    } finally {
      setLoading(false);
    }
  }, [activeTeam, page, filters]);

  useEffect(() => {
    if (!teamLoading && activeTeam) {
      loadAuditLog();
    } else if (!teamLoading && !activeTeam) {
      setLoading(false);
    }
  }, [teamLoading, activeTeam, loadAuditLog]);

  const handleFilterChange = (key: keyof AuditFilters, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setPage(1);
  };

  const clearFilters = () => {
    setFilters({ action: '', user_id: '', from_date: '', to_date: '' });
    setPage(1);
  };

  const hasActiveFilters = filters.action || filters.user_id || filters.from_date || filters.to_date;

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getActionCategory = (action: string): string => {
    return ACTION_CATEGORIES[action] || 'Other';
  };

  const getActionColor = (action: string): string => {
    const category = getActionCategory(action);
    return ACTION_COLORS[category] || 'text-[var(--text-muted)] bg-[var(--surface)]';
  };

  if (!teamLoading && !isAdmin) {
    return (
      <SettingsSection title="Audit Log" description="Team activity history">
        <div className="text-center py-12 text-[var(--text-muted)]">
          <p>You need admin access to view the audit log.</p>
        </div>
      </SettingsSection>
    );
  }

  if (loading && entries.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading audit log..." size={60} />
      </div>
    );
  }

  if (!activeTeam) {
    return (
      <SettingsSection title="Audit Log" description="No team selected">
        <div className="text-center py-12 text-[var(--text-muted)]">
          <p>Select a team to view audit logs.</p>
        </div>
      </SettingsSection>
    );
  }

  return (
    <SettingsSection
      title="Audit Log"
      description="Track all activity and changes within your team"
    >
      {/* Filter Bar */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`btn btn-sm flex items-center gap-1.5 ${showFilters || hasActiveFilters ? 'btn-active' : ''}`}
        >
          <Filter size={14} />
          Filters
          {hasActiveFilters && (
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary)]" />
          )}
        </button>
        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            className="btn btn-sm flex items-center gap-1"
          >
            <X size={14} />
            Clear
          </button>
        )}
        <div className="flex-1" />
        <span className="text-xs text-[var(--text-muted)]">
          Page {page}
        </span>
      </div>

      {/* Filter Panel */}
      {showFilters && (
        <SettingsGroup title="Filters">
          <div className="px-4 py-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-[var(--text-muted)] mb-1 block">Action</label>
              <select
                value={filters.action}
                onChange={(e) => handleFilterChange('action', e.target.value)}
                className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)] focus:outline-none focus:border-[var(--border-hover)]"
              >
                <option value="">All actions</option>
                <option value="team.created">Team created</option>
                <option value="team.updated">Team updated</option>
                <option value="team.deleted">Team deleted</option>
                <option value="member.invited">Member invited</option>
                <option value="member.joined">Member joined</option>
                <option value="member.removed">Member removed</option>
                <option value="member.role_changed">Role changed</option>
                <option value="project.created">Project created</option>
                <option value="project.deleted">Project deleted</option>
                <option value="project.started">Project started</option>
                <option value="project.stopped">Project stopped</option>
                <option value="billing.subscription_changed">Subscription changed</option>
                <option value="billing.credits_purchased">Credits purchased</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-[var(--text-muted)] mb-1 block">User ID</label>
              <input
                type="text"
                value={filters.user_id}
                onChange={(e) => handleFilterChange('user_id', e.target.value)}
                placeholder="Filter by user ID"
                className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)] placeholder-[var(--text-subtle)] focus:outline-none focus:border-[var(--border-hover)]"
              />
            </div>
            <div>
              <label className="text-xs text-[var(--text-muted)] mb-1 block">From Date</label>
              <div className="relative">
                <Calendar size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-subtle)]" />
                <input
                  type="date"
                  value={filters.from_date}
                  onChange={(e) => handleFilterChange('from_date', e.target.value)}
                  className="w-full pl-8 py-1 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)] focus:outline-none focus:border-[var(--border-hover)]"
                />
              </div>
            </div>
            <div>
              <label className="text-xs text-[var(--text-muted)] mb-1 block">To Date</label>
              <div className="relative">
                <Calendar size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-subtle)]" />
                <input
                  type="date"
                  value={filters.to_date}
                  onChange={(e) => handleFilterChange('to_date', e.target.value)}
                  className="w-full pl-8 py-1 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)] focus:outline-none focus:border-[var(--border-hover)]"
                />
              </div>
            </div>
          </div>
        </SettingsGroup>
      )}

      {/* Audit Log Table */}
      <SettingsGroup title="Activity">
        {loading ? (
          <div className="px-4 py-8 flex justify-center">
            <LoadingSpinner size={40} />
          </div>
        ) : entries.length === 0 ? (
          <div className="px-4 py-8 text-center text-[var(--text-muted)]">
            <FileText size={32} className="mx-auto mb-2 opacity-40" />
            <p className="text-sm">
              {hasActiveFilters ? 'No results match your filters' : 'No audit log entries yet'}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {entries.map((entry) => (
              <div
                key={entry.id}
                className="px-4 py-3 hover:bg-[var(--surface)] transition-colors"
              >
                <div className="flex items-start gap-3">
                  {/* Action badge */}
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-medium mt-0.5 flex-shrink-0 ${getActionColor(entry.action)}`}
                  >
                    {getActionCategory(entry.action)}
                  </span>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-[var(--text)]">
                      <span className="font-medium">{entry.action}</span>
                      {entry.resource_type && (
                        <span className="text-[var(--text-muted)]">
                          {' '}on {entry.resource_type}
                        </span>
                      )}
                    </p>
                    {entry.details && Object.keys(entry.details).length > 0 && (
                      <p className="text-xs text-[var(--text-muted)] mt-0.5 truncate">
                        {JSON.stringify(entry.details)}
                      </p>
                    )}
                  </div>

                  {/* Timestamp and IP */}
                  <div className="text-right flex-shrink-0">
                    <p className="text-xs text-[var(--text-muted)]">
                      {formatDate(entry.created_at)}
                    </p>
                    {entry.ip_address && (
                      <p className="text-[10px] text-[var(--text-subtle)] mt-0.5">
                        {entry.ip_address}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </SettingsGroup>

      {/* Pagination */}
      {(page > 1 || hasMore) && (
        <div className="flex items-center justify-between">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="btn btn-sm flex items-center gap-1 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <ChevronLeft size={14} />
            Previous
          </button>
          <span className="text-xs text-[var(--text-muted)]">
            Page {page}
          </span>
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={!hasMore}
            className="btn btn-sm flex items-center gap-1 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Next
            <ChevronRight size={14} />
          </button>
        </div>
      )}
    </SettingsSection>
  );
}
