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
  assignedDeploymentTarget?: string | null;
  containerName?: string;
}

// Provider display info
const PROVIDER_INFO: Record<string, { name: string; icon: string }> = {
  vercel: { name: 'Vercel', icon: '▲' },
  netlify: { name: 'Netlify', icon: '◆' },
  cloudflare: { name: 'Cloudflare', icon: '🔥' },
};

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
  onDeploymentChange,
  assignedDeploymentTarget,
  containerName,
}: DeploymentsDropdownProps) {
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Check if there's an active deployment in progress
  const hasActiveDeployment = deployments.some(
    d => d.status === 'building' || d.status === 'deploying' || d.status === 'pending'
  );

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
    } catch (error: unknown) {
      console.error('Failed to load deployments:', error);
      toast.error((error as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'Failed to load deployments');
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
    } catch (error: unknown) {
      console.error('Failed to delete deployment:', error);
      toast.error((error as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'Failed to delete deployment');
    } finally {
      setDeletingId(null);
    }
  };

  const getStatusIcon = (status: Deployment['status']) => {
    switch (status) {
      case 'success':
        return <CheckCircle size={13} className="text-[var(--status-success)]" weight="fill" />;
      case 'failed':
        return <XCircle size={13} className="text-[var(--status-error)]" weight="fill" />;
      case 'building':
      case 'deploying':
        return <Spinner size={13} className="text-[var(--primary)] animate-spin" />;
      case 'pending':
        return <Clock size={13} className="text-[var(--status-warning)]" />;
      default:
        return <Clock size={13} className="text-[var(--text-subtle)]" />;
    }
  };

  const getStatusColor = (status: Deployment['status']) => {
    switch (status) {
      case 'success':
        return 'text-[var(--status-success)]';
      case 'failed':
        return 'text-[var(--status-error)]';
      case 'building':
      case 'deploying':
        return 'text-[var(--primary)]';
      case 'pending':
        return 'text-[var(--status-warning)]';
      default:
        return 'text-[var(--text-subtle)]';
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
      className="absolute top-full right-0 mt-1 w-[400px] max-h-[480px] bg-[var(--surface)] border rounded-[var(--radius-medium)] overflow-hidden flex flex-col z-50"
      style={{ borderWidth: 'var(--border-width)', borderColor: 'var(--border-hover)' }}
    >
      {/* Header */}
      <div className="px-3 pt-3 pb-2 flex-shrink-0">
        <div className="flex items-center justify-between mb-2.5">
          <div className="flex items-center gap-2">
            <Rocket size={15} className="text-[var(--primary)]" weight="bold" />
            <span className="text-xs font-semibold text-[var(--text)]">Deployments</span>
          </div>
          <button onClick={onClose} className="btn btn-icon btn-sm">
            <X size={13} />
          </button>
        </div>

        {/* Assigned deployment target */}
        {assignedDeploymentTarget && PROVIDER_INFO[assignedDeploymentTarget] && (
          <div className="mb-2.5 px-3 py-2 rounded-[var(--radius-small)] bg-[var(--surface-hover)] border border-[var(--border)]">
            <div className="flex items-center gap-2">
              <span className="text-xs">{PROVIDER_INFO[assignedDeploymentTarget].icon}</span>
              <div className="flex-1 min-w-0">
                <p className="text-[11px] font-medium text-[var(--text)]">
                  Target: {PROVIDER_INFO[assignedDeploymentTarget].name}
                </p>
                {containerName && (
                  <p className="text-[10px] text-[var(--text-subtle)]">
                    {containerName}
                  </p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* New deployment button */}
        <button
          onClick={() => {
            if (!hasActiveDeployment) {
              onClose();
              onOpenDeployModal();
            }
          }}
          disabled={hasActiveDeployment}
          className={`w-full ${hasActiveDeployment ? 'btn opacity-50 cursor-not-allowed' : 'btn btn-filled'}`}
        >
          {hasActiveDeployment ? (
            <>
              <Spinner size={14} className="animate-spin" />
              <span>Deployment in Progress</span>
            </>
          ) : (
            <>
              <Plus size={14} weight="bold" />
              <span>New Deployment</span>
            </>
          )}
        </button>
      </div>

      {/* Divider */}
      <div className="h-px bg-[var(--border)] flex-shrink-0" />

      {/* Deployments List */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Spinner size={18} className="animate-spin text-[var(--text-subtle)]" />
          </div>
        ) : deployments.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 px-6 text-center">
            <CloudArrowUp size={24} className="text-[var(--text-subtle)] mb-2" />
            <p className="text-xs font-medium text-[var(--text-muted)] mb-0.5">
              No deployments yet
            </p>
            <p className="text-[10px] text-[var(--text-subtle)]">
              Deploy your project to make it live
            </p>
          </div>
        ) : (
          <div className="p-1.5 space-y-0.5">
            {deployments.map((deployment) => (
              <div
                key={deployment.id}
                className="rounded-[var(--radius-small)] px-3 py-2.5 hover:bg-[var(--surface-hover)] transition-colors group"
              >
                {/* Top row: provider + status + time */}
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[11px] font-semibold text-[var(--text)]">
                    {deployment.provider.charAt(0).toUpperCase() + deployment.provider.slice(1)}
                  </span>
                  <div className={`flex items-center gap-1 ${getStatusColor(deployment.status)}`}>
                    {getStatusIcon(deployment.status)}
                    <span className="text-[10px] font-medium">
                      {deployment.status.charAt(0).toUpperCase() + deployment.status.slice(1)}
                    </span>
                  </div>
                  <span className="text-[10px] text-[var(--text-subtle)] ml-auto">
                    {formatDate(deployment.created_at)}
                  </span>
                </div>

                {/* URL */}
                {deployment.deployment_url && (
                  <a
                    href={deployment.deployment_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="flex items-center gap-1 text-[10px] text-[var(--primary)] hover:underline transition-colors mb-1 truncate"
                  >
                    <span className="truncate">{deployment.deployment_url}</span>
                    <ArrowSquareOut size={10} className="flex-shrink-0" />
                  </a>
                )}

                {/* Error */}
                {deployment.error && (
                  <p className="text-[10px] text-[var(--status-error)] mb-1 line-clamp-1">
                    {deployment.error}
                  </p>
                )}

                {/* Actions — visible on hover */}
                <div className="flex items-center gap-1 pt-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      window.open(deployment.deployment_url || '#', '_blank');
                    }}
                    disabled={!deployment.deployment_url}
                    className="btn btn-sm disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    <ArrowSquareOut size={12} />
                    Open
                  </button>
                  <button
                    onClick={(e) => handleDelete(deployment.id, e)}
                    disabled={deletingId === deployment.id}
                    className="btn btn-sm btn-danger disabled:opacity-50 disabled:cursor-not-allowed ml-auto"
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
