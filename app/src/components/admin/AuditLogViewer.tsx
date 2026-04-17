import { useState, useEffect, useCallback } from 'react';
import {
  Search,
  FileText,
  Download,
  ChevronLeft,
  ChevronRight,
  X,
  Eye,
  Calendar,
  User,
  Shield,
} from 'lucide-react';
import { getAuthHeaders } from '../../lib/api';
import toast from 'react-hot-toast';
import { LoadingSpinner } from '../PulsingGridSpinner';

interface AuditLog {
  id: string;
  admin_id: string | null;
  admin_username: string | null;
  action_type: string;
  target_type: string;
  target_id: string;
  reason: string | null;
  extra_data: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string | null;
}

interface AuditLogsResponse {
  logs: AuditLog[];
  total: number;
  page: number;
  pages: number;
}

const ACTION_TYPE_COLORS: Record<string, string> = {
  'user.suspend': 'bg-yellow-500/20 text-yellow-400',
  'user.unsuspend': 'bg-green-500/20 text-green-400',
  'user.delete': 'bg-red-500/20 text-red-400',
  'user.credits_adjusted': 'bg-blue-500/20 text-blue-400',
  'project.hibernate': 'bg-yellow-500/20 text-yellow-400',
  'project.transfer': 'bg-purple-500/20 text-purple-400',
  'project.delete': 'bg-red-500/20 text-red-400',
  'k8s.pod.restart': 'bg-orange-500/20 text-orange-400',
  'k8s.namespace.delete': 'bg-red-500/20 text-red-400',
};

const ACTION_TYPE_OPTIONS = [
  { value: '', label: 'All Actions' },
  { value: 'user.suspend', label: 'User Suspend' },
  { value: 'user.unsuspend', label: 'User Unsuspend' },
  { value: 'user.delete', label: 'User Delete' },
  { value: 'user.credits_adjusted', label: 'Credits Adjusted' },
  { value: 'project.hibernate', label: 'Project Hibernate' },
  { value: 'project.transfer', label: 'Project Transfer' },
  { value: 'project.delete', label: 'Project Delete' },
  { value: 'k8s.pod.restart', label: 'Pod Restart' },
  { value: 'k8s.namespace.delete', label: 'Namespace Delete' },
];

const TARGET_TYPE_OPTIONS = [
  { value: '', label: 'All Targets' },
  { value: 'user', label: 'User' },
  { value: 'project', label: 'Project' },
  { value: 'pod', label: 'Pod' },
  { value: 'namespace', label: 'Namespace' },
];

