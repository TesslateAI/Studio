import React, { useState, useEffect, useCallback } from 'react';
import {
  Rocket,
  Eye,
  ChevronLeft,
  ChevronRight,
  X,
  CheckCircle,
  XCircle,
  Clock,
  ExternalLink,
  TrendingUp,
} from 'lucide-react';
import { getAuthHeaders } from '../../lib/api';
import toast from 'react-hot-toast';
import { LoadingSpinner } from '../PulsingGridSpinner';

interface DeploymentStats {
  summary: {
    total_deployments: number;
    successful: number;
    failed: number;
    pending: number;
    success_rate: number;
  };
  by_provider: Array<{
    provider: string;
    total: number;
    success: number;
    failed: number;
    success_rate: number;
  }>;
  by_status: Record<string, number>;
  timeline: Array<{
    date: string;
    total: number;
    success: number;
  }>;
  period: string;
}

interface DeploymentListItem {
  id: string;
  project_id: string;
  project_name: string | null;
  user_id: string;
  user_username: string | null;
  provider: string;
  deployment_id: string | null;
  deployment_url: string | null;
  version: string | null;
  status: string;
  error: string | null;
  created_at: string | null;
  completed_at: string | null;
}

interface DeploymentDetail extends DeploymentListItem {
  project: {
    id: string;
    name: string | null;
    slug: string | null;
  };
  user: {
    id: string;
    username: string | null;
    email: string | null;
  };
  logs: string[] | null;
  metadata: Record<string, unknown> | null;
  updated_at: string | null;
}

const STATUS_COLORS: Record<string, string> = {
  success: 'bg-green-500/20 text-green-400',
  failed: 'bg-red-500/20 text-red-400',
  pending: 'bg-yellow-500/20 text-yellow-400',
  building: 'bg-blue-500/20 text-blue-400',
  deploying: 'bg-purple-500/20 text-purple-400',
};

const STATUS_ICONS: Record<string, React.ReactNode> = {
  success: <CheckCircle className="h-4 w-4 text-green-400" />,
  failed: <XCircle className="h-4 w-4 text-red-400" />,
  pending: <Clock className="h-4 w-4 text-yellow-400" />,
  building: <Clock className="h-4 w-4 text-blue-400" />,
  deploying: <Rocket className="h-4 w-4 text-purple-400" />,
};

const PROVIDER_COLORS: Record<string, string> = {
  vercel: 'bg-black text-white',
  netlify: 'bg-teal-600 text-white',
  cloudflare: 'bg-orange-500 text-white',
};

