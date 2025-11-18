import { useState, useEffect } from 'react';
import {
  Rocket,
  CloudArrowUp,
  CheckCircle,
  XCircle,
  Clock,
  Spinner,
  ArrowSquareOut,
  Trash,
  ArrowsClockwise,
  Plus
} from '@phosphor-icons/react';
import { deploymentsApi, deploymentCredentialsApi } from '../../lib/api';
import toast from 'react-hot-toast';
import { DeploymentModal } from '../modals/DeploymentModal';

interface DeploymentsPanelProps {
  projectSlug: string;
}

interface Deployment {
  id: string;
  provider: string;
  deployment_url: string | null;
  status: 'pending' | 'building' | 'deploying' | 'success' | 'failed';
  created_at: string;
  completed_at: string | null;
  error: string | null;
  logs: string[];
}

interface DeploymentCredential {
  id: string;
  provider: string;
  metadata: Record<string, any>;
}

export function DeploymentsPanel({ projectSlug }: DeploymentsPanelProps) {
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [credentials, setCredentials] = useState<DeploymentCredential[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDeployment, setSelectedDeployment] = useState<Deployment | null>(null);
  const [showDeployModal, setShowDeployModal] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    loadDeployments();
    loadCredentials();
  }, [projectSlug]);

  const loadDeployments = async () => {
    try {
      const data = await deploymentsApi.listProjectDeployments(projectSlug, {
        limit: 20,
        offset: 0,
      });
      setDeployments(Array.isArray(data) ? data : []);
    } catch (error: any) {
      console.error('Failed to load deployments:', error);
      toast.error(error.response?.data?.detail || 'Failed to load deployments');
    } finally {
      setLoading(false);
    }
  };

  const loadCredentials = async () => {
    try {
      const data = await deploymentCredentialsApi.list();
      setCredentials(data.credentials || []);
    } catch (error) {
      console.error('Failed to load credentials:', error);
    }
  };

  const handleDelete = async (deploymentId: string) => {
    if (!confirm('Are you sure you want to delete this deployment?')) {
      return;
    }

    setDeletingId(deploymentId);
    try {
      await deploymentsApi.delete(deploymentId);
      toast.success('Deployment deleted successfully');
      await loadDeployments();
    } catch (error: any) {
      console.error('Failed to delete deployment:', error);
      toast.error(error.response?.data?.detail || 'Failed to delete deployment');
    } finally {
      setDeletingId(null);
    }
  };

  const getStatusIcon = (status: Deployment['status']) => {
    switch (status) {
      case 'success':
        return <CheckCircle size={18} className="text-green-400" weight="fill" />;
      case 'failed':
        return <XCircle size={18} className="text-red-400" weight="fill" />;
      case 'building':
      case 'deploying':
        return <Spinner size={18} className="text-blue-400 animate-spin" />;
      case 'pending':
        return <Clock size={18} className="text-yellow-400" />;
      default:
        return <Clock size={18} className="text-gray-400" />;
    }
  };

  const getStatusColor = (status: Deployment['status']) => {
    switch (status) {
      case 'success':
        return 'text-green-400 bg-green-500/10';
      case 'failed':
        return 'text-red-400 bg-red-500/10';
      case 'building':
      case 'deploying':
        return 'text-blue-400 bg-blue-500/10';
      case 'pending':
        return 'text-yellow-400 bg-yellow-500/10';
      default:
        return 'text-gray-400 bg-gray-500/10';
    }
  };

  const getProviderColor = (provider: string) => {
    switch (provider.toLowerCase()) {
      case 'cloudflare':
        return 'text-orange-400 bg-orange-500/10';
      case 'vercel':
        return 'text-white bg-black/50';
      case 'netlify':
        return 'text-teal-400 bg-teal-500/10';
      default:
        return 'text-purple-400 bg-purple-500/10';
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="text-[var(--text)]/60">Loading deployments...</div>
      </div>
    );
  }

  return (
    <>
      <div className="h-full flex flex-col overflow-hidden">
        {/* Header */}
        <div className="p-6 border-b border-white/10">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-purple-500/20 rounded-lg">
                <Rocket size={20} className="text-purple-400" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-[var(--text)]">Deployments</h2>
                <p className="text-xs text-[var(--text)]/60">
                  Manage your project deployments
                </p>
              </div>
            </div>
            <button
              onClick={() => setShowDeployModal(true)}
              disabled={credentials.length === 0}
              className="flex items-center gap-2 bg-orange-500 hover:bg-orange-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg font-semibold transition-all text-sm"
              title={credentials.length === 0 ? 'Connect a deployment provider first in Account Settings' : 'Deploy project'}
            >
              <Plus size={16} weight="bold" />
              New Deployment
            </button>
          </div>

          {credentials.length === 0 && (
            <div className="p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-lg">
              <p className="text-xs text-yellow-400">
                You haven't connected any deployment providers yet. Go to Account Settings to connect Cloudflare, Vercel, or Netlify.
              </p>
            </div>
          )}
        </div>

        {/* Deployments List */}
        <div className="flex-1 overflow-y-auto">
          {deployments.length === 0 ? (
            <div className="flex flex-col items-center justify-center p-12 text-center">
              <div className="p-4 bg-purple-500/10 rounded-full mb-4">
                <CloudArrowUp size={40} className="text-purple-400" />
              </div>
              <h3 className="text-lg font-semibold text-[var(--text)] mb-2">
                No deployments yet
              </h3>
              <p className="text-sm text-[var(--text)]/60 mb-4">
                Deploy your project to make it live on the web
              </p>
              {credentials.length > 0 && (
                <button
                  onClick={() => setShowDeployModal(true)}
                  className="flex items-center gap-2 bg-orange-500 hover:bg-orange-600 text-white px-6 py-3 rounded-lg font-semibold transition-all"
                >
                  <Rocket size={18} weight="bold" />
                  Deploy Now
                </button>
              )}
            </div>
          ) : (
            <div className="p-6 space-y-4">
              {deployments.map((deployment) => (
                <div
                  key={deployment.id}
                  className="bg-white/5 border border-white/10 rounded-lg p-4 hover:border-white/20 transition-all cursor-pointer"
                  onClick={() => setSelectedDeployment(deployment)}
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div className={`px-3 py-1 rounded-lg text-xs font-semibold ${getProviderColor(deployment.provider)}`}>
                        {deployment.provider.charAt(0).toUpperCase() + deployment.provider.slice(1)}
                      </div>
                      <div className={`flex items-center gap-2 px-3 py-1 rounded-lg text-xs font-semibold ${getStatusColor(deployment.status)}`}>
                        {getStatusIcon(deployment.status)}
                        {deployment.status.charAt(0).toUpperCase() + deployment.status.slice(1)}
                      </div>
                    </div>
                    <span className="text-xs text-[var(--text)]/60">
                      {formatDate(deployment.created_at)}
                    </span>
                  </div>

                  {deployment.deployment_url && (
                    <div className="mb-2">
                      <a
                        href={deployment.deployment_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="flex items-center gap-2 text-sm text-blue-400 hover:text-blue-300 transition-colors"
                      >
                        <span className="truncate">{deployment.deployment_url}</span>
                        <ArrowSquareOut size={14} />
                      </a>
                    </div>
                  )}

                  {deployment.error && (
                    <div className="mb-2">
                      <p className="text-xs text-red-400 truncate">
                        Error: {deployment.error}
                      </p>
                    </div>
                  )}

                  <div className="flex items-center gap-2 mt-3 pt-3 border-t border-white/10">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        window.open(deployment.deployment_url || '#', '_blank');
                      }}
                      disabled={!deployment.deployment_url}
                      className="flex items-center gap-1 text-xs text-[var(--text)]/60 hover:text-[var(--text)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    >
                      <ArrowSquareOut size={14} />
                      Open
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(deployment.id);
                      }}
                      disabled={deletingId === deployment.id}
                      className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors ml-auto"
                    >
                      {deletingId === deployment.id ? (
                        <Spinner size={14} className="animate-spin" />
                      ) : (
                        <Trash size={14} />
                      )}
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Deployment Details Modal */}
        {selectedDeployment && (
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
            onClick={() => setSelectedDeployment(null)}
          >
            <div
              className="bg-[var(--surface)] rounded-3xl w-full max-w-2xl shadow-2xl border border-white/10 max-h-[80vh] overflow-hidden flex flex-col"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Modal Header */}
              <div className="p-6 border-b border-white/10">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-3 mb-2">
                      <div className={`px-3 py-1 rounded-lg text-xs font-semibold ${getProviderColor(selectedDeployment.provider)}`}>
                        {selectedDeployment.provider.charAt(0).toUpperCase() + selectedDeployment.provider.slice(1)}
                      </div>
                      <div className={`flex items-center gap-2 px-3 py-1 rounded-lg text-xs font-semibold ${getStatusColor(selectedDeployment.status)}`}>
                        {getStatusIcon(selectedDeployment.status)}
                        {selectedDeployment.status.charAt(0).toUpperCase() + selectedDeployment.status.slice(1)}
                      </div>
                    </div>
                    <h2 className="text-xl font-bold text-[var(--text)]">Deployment Details</h2>
                    <p className="text-sm text-[var(--text)]/60 mt-1">
                      Created {formatDate(selectedDeployment.created_at)}
                    </p>
                  </div>
                  <button
                    onClick={() => setSelectedDeployment(null)}
                    className="text-[var(--text)]/60 hover:text-[var(--text)] transition-colors"
                  >
                    <XCircle size={24} />
                  </button>
                </div>
              </div>

              {/* Modal Content */}
              <div className="flex-1 overflow-y-auto p-6 space-y-4">
                {selectedDeployment.deployment_url && (
                  <div>
                    <h3 className="text-sm font-semibold text-[var(--text)] mb-2">Deployment URL</h3>
                    <a
                      href={selectedDeployment.deployment_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-2 text-blue-400 hover:text-blue-300 transition-colors"
                    >
                      <span className="break-all">{selectedDeployment.deployment_url}</span>
                      <ArrowSquareOut size={16} />
                    </a>
                  </div>
                )}

                {selectedDeployment.error && (
                  <div>
                    <h3 className="text-sm font-semibold text-[var(--text)] mb-2">Error</h3>
                    <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg">
                      <p className="text-sm text-red-400">{selectedDeployment.error}</p>
                    </div>
                  </div>
                )}

                {selectedDeployment.logs && selectedDeployment.logs.length > 0 && (
                  <div>
                    <h3 className="text-sm font-semibold text-[var(--text)] mb-2">Deployment Logs</h3>
                    <div className="bg-black/50 rounded-lg p-4 font-mono text-xs max-h-96 overflow-y-auto">
                      {selectedDeployment.logs.map((log, index) => (
                        <div key={index} className="text-[var(--text)]/80 whitespace-pre-wrap break-words">
                          {log}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Modal Footer */}
              <div className="p-6 border-t border-white/10 flex justify-end gap-3">
                <button
                  onClick={() => setSelectedDeployment(null)}
                  className="px-4 py-2 bg-white/5 border border-white/10 text-[var(--text)] rounded-lg font-semibold hover:bg-white/10 transition-all"
                >
                  Close
                </button>
                {selectedDeployment.deployment_url && (
                  <button
                    onClick={() => window.open(selectedDeployment.deployment_url || '#', '_blank')}
                    className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-semibold transition-all flex items-center gap-2"
                  >
                    <ArrowSquareOut size={16} />
                    Open Deployment
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Deployment Modal */}
      {showDeployModal && (
        <DeploymentModal
          projectSlug={projectSlug}
          isOpen={showDeployModal}
          onClose={() => setShowDeployModal(false)}
          onSuccess={() => {
            setShowDeployModal(false);
            loadDeployments();
          }}
        />
      )}
    </>
  );
}