export default function AuditLogViewer() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [pages, setPages] = useState(0);

  // Filters
  const [search, setSearch] = useState('');
  const [actionTypeFilter, setActionTypeFilter] = useState('');
  const [targetTypeFilter, setTargetTypeFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  // Modal states
  const [selectedLog, setSelectedLog] = useState<AuditLog | null>(null);
  const [showDetailModal, setShowDetailModal] = useState(false);

  const loadLogs = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (search) params.append('search', search);
      if (actionTypeFilter) params.append('action_type', actionTypeFilter);
      if (targetTypeFilter) params.append('target_type', targetTypeFilter);
      if (dateFrom) params.append('date_from', new Date(dateFrom).toISOString());
      if (dateTo) params.append('date_to', new Date(dateTo).toISOString());
      params.append('page', page.toString());
      params.append('page_size', pageSize.toString());

      const response = await fetch(`/api/admin/audit-logs?${params.toString()}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load audit logs');

      const data: AuditLogsResponse = await response.json();
      setLogs(data.logs);
      setTotal(data.total);
      setPages(data.pages);
    } catch (error) {
      console.error('Failed to load audit logs:', error);
      toast.error('Failed to load audit logs');
    } finally {
      setLoading(false);
    }
  }, [search, actionTypeFilter, targetTypeFilter, dateFrom, dateTo, page, pageSize]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  const handleExport = async () => {
    try {
      const params = new URLSearchParams();
      if (actionTypeFilter) params.append('action_type', actionTypeFilter);
      if (targetTypeFilter) params.append('target_type', targetTypeFilter);
      if (dateFrom) params.append('date_from', new Date(dateFrom).toISOString());
      if (dateTo) params.append('date_to', new Date(dateTo).toISOString());

      const response = await fetch(`/api/admin/audit-logs/export?${params.toString()}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to export audit logs');

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'audit_logs_export.csv';
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      toast.success('Export downloaded');
    } catch (error) {
      console.error('Failed to export audit logs:', error);
      toast.error('Failed to export audit logs');
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString();
  };

  const formatActionType = (actionType: string) => {
    return actionType.replace(/\./g, ' → ').replace(/_/g, ' ');
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileText className="h-5 w-5 text-zinc-400" />
          <h2 className="text-lg font-semibold text-white">Audit Logs</h2>
        </div>
        <button
          onClick={handleExport}
          className="flex items-center gap-2 px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 rounded-lg text-sm text-zinc-300"
        >
          <Download className="h-4 w-4" />
          Export CSV
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-zinc-500" />
          <input
            type="text"
            placeholder="Search logs..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="w-full pl-9 pr-4 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white placeholder:text-zinc-500 focus:outline-none focus:border-zinc-700"
          />
        </div>

        <select
          value={actionTypeFilter}
          onChange={(e) => {
            setActionTypeFilter(e.target.value);
            setPage(1);
          }}
          className="px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-zinc-700"
        >
          {ACTION_TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <select
          value={targetTypeFilter}
          onChange={(e) => {
            setTargetTypeFilter(e.target.value);
            setPage(1);
          }}
          className="px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-zinc-700"
        >
          {TARGET_TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <div className="flex items-center gap-2">
          <Calendar className="h-4 w-4 text-zinc-500" />
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => {
              setDateFrom(e.target.value);
              setPage(1);
            }}
            className="px-2 py-1.5 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-zinc-700"
          />
          <span className="text-zinc-500">to</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => {
              setDateTo(e.target.value);
              setPage(1);
            }}
            className="px-2 py-1.5 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-zinc-700"
          />
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner size={32} />
        </div>
      ) : logs.length === 0 ? (
        <div className="text-center py-12 text-zinc-500">No audit logs found</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-zinc-500 border-b border-zinc-800">
                <th className="pb-3 font-medium">Time</th>
                <th className="pb-3 font-medium">Action</th>
                <th className="pb-3 font-medium">Admin</th>
                <th className="pb-3 font-medium">Target</th>
                <th className="pb-3 font-medium">Reason</th>
                <th className="pb-3 font-medium">IP</th>
                <th className="pb-3 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                  <td className="py-3 text-zinc-400 whitespace-nowrap">
                    {formatDate(log.created_at)}
                  </td>
                  <td className="py-3">
                    <span
                      className={`px-2 py-1 rounded text-xs font-medium ${ACTION_TYPE_COLORS[log.action_type] || 'bg-zinc-700 text-zinc-300'}`}
                    >
                      {formatActionType(log.action_type)}
                    </span>
                  </td>
                  <td className="py-3">
                    <div className="flex items-center gap-2">
                      <User className="h-4 w-4 text-zinc-500" />
                      <span className="text-white">{log.admin_username || '-'}</span>
                    </div>
                  </td>
                  <td className="py-3">
                    <span className="text-zinc-400">{log.target_type}:</span>
                    <span className="text-white ml-1 font-mono text-xs">
                      {log.target_id.slice(0, 8)}...
                    </span>
                  </td>
                  <td className="py-3 text-zinc-400 max-w-[200px] truncate">{log.reason || '-'}</td>
                  <td className="py-3 text-zinc-500 font-mono text-xs">{log.ip_address || '-'}</td>
                  <td className="py-3">
                    <button
                      onClick={() => {
                        setSelectedLog(log);
                        setShowDetailModal(true);
                      }}
                      className="p-1 hover:bg-zinc-700 rounded"
                    >
                      <Eye className="h-4 w-4 text-zinc-400" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {pages > 1 && (
        <div className="flex items-center justify-between pt-4">
          <span className="text-sm text-zinc-500">
            Showing {(page - 1) * pageSize + 1} - {Math.min(page * pageSize, total)} of {total} logs
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="p-2 hover:bg-zinc-800 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <ChevronLeft className="h-4 w-4 text-zinc-400" />
            </button>
            <span className="text-sm text-zinc-400">
              Page {page} of {pages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              disabled={page === pages}
              className="p-2 hover:bg-zinc-800 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <ChevronRight className="h-4 w-4 text-zinc-400" />
            </button>
          </div>
        </div>
      )}

      {/* Detail Modal */}
      {showDetailModal && selectedLog && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-zinc-900 rounded-xl border border-zinc-800 w-full max-w-2xl max-h-[80vh] overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <Shield className="h-5 w-5 text-zinc-400" />
                <h3 className="font-semibold text-white">Audit Log Details</h3>
              </div>
              <button
                onClick={() => setShowDetailModal(false)}
                className="p-1 hover:bg-zinc-800 rounded"
              >
                <X className="h-5 w-5 text-zinc-400" />
              </button>
            </div>
            <div className="p-4 space-y-4 overflow-y-auto max-h-[60vh]">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs text-zinc-500">Action Type</label>
                  <p
                    className={`mt-1 px-2 py-1 rounded text-sm font-medium inline-block ${ACTION_TYPE_COLORS[selectedLog.action_type] || 'bg-zinc-700 text-zinc-300'}`}
                  >
                    {formatActionType(selectedLog.action_type)}
                  </p>
                </div>
                <div>
                  <label className="text-xs text-zinc-500">Time</label>
                  <p className="text-white">{formatDate(selectedLog.created_at)}</p>
                </div>
                <div>
                  <label className="text-xs text-zinc-500">Admin</label>
                  <p className="text-white">{selectedLog.admin_username || '-'}</p>
                </div>
                <div>
                  <label className="text-xs text-zinc-500">IP Address</label>
                  <p className="text-white font-mono text-sm">{selectedLog.ip_address || '-'}</p>
                </div>
                <div>
                  <label className="text-xs text-zinc-500">Target Type</label>
                  <p className="text-white">{selectedLog.target_type}</p>
                </div>
                <div>
                  <label className="text-xs text-zinc-500">Target ID</label>
                  <p className="text-white font-mono text-sm">{selectedLog.target_id}</p>
                </div>
              </div>

              {selectedLog.reason && (
                <div>
                  <label className="text-xs text-zinc-500">Reason</label>
                  <p className="mt-1 text-white bg-zinc-800 rounded-lg p-3">{selectedLog.reason}</p>
                </div>
              )}

              {selectedLog.extra_data && Object.keys(selectedLog.extra_data).length > 0 && (
                <div>
                  <label className="text-xs text-zinc-500">Additional Data</label>
                  <pre className="mt-1 text-sm text-zinc-300 bg-zinc-800 rounded-lg p-3 overflow-x-auto">
                    {JSON.stringify(selectedLog.extra_data, null, 2)}
                  </pre>
                </div>
              )}
            </div>
            <div className="p-4 border-t border-zinc-800">
              <button
                onClick={() => setShowDetailModal(false)}
                className="w-full px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg text-white"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