export default function DeploymentMonitor() {
  const [activeTab, setActiveTab] = useState<'overview' | 'list'>('overview');
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState('30d');

  // Stats data
  const [stats, setStats] = useState<DeploymentStats | null>(null);

  // List data
  const [deployments, setDeployments] = useState<DeploymentListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [pages, setPages] = useState(0);

  // Filters
  const [_search, _setSearch] = useState('');
  const [providerFilter, setProviderFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  // Detail modal
  const [selectedDeployment, setSelectedDeployment] = useState<DeploymentDetail | null>(null);
  const [showDetailModal, setShowDetailModal] = useState(false);

  const loadStats = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(`/api/admin/deployments/stats?period=${period}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load deployment stats');

      const data: DeploymentStats = await response.json();
      setStats(data);
    } catch (error) {
      console.error('Failed to load deployment stats:', error);
      toast.error('Failed to load deployment stats');
    } finally {
      setLoading(false);
    }
  }, [period]);

  const loadDeployments = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (providerFilter) params.append('provider', providerFilter);
      if (statusFilter) params.append('status', statusFilter);
      params.append('page', page.toString());
      params.append('page_size', pageSize.toString());

      const response = await fetch(`/api/admin/deployments?${params.toString()}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load deployments');

      const data = await response.json();
      setDeployments(data.deployments);
      setTotal(data.total);
      setPages(data.pages);
    } catch (error) {
      console.error('Failed to load deployments:', error);
      toast.error('Failed to load deployments');
    } finally {
      setLoading(false);
    }
  }, [providerFilter, statusFilter, page, pageSize]);

  const loadDeploymentDetail = async (deploymentId: string) => {
    try {
      const response = await fetch(`/api/admin/deployments/${deploymentId}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load deployment details');

      const data: DeploymentDetail = await response.json();
      setSelectedDeployment(data);
      setShowDetailModal(true);
    } catch (error) {
      console.error('Failed to load deployment details:', error);
      toast.error('Failed to load deployment details');
    }
  };

  useEffect(() => {
    if (activeTab === 'overview') {
      loadStats();
    } else {
      loadDeployments();
    }
  }, [activeTab, loadStats, loadDeployments]);

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleDateString();
  };

  const formatDateTime = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString();
  };

  // Calculate max value for timeline chart
  const maxTimelineValue = stats?.timeline ? Math.max(...stats.timeline.map((t) => t.total), 1) : 1;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Rocket className="h-5 w-5 text-zinc-400" />
          <h2 className="text-lg font-semibold text-white">Deployment Monitoring</h2>
        </div>
        {activeTab === 'overview' && (
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="px-3 py-1.5 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none"
          >
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
            <option value="90d">Last 90 days</option>
          </select>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-zinc-900 rounded-lg w-fit">
        {(['overview', 'list'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === tab ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-white'
            }`}
          >
            {tab === 'overview' ? 'Overview' : 'All Deployments'}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner size={32} />
        </div>
      ) : activeTab === 'overview' && stats ? (
        <div className="space-y-6">
          {/* Summary Cards */}
          <div className="grid grid-cols-4 gap-4">
            <div className="bg-zinc-800/50 rounded-xl p-4 border border-zinc-800">
              <div className="flex items-center gap-2 text-zinc-400 mb-2">
                <Rocket className="h-4 w-4" />
                <span className="text-sm">Total Deployments</span>
              </div>
              <p className="text-2xl font-bold text-white">{stats.summary.total_deployments}</p>
            </div>
            <div className="bg-zinc-800/50 rounded-xl p-4 border border-zinc-800">
              <div className="flex items-center gap-2 text-zinc-400 mb-2">
                <CheckCircle className="h-4 w-4 text-green-400" />
                <span className="text-sm">Successful</span>
              </div>
              <p className="text-2xl font-bold text-green-400">{stats.summary.successful}</p>
            </div>
            <div className="bg-zinc-800/50 rounded-xl p-4 border border-zinc-800">
              <div className="flex items-center gap-2 text-zinc-400 mb-2">
                <XCircle className="h-4 w-4 text-red-400" />
                <span className="text-sm">Failed</span>
              </div>
              <p className="text-2xl font-bold text-red-400">{stats.summary.failed}</p>
            </div>
            <div className="bg-zinc-800/50 rounded-xl p-4 border border-zinc-800">
              <div className="flex items-center gap-2 text-zinc-400 mb-2">
                <TrendingUp className="h-4 w-4" />
                <span className="text-sm">Success Rate</span>
              </div>
              <p className="text-2xl font-bold text-white">{stats.summary.success_rate}%</p>
            </div>
          </div>

          {/* By Provider */}
          <div className="bg-zinc-800/50 rounded-xl p-4 border border-zinc-800">
            <h3 className="text-sm font-medium text-zinc-400 mb-4">Deployments by Provider</h3>
            <div className="grid grid-cols-3 gap-4">
              {stats.by_provider.map((provider) => (
                <div key={provider.provider} className="bg-zinc-900 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <span
                      className={`px-3 py-1 rounded text-sm font-medium capitalize ${PROVIDER_COLORS[provider.provider] || 'bg-zinc-700'}`}
                    >
                      {provider.provider}
                    </span>
                    <span className="text-zinc-400 text-sm">{provider.success_rate}%</span>
                  </div>
                  <div className="flex items-center gap-4 text-sm">
                    <span className="text-zinc-400">
                      Total: <span className="text-white">{provider.total}</span>
                    </span>
                    <span className="text-green-400">{provider.success} success</span>
                    <span className="text-red-400">{provider.failed} failed</span>
                  </div>
                  {/* Success rate bar */}
                  <div className="mt-2 h-2 bg-zinc-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-green-500 rounded-full"
                      style={{ width: `${provider.success_rate}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Timeline */}
          <div className="bg-zinc-800/50 rounded-xl p-4 border border-zinc-800">
            <h3 className="text-sm font-medium text-zinc-400 mb-4">Daily Deployments</h3>
            <div className="h-48 flex items-end gap-1">
              {stats.timeline.map((day, idx) => (
                <div
                  key={idx}
                  className="flex-1 flex flex-col justify-end"
                  title={`${formatDate(day.date)}: ${day.total} deployments (${day.success} success)`}
                >
                  <div
                    className="bg-green-600 rounded-t"
                    style={{
                      height: `${(day.success / maxTimelineValue) * 100}%`,
                      minHeight: day.success > 0 ? '4px' : '0',
                    }}
                  />
                  <div
                    className="bg-red-600"
                    style={{
                      height: `${((day.total - day.success) / maxTimelineValue) * 100}%`,
                      minHeight: day.total - day.success > 0 ? '4px' : '0',
                    }}
                  />
                </div>
              ))}
            </div>
            <div className="flex justify-between text-xs text-zinc-500 mt-2">
              <span>{stats.timeline.length > 0 ? formatDate(stats.timeline[0].date) : ''}</span>
              <span>
                {stats.timeline.length > 0
                  ? formatDate(stats.timeline[stats.timeline.length - 1].date)
                  : ''}
              </span>
            </div>
            <div className="flex items-center gap-4 mt-2 text-xs">
              <div className="flex items-center gap-1">
                <div className="w-3 h-3 bg-green-600 rounded" />
                <span className="text-zinc-400">Success</span>
              </div>
              <div className="flex items-center gap-1">
                <div className="w-3 h-3 bg-red-600 rounded" />
                <span className="text-zinc-400">Failed</span>
              </div>
            </div>
          </div>
        </div>
      ) : activeTab === 'list' ? (
        <div className="space-y-4">
          {/* Filters */}
          <div className="flex flex-wrap items-center gap-3">
            <select
              value={providerFilter}
              onChange={(e) => {
                setProviderFilter(e.target.value);
                setPage(1);
              }}
              className="px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none"
            >
              <option value="">All Providers</option>
              <option value="vercel">Vercel</option>
              <option value="netlify">Netlify</option>
              <option value="cloudflare">Cloudflare</option>
            </select>

            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
              className="px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none"
            >
              <option value="">All Status</option>
              <option value="success">Success</option>
              <option value="failed">Failed</option>
              <option value="pending">Pending</option>
              <option value="building">Building</option>
            </select>
          </div>

          {/* Table */}
          {deployments.length === 0 ? (
            <div className="text-center py-12 text-zinc-500">No deployments found</div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-zinc-500 border-b border-zinc-800">
                      <th className="pb-3 font-medium">Project</th>
                      <th className="pb-3 font-medium">User</th>
                      <th className="pb-3 font-medium">Provider</th>
                      <th className="pb-3 font-medium">Status</th>
                      <th className="pb-3 font-medium">URL</th>
                      <th className="pb-3 font-medium">Created</th>
                      <th className="pb-3 font-medium"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {deployments.map((deployment) => (
                      <tr
                        key={deployment.id}
                        className="border-b border-zinc-800/50 hover:bg-zinc-800/30"
                      >
                        <td className="py-3">
                          <p className="text-white">{deployment.project_name || '-'}</p>
                        </td>
                        <td className="py-3 text-zinc-400">@{deployment.user_username || '-'}</td>
                        <td className="py-3">
                          <span
                            className={`px-2 py-1 rounded text-xs font-medium capitalize ${PROVIDER_COLORS[deployment.provider] || 'bg-zinc-700'}`}
                          >
                            {deployment.provider}
                          </span>
                        </td>
                        <td className="py-3">
                          <span
                            className={`px-2 py-1 rounded text-xs font-medium flex items-center gap-1 w-fit ${STATUS_COLORS[deployment.status] || 'bg-zinc-700'}`}
                          >
                            {STATUS_ICONS[deployment.status]}
                            {deployment.status}
                          </span>
                        </td>
                        <td className="py-3">
                          {deployment.deployment_url ? (
                            <a
                              href={deployment.deployment_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-blue-400 hover:text-blue-300 flex items-center gap-1"
                            >
                              View <ExternalLink className="h-3 w-3" />
                            </a>
                          ) : (
                            <span className="text-zinc-600">-</span>
                          )}
                        </td>
                        <td className="py-3 text-zinc-400">
                          {formatDateTime(deployment.created_at)}
                        </td>
                        <td className="py-3">
                          <button
                            onClick={() => loadDeploymentDetail(deployment.id)}
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

              {/* Pagination */}
              {pages > 1 && (
                <div className="flex items-center justify-between pt-4">
                  <span className="text-sm text-zinc-500">
                    Showing {(page - 1) * pageSize + 1} - {Math.min(page * pageSize, total)} of{' '}
                    {total}
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page === 1}
                      className="p-2 hover:bg-zinc-800 rounded-lg disabled:opacity-50"
                    >
                      <ChevronLeft className="h-4 w-4 text-zinc-400" />
                    </button>
                    <span className="text-sm text-zinc-400">
                      Page {page} of {pages}
                    </span>
                    <button
                      onClick={() => setPage((p) => Math.min(pages, p + 1))}
                      disabled={page === pages}
                      className="p-2 hover:bg-zinc-800 rounded-lg disabled:opacity-50"
                    >
                      <ChevronRight className="h-4 w-4 text-zinc-400" />
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      ) : null}

      {/* Detail Modal */}
      {showDetailModal && selectedDeployment && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-zinc-900 rounded-xl border border-zinc-800 w-full max-w-2xl max-h-[80vh] overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <Rocket className="h-5 w-5 text-zinc-400" />
                <h3 className="font-semibold text-white">Deployment Details</h3>
              </div>
              <button
                onClick={() => setShowDetailModal(false)}
                className="p-1 hover:bg-zinc-800 rounded"
              >
                <X className="h-5 w-5 text-zinc-400" />
              </button>
            </div>
            <div className="p-4 space-y-4 overflow-y-auto max-h-[60vh]">
              {/* Status and Provider */}
              <div className="flex items-center gap-4">
                <span
                  className={`px-3 py-1.5 rounded text-sm font-medium capitalize ${PROVIDER_COLORS[selectedDeployment.provider] || 'bg-zinc-700'}`}
                >
                  {selectedDeployment.provider}
                </span>
                <span
                  className={`px-3 py-1.5 rounded text-sm font-medium flex items-center gap-1 ${STATUS_COLORS[selectedDeployment.status] || 'bg-zinc-700'}`}
                >
                  {STATUS_ICONS[selectedDeployment.status]}
                  {selectedDeployment.status}
                </span>
              </div>

              {/* Project and User */}
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-zinc-800/50 rounded-lg p-3">
                  <p className="text-xs text-zinc-500">Project</p>
                  <p className="text-white">{selectedDeployment.project?.name || '-'}</p>
                  <p className="text-xs text-zinc-500 font-mono">
                    {selectedDeployment.project?.slug}
                  </p>
                </div>
                <div className="bg-zinc-800/50 rounded-lg p-3">
                  <p className="text-xs text-zinc-500">User</p>
                  <p className="text-white">@{selectedDeployment.user?.username || '-'}</p>
                  <p className="text-xs text-zinc-500">{selectedDeployment.user?.email}</p>
                </div>
              </div>

              {/* Deployment URL */}
              {selectedDeployment.deployment_url && (
                <div>
                  <p className="text-xs text-zinc-500 mb-1">Deployment URL</p>
                  <a
                    href={selectedDeployment.deployment_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:text-blue-300 flex items-center gap-1"
                  >
                    {selectedDeployment.deployment_url} <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              )}

              {/* Error */}
              {selectedDeployment.error && (
                <div>
                  <p className="text-xs text-zinc-500 mb-1">Error</p>
                  <p className="text-red-400 bg-red-500/10 rounded-lg p-3 text-sm">
                    {selectedDeployment.error}
                  </p>
                </div>
              )}

              {/* Logs */}
              {selectedDeployment.logs && selectedDeployment.logs.length > 0 && (
                <div>
                  <p className="text-xs text-zinc-500 mb-1">Logs</p>
                  <pre className="text-sm text-zinc-300 bg-zinc-800 rounded-lg p-3 overflow-x-auto max-h-48 font-mono">
                    {selectedDeployment.logs.join('\n')}
                  </pre>
                </div>
              )}

              {/* Timestamps */}
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-zinc-500">Created:</span>
                  <span className="text-white ml-2">
                    {formatDateTime(selectedDeployment.created_at)}
                  </span>
                </div>
                <div>
                  <span className="text-zinc-500">Completed:</span>
                  <span className="text-white ml-2">
                    {formatDateTime(selectedDeployment.completed_at)}
                  </span>
                </div>
              </div>
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
