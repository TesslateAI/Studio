import { useState, useEffect, useRef } from 'react';
import {
  Rocket,
  X,
  CheckCircle,
  XCircle,
  Clock,
  Spinner,
  ArrowSquareOut,
  Trash,
  Plus,
  CloudArrowUp
} from '@phosphor-icons/react';
import { deploymentsApi } from '../lib/api';
import toast from 'react-hot-toast';

interface DeploymentsDropdownProps {
  projectSlug: string;
  isOpen: boolean;
  onClose: () => void;
  onOpenDeployModal: () => void;
  onDeploymentChange?: () => void;
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

export function DeploymentsDropdown({
  projectSlug,
  isOpen,
  onClose,
  onOpenDeployModal,
  onDeploymentChange
}: DeploymentsDropdownProps) {
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen) {
      loadDeployments();
    }
  }, [isOpen, projectSlug]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        onClose();
      }
    }

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen, onClose]);

  const loadDeployments = async () => {
    try {
      setLoading(true);
      const data = await deploymentsApi.listProjectDeployments(projectSlug, {
        limit: 10,
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

  const handleDelete = async (deploymentId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Are you sure you want to delete this deployment?')) {
      return;
    }

    setDeletingId(deploymentId);
    try {
      await deploymentsApi.delete(deploymentId);
      toast.success('Deployment deleted successfully');
      await loadDeployments();
      if (onDeploymentChange) {
        onDeploymentChange();
      }
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
        return <CheckCircle size={16} className="text-green-400" weight="fill" />;
      case 'failed':
        return <XCircle size={16} className="text-red-400" weight="fill" />;
      case 'building':
      case 'deploying':
        return <Spinner size={16} className="text-blue-400 animate-spin" />;
      case 'pending':
        return <Clock size={16} className="text-yellow-400" />;
      default:
        return <Clock size={16} className="text-gray-400" />;
    }
  };

  const getStatusColor = (status: Deployment['status']) => {
    switch (status) {
      case 'success':
        return 'text-green-400';
      case 'failed':
        return 'text-red-400';
      case 'building':
      case 'deploying':
        return 'text-blue-400';
      case 'pending':
        return 'text-yellow-400';
      default:
        return 'text-gray-400';
    }
  };

  const getProviderColor = (provider: string) => {
    switch (provider.toLowerCase()) {
      case 'cloudflare':
        return 'text-orange-400';
      case 'vercel':
        return 'text-white';
      case 'netlify':
        return 'text-teal-400';
      default:
        return 'text-purple-400';
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

  if (!isOpen) return null;

  return (
    <div
      ref={dropdownRef}
      className="absolute top-full right-0 mt-2 w-[480px] max-h-[600px] bg-[var(--surface)] border border-[var(--sidebar-border)] rounded-2xl shadow-2xl overflow-hidden flex flex-col z-50"
    >
        {/* Header */}
        <div className="p-4 border-b border-[var(--sidebar-border)] bg-[var(--bg)]/30">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Rocket size={20} className="text-[var(--primary)]" weight="bold" />
              <h3 className="text-base font-semibold text-[var(--text)]">Deployments</h3>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 hover:bg-[var(--sidebar-hover)] rounded-lg transition-colors"
            >
              <X size={18} className="text-[var(--text)]/60" />
            </button>
          </div>
          <button
            onClick={() => {
              onClose();
              onOpenDeployModal();
            }}
            className="w-full flex items-center justify-center gap-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white px-4 py-2.5 rounded-lg font-semibold transition-all text-sm"
          >
            <Plus size={16} weight="bold" />
            New Deployment
          </button>
        </div>

        {/* Deployments List */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Spinner size={24} className="animate-spin text-[var(--primary)]" />
            </div>
          ) : deployments.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-6 text-center">
              <div className="p-3 bg-[var(--primary)]/10 rounded-full mb-3">
                <CloudArrowUp size={32} className="text-[var(--primary)]" />
              </div>
              <h4 className="text-sm font-semibold text-[var(--text)] mb-1">
                No deployments yet
              </h4>
              <p className="text-xs text-[var(--text)]/60">
                Deploy your project to make it live on the web
              </p>
            </div>
          ) : (
            <div className="p-3 space-y-2">
              {deployments.map((deployment) => (
                <div
                  key={deployment.id}
                  className="bg-[var(--bg)]/50 border border-[var(--sidebar-border)] rounded-lg p-3 hover:border-[var(--text)]/20 transition-all"
                >
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <span className={`text-xs font-semibold ${getProviderColor(deployment.provider)}`}>
                        {deployment.provider.charAt(0).toUpperCase() + deployment.provider.slice(1)}
                      </span>
                      <div className={`flex items-center gap-1.5 ${getStatusColor(deployment.status)}`}>
                        {getStatusIcon(deployment.status)}
                        <span className="text-xs font-medium">
                          {deployment.status.charAt(0).toUpperCase() + deployment.status.slice(1)}
                        </span>
                      </div>
                    </div>
                    <span className="text-xs text-[var(--text)]/50">
                      {formatDate(deployment.created_at)}
                    </span>
                  </div>

                  {deployment.deployment_url && (
                    <a
                      href={deployment.deployment_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors mb-2 truncate"
                    >
                      <span className="truncate">{deployment.deployment_url}</span>
                      <ArrowSquareOut size={12} className="flex-shrink-0" />
                    </a>
                  )}

                  {deployment.error && (
                    <p className="text-xs text-red-400 mb-2 line-clamp-1">
                      Error: {deployment.error}
                    </p>
                  )}

                  <div className="flex items-center gap-2 pt-2 border-t border-[var(--sidebar-border)]">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        window.open(deployment.deployment_url || '#', '_blank');
                      }}
                      disabled={!deployment.deployment_url}
                      className="flex items-center gap-1 text-xs text-[var(--text)]/60 hover:text-[var(--text)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    >
                      <ArrowSquareOut size={12} />
                      Open
                    </button>
                    <button
                      onClick={(e) => handleDelete(deployment.id, e)}
                      disabled={deletingId === deployment.id}
                      className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors ml-auto"
                    >
                      {deletingId === deployment.id ? (
                        <Spinner size={12} className="animate-spin" />
                      ) : (
                        <Trash size={12} />
                      )}
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
      </div>
    </div>
  );
}
