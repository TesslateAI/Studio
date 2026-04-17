import { useState, useEffect, useCallback } from 'react';
import {
  Activity,
  Server,
  Database,
  Cloud,
  AlertTriangle,
  CheckCircle,
  XCircle,
  RefreshCw,
  Clock,
  HardDrive,
  Box,
  Eye,
  RotateCw,
  Trash2,
  ChevronRight,
  Search,
} from 'lucide-react';
import { getAuthHeaders } from '../../lib/api';
import toast from 'react-hot-toast';
import { LoadingSpinner } from '../PulsingGridSpinner';

interface ServiceHealth {
  service: string;
  status: 'up' | 'down' | 'degraded';
  response_time_ms: number;
  error: string | null;
}

interface HealthResponse {
  overall_status: 'operational' | 'degraded' | 'outage';
  services: ServiceHealth[];
  incidents: Array<{
    service: string;
    status: string;
    error: string | null;
    time: string;
  }>;
  checked_at: string;
}

interface Namespace {
  namespace: string;
  project_id: string;
  project_name: string;
  owner_username: string;
  owner_email: string | null;
  status: string;
  pods: string;
  storage_gb: number;
  created_at: string | null;
}

interface NamespaceDetail {
  namespace: string;
  status: string;
  project: {
    id: string;
    name: string | null;
    slug: string | null;
  };
  owner: {
    id: string | null;
    username: string | null;
    email: string | null;
  };
  pods: Array<{
    name: string;
    status: string;
    ready: boolean;
    restarts: number;
    created_at: string | null;
  }>;
  pvcs: Array<{
    name: string;
    status: string;
    storage: string;
    storage_class: string | null;
  }>;
  ingresses: Array<{
    host: string;
    tls: boolean;
  }>;
  created_at: string | null;
}

export default function SystemHealth() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [namespaces, setNamespaces] = useState<Namespace[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [activeTab, setActiveTab] = useState<'services' | 'kubernetes'>('services');
  const [selectedNamespace, setSelectedNamespace] = useState<NamespaceDetail | null>(null);
  const [showNamespaceModal, setShowNamespaceModal] = useState(false);
  const [showLogsModal, setShowLogsModal] = useState(false);
  const [logs, setLogs] = useState<string>('');
  const [selectedPod, setSelectedPod] = useState<{ namespace: string; pod: string } | null>(null);
  const [nsSearch, setNsSearch] = useState('');
  const [nsPage, setNsPage] = useState(1);
  const [nsTotal, setNsTotal] = useState(0);
  const [nsPages, setNsPages] = useState(0);

  const loadHealth = useCallback(async () => {
    try {
      const response = await fetch('/api/admin/health', {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load health data');

      const data: HealthResponse = await response.json();
      setHealth(data);
    } catch (error) {
      console.error('Failed to load health:', error);
      toast.error('Failed to load system health');
    }
  }, []);

  const loadNamespaces = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (nsSearch) params.append('search', nsSearch);
      params.append('page', nsPage.toString());
      params.append('page_size', '20');

      const response = await fetch(`/api/admin/k8s/namespaces?${params.toString()}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        if (data.message === 'Kubernetes mode not enabled') {
          setNamespaces([]);
          return;
        }
        throw new Error('Failed to load namespaces');
      }

      const data = await response.json();
      setNamespaces(data.namespaces || []);
      setNsTotal(data.total);
      setNsPages(data.pages);
    } catch (error) {
      console.error('Failed to load namespaces:', error);
    }
  }, [nsSearch, nsPage]);

  useEffect(() => {
    const loadAll = async () => {
      setLoading(true);
      await Promise.all([loadHealth(), loadNamespaces()]);
      setLoading(false);
    };
    loadAll();
  }, [loadHealth, loadNamespaces]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await Promise.all([loadHealth(), loadNamespaces()]);
    setRefreshing(false);
    toast.success('Health data refreshed');
  };

  const loadNamespaceDetail = async (namespace: string) => {
    try {
      const response = await fetch(`/api/admin/k8s/namespaces/${namespace}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load namespace details');

      const data: NamespaceDetail = await response.json();
      setSelectedNamespace(data);
      setShowNamespaceModal(true);
    } catch (error) {
      console.error('Failed to load namespace details:', error);
      toast.error('Failed to load namespace details');
    }
  };

  const loadPodLogs = async (namespace: string, pod: string) => {
    try {
      const response = await fetch(
        `/api/admin/k8s/namespaces/${namespace}/logs/${pod}?tail_lines=200`,
        {
          headers: getAuthHeaders(),
          credentials: 'include',
        }
      );

      if (!response.ok) throw new Error('Failed to load logs');

      const data = await response.json();
      setLogs(data.logs);
      setSelectedPod({ namespace, pod });
      setShowLogsModal(true);
    } catch (error) {
      console.error('Failed to load pod logs:', error);
      toast.error('Failed to load pod logs');
    }
  };

  const restartPod = async (namespace: string, pod: string) => {
    if (!confirm(`Restart pod ${pod}?`)) return;

    try {
      const response = await fetch(`/api/admin/k8s/namespaces/${namespace}/pods/${pod}/restart`, {
        method: 'POST',
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to restart pod');

      toast.success('Pod restart initiated');
      setTimeout(() => loadNamespaceDetail(namespace), 2000);
    } catch (error) {
      console.error('Failed to restart pod:', error);
      toast.error('Failed to restart pod');
    }
  };

  const deleteNamespace = async (namespace: string) => {
    const reason = prompt('Enter reason for deleting this namespace:');
    if (!reason) return;

    try {
      const response = await fetch(
        `/api/admin/k8s/namespaces/${namespace}?reason=${encodeURIComponent(reason)}`,
        {
          method: 'DELETE',
          headers: getAuthHeaders(),
          credentials: 'include',
        }
      );

      if (!response.ok) throw new Error('Failed to delete namespace');

      toast.success('Namespace deletion initiated');
      setShowNamespaceModal(false);
      loadNamespaces();
    } catch (error) {
      console.error('Failed to delete namespace:', error);
      toast.error('Failed to delete namespace');
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'up':
      case 'operational':
        return <CheckCircle className="text-green-500" size={20} />;
      case 'down':
      case 'outage':
        return <XCircle className="text-red-500" size={20} />;
      case 'degraded':
        return <AlertTriangle className="text-yellow-500" size={20} />;
      default:
        return <Clock className="text-gray-500" size={20} />;
    }
  };

  const getServiceIcon = (service: string) => {
    switch (service.toLowerCase()) {
      case 'database':
        return <Database size={20} />;
      case 'litellm':
        return <Cloud size={20} />;
      case 'kubernetes':
        return <Box size={20} />;
      default:
        return <Server size={20} />;
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'Unknown';
    return new Date(dateStr).toLocaleString();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <LoadingSpinner message="Loading system health..." size={60} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <Activity className="text-blue-500" size={24} />
          <h2 className="text-2xl font-bold text-white">System Health</h2>
          {health && (
            <span
              className={`px-3 py-1 rounded-full text-sm font-medium ${
                health.overall_status === 'operational'
                  ? 'bg-green-500/20 text-green-400'
                  : health.overall_status === 'degraded'
                    ? 'bg-yellow-500/20 text-yellow-400'
                    : 'bg-red-500/20 text-red-400'
              }`}
            >
              {health.overall_status === 'operational'
                ? 'All Systems Operational'
                : health.overall_status === 'degraded'
                  ? 'Degraded Performance'
                  : 'System Outage'}
            </span>
          )}
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="bg-gray-700 hover:bg-gray-600 text-white px-4 py-2 rounded-lg flex items-center space-x-2 text-sm"
        >
          <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Tabs */}
      <div className="flex space-x-4 border-b border-[var(--text)]/15">
        <button
          onClick={() => setActiveTab('services')}
          className={`pb-3 px-1 border-b-2 transition-colors ${
            activeTab === 'services'
              ? 'border-blue-500 text-blue-500'
              : 'border-transparent text-gray-400 hover:text-white'
          }`}
        >
          Services
        </button>
        <button
          onClick={() => setActiveTab('kubernetes')}
          className={`pb-3 px-1 border-b-2 transition-colors ${
            activeTab === 'kubernetes'
              ? 'border-blue-500 text-blue-500'
              : 'border-transparent text-gray-400 hover:text-white'
          }`}
        >
          Kubernetes
        </button>
      </div>

      {activeTab === 'services' && health && (
        <div className="space-y-6">
          {/* Service Status Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {health.services.map((service) => (
              <div
                key={service.service}
                className="bg-gray-800 rounded-lg p-6 border border-[var(--text)]/15"
              >
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center space-x-3">
                    <div className="text-gray-400">{getServiceIcon(service.service)}</div>
                    <h3 className="text-white font-medium capitalize">{service.service}</h3>
                  </div>
                  {getStatusIcon(service.status)}
                </div>
                <div className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-400">Status</span>
                    <span
                      className={`capitalize ${
                        service.status === 'up'
                          ? 'text-green-400'
                          : service.status === 'down'
                            ? 'text-red-400'
                            : 'text-yellow-400'
                      }`}
                    >
                      {service.status}
                    </span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-400">Response Time</span>
                    <span
                      className={`${
                        service.response_time_ms < 100
                          ? 'text-green-400'
                          : service.response_time_ms < 500
                            ? 'text-yellow-400'
                            : 'text-red-400'
                      }`}
                    >
                      {service.response_time_ms}ms
                    </span>
                  </div>
                  {service.error && (
                    <div className="mt-2 p-2 bg-red-500/10 rounded text-red-400 text-xs">
                      {service.error}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Recent Incidents */}
          {health.incidents.length > 0 && (
            <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15">
              <div className="p-4 border-b border-[var(--text)]/15">
                <h3 className="text-white font-medium flex items-center space-x-2">
                  <AlertTriangle className="text-yellow-500" size={18} />
                  <span>Recent Incidents (24h)</span>
                </h3>
              </div>
              <div className="divide-y divide-gray-700">
                {health.incidents.map((incident, idx) => (
                  <div key={idx} className="p-4 flex items-center justify-between">
                    <div className="flex items-center space-x-3">
                      {getStatusIcon(incident.status)}
                      <div>
                        <span className="text-white capitalize">{incident.service}</span>
                        {incident.error && (
                          <p className="text-gray-400 text-sm">{incident.error}</p>
                        )}
                      </div>
                    </div>
                    <span className="text-gray-500 text-sm">{formatDate(incident.time)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Last Check */}
          <div className="text-center text-gray-500 text-sm">
            Last checked: {formatDate(health.checked_at)}
          </div>
        </div>
      )}

      {activeTab === 'kubernetes' && (
        <div className="space-y-6">
          {/* Search */}
          <div className="bg-gray-800 rounded-lg p-4 border border-[var(--text)]/15">
            <div className="relative">
              <Search
                className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
                size={18}
              />
              <input
                type="text"
                placeholder="Search namespaces..."
                value={nsSearch}
                onChange={(e) => {
                  setNsSearch(e.target.value);
                  setNsPage(1);
                }}
                className="w-full bg-gray-700 text-white rounded-lg pl-10 pr-4 py-2 border border-[var(--text)]/20"
              />
            </div>
          </div>

          {/* Namespace Stats */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-gray-800 rounded-lg p-4 border border-[var(--text)]/15">
              <div className="text-gray-400 text-sm">Active Namespaces</div>
              <div className="text-white text-2xl font-bold">{nsTotal}</div>
            </div>
            <div className="bg-gray-800 rounded-lg p-4 border border-[var(--text)]/15">
              <div className="text-gray-400 text-sm">Total Pods</div>
              <div className="text-white text-2xl font-bold">
                {namespaces.reduce((sum, ns) => {
                  const [running] = ns.pods.split('/').map(Number);
                  return sum + (running || 0);
                }, 0)}
              </div>
            </div>
            <div className="bg-gray-800 rounded-lg p-4 border border-[var(--text)]/15">
              <div className="text-gray-400 text-sm">Total Storage</div>
              <div className="text-white text-2xl font-bold">
                {namespaces.reduce((sum, ns) => sum + ns.storage_gb, 0)} GB
              </div>
            </div>
          </div>

          {/* Namespaces Table */}
          <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15 overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-750 border-b border-[var(--text)]/15">
                <tr>
                  <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">
                    Namespace
                  </th>
                  <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Project</th>
                  <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Owner</th>
                  <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Pods</th>
                  <th className="text-left px-6 py-3 text-gray-400 font-medium text-sm">Storage</th>
                  <th className="text-right px-6 py-3 text-gray-400 font-medium text-sm">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {namespaces.map((ns) => (
                  <tr key={ns.namespace} className="hover:bg-gray-700/50 transition-colors">
                    <td className="px-6 py-4">
                      <div className="text-white font-mono text-sm">{ns.namespace}</div>
                      <div className="text-gray-500 text-xs">{ns.status}</div>
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-gray-300">{ns.project_name}</span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-gray-300">@{ns.owner_username}</div>
                      {ns.owner_email && (
                        <div className="text-gray-500 text-xs">{ns.owner_email}</div>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`${
                          ns.pods.startsWith('0/')
                            ? 'text-red-400'
                            : ns.pods.split('/')[0] === ns.pods.split('/')[1]
                              ? 'text-green-400'
                              : 'text-yellow-400'
                        }`}
                      >
                        {ns.pods}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-gray-300">{ns.storage_gb} GB</span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center justify-end space-x-2">
                        <button
                          onClick={() => loadNamespaceDetail(ns.namespace)}
                          className="p-2 hover:bg-gray-600 rounded text-gray-400 hover:text-white"
                          title="View details"
                        >
                          <Eye size={16} />
                        </button>
                        <button
                          onClick={() => deleteNamespace(ns.namespace)}
                          className="p-2 hover:bg-red-600/20 rounded text-red-400 hover:text-red-300"
                          title="Delete namespace"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {namespaces.length === 0 && (
              <div className="text-center py-12 text-gray-400">
                {nsSearch ? 'No namespaces found matching your search' : 'No active namespaces'}
              </div>
            )}

            {/* Pagination */}
            {nsPages > 1 && (
              <div className="flex items-center justify-between px-6 py-4 border-t border-[var(--text)]/15">
                <span className="text-gray-400 text-sm">
                  Page {nsPage} of {nsPages}
                </span>
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => setNsPage((p) => Math.max(1, p - 1))}
                    disabled={nsPage === 1}
                    className="p-2 hover:bg-gray-700 rounded disabled:opacity-50"
                  >
                    <ChevronRight size={18} className="rotate-180" />
                  </button>
                  <button
                    onClick={() => setNsPage((p) => Math.min(nsPages, p + 1))}
                    disabled={nsPage === nsPages}
                    className="p-2 hover:bg-gray-700 rounded disabled:opacity-50"
                  >
                    <ChevronRight size={18} />
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Namespace Detail Modal */}
      {showNamespaceModal && selectedNamespace && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15 max-w-3xl w-full max-h-[80vh] overflow-y-auto">
            <div className="p-6 border-b border-[var(--text)]/15 flex items-center justify-between sticky top-0 bg-gray-800">
              <h3 className="text-xl font-bold text-white font-mono">
                {selectedNamespace.namespace}
              </h3>
              <button
                onClick={() => setShowNamespaceModal(false)}
                className="text-gray-400 hover:text-white"
              >
                ×
              </button>
            </div>
            <div className="p-6 space-y-6">
              {/* Info */}
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-gray-700/50 rounded-lg p-4">
                  <div className="text-gray-400 text-sm">Project</div>
                  <div className="text-white">{selectedNamespace.project.name || 'Unknown'}</div>
                </div>
                <div className="bg-gray-700/50 rounded-lg p-4">
                  <div className="text-gray-400 text-sm">Owner</div>
                  <div className="text-white">@{selectedNamespace.owner.username || 'Unknown'}</div>
                </div>
              </div>

              {/* Pods */}
              <div>
                <h4 className="text-white font-medium mb-3 flex items-center space-x-2">
                  <Box size={18} />
                  <span>Pods ({selectedNamespace.pods.length})</span>
                </h4>
                <div className="space-y-2">
                  {selectedNamespace.pods.map((pod) => (
                    <div
                      key={pod.name}
                      className="bg-gray-700/50 rounded-lg p-4 flex items-center justify-between"
                    >
                      <div>
                        <div className="text-white font-mono text-sm">{pod.name}</div>
                        <div className="flex items-center space-x-3 text-sm mt-1">
                          <span
                            className={
                              pod.status === 'Running' ? 'text-green-400' : 'text-yellow-400'
                            }
                          >
                            {pod.status}
                          </span>
                          <span className="text-gray-500">{pod.restarts} restarts</span>
                        </div>
                      </div>
                      <div className="flex items-center space-x-2">
                        <button
                          onClick={() => loadPodLogs(selectedNamespace.namespace, pod.name)}
                          className="p-2 hover:bg-gray-600 rounded text-gray-400 hover:text-white"
                          title="View logs"
                        >
                          <Eye size={16} />
                        </button>
                        <button
                          onClick={() => restartPod(selectedNamespace.namespace, pod.name)}
                          className="p-2 hover:bg-yellow-600/20 rounded text-yellow-400 hover:text-yellow-300"
                          title="Restart pod"
                        >
                          <RotateCw size={16} />
                        </button>
                      </div>
                    </div>
                  ))}
                  {selectedNamespace.pods.length === 0 && (
                    <p className="text-gray-400 text-sm">No pods in this namespace</p>
                  )}
                </div>
              </div>

              {/* PVCs */}
              {selectedNamespace.pvcs.length > 0 && (
                <div>
                  <h4 className="text-white font-medium mb-3 flex items-center space-x-2">
                    <HardDrive size={18} />
                    <span>Storage</span>
                  </h4>
                  <div className="space-y-2">
                    {selectedNamespace.pvcs.map((pvc) => (
                      <div
                        key={pvc.name}
                        className="bg-gray-700/50 rounded-lg p-3 flex items-center justify-between"
                      >
                        <div>
                          <div className="text-white font-mono text-sm">{pvc.name}</div>
                          <div className="text-gray-500 text-xs">{pvc.storage_class}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-white">{pvc.storage}</div>
                          <div
                            className={`text-xs ${pvc.status === 'Bound' ? 'text-green-400' : 'text-yellow-400'}`}
                          >
                            {pvc.status}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Ingresses */}
              {selectedNamespace.ingresses.length > 0 && (
                <div>
                  <h4 className="text-white font-medium mb-3 flex items-center space-x-2">
                    <Cloud size={18} />
                    <span>Ingresses</span>
                  </h4>
                  <div className="space-y-2">
                    {selectedNamespace.ingresses.map((ing, idx) => (
                      <div
                        key={idx}
                        className="bg-gray-700/50 rounded-lg p-3 flex items-center justify-between"
                      >
                        <span className="text-white font-mono text-sm">{ing.host}</span>
                        <span
                          className={`text-xs ${ing.tls ? 'text-green-400' : 'text-yellow-400'}`}
                        >
                          {ing.tls ? 'HTTPS' : 'HTTP'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div className="p-6 border-t border-[var(--text)]/15 flex justify-between">
              <button
                onClick={() => deleteNamespace(selectedNamespace.namespace)}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg"
              >
                Delete Namespace
              </button>
              <button
                onClick={() => setShowNamespaceModal(false)}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Logs Modal */}
      {showLogsModal && selectedPod && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15 max-w-4xl w-full max-h-[80vh] overflow-hidden flex flex-col">
            <div className="p-4 border-b border-[var(--text)]/15 flex items-center justify-between">
              <h3 className="text-lg font-bold text-white">
                Logs: <span className="font-mono text-blue-400">{selectedPod.pod}</span>
              </h3>
              <button
                onClick={() => setShowLogsModal(false)}
                className="text-gray-400 hover:text-white"
              >
                ×
              </button>
            </div>
            <div className="flex-1 overflow-auto p-4 bg-gray-900">
              <pre className="text-gray-300 text-sm font-mono whitespace-pre-wrap">
                {logs || 'No logs available'}
              </pre>
            </div>
            <div className="p-4 border-t border-[var(--text)]/15 flex justify-end">
              <button
                onClick={() => loadPodLogs(selectedPod.namespace, selectedPod.pod)}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg mr-2 flex items-center space-x-2"
              >
                <RefreshCw size={16} />
                <span>Refresh</span>
              </button>
              <button
                onClick={() => setShowLogsModal(false)}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg"
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
