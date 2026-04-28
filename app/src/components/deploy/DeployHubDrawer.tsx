import { useEffect, useState, useCallback } from 'react';
import {
  X,
  Rocket,
  ArrowRight,
  CaretDown,
  CaretUp,
  CheckCircle,
  XCircle,
  Spinner,
  Clock,
  ArrowSquareOut,
  Trash,
  CloudArrowUp,
  Stack,
  Lightning,
  Package,
  GitBranch,
  ShieldCheck,
} from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import { Link } from 'react-router-dom';
import {
  deploymentsApi,
  deploymentCredentialsApi,
  deploymentTargetsApi,
} from '../../lib/api';
import { ProviderQuickGrid } from './ProviderQuickGrid';

export interface DeployHubDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  projectSlug: string;
  /** Allow showing the "Publish as App" hero. Hidden for app_runtime / viewer roles. */
  canPublish: boolean;
  onOpenPublishDrawer: () => void;
  onOpenArchitectureWithDeploymentCategory: () => void;
  onOpenDeployModal: (provider: string) => void;
  onOpenProviderConnectModal: (provider: string) => void;
  /** Bumped by the parent when credentials may have changed (e.g., after connect). */
  refreshNonce?: number;
}

interface DeploymentRow {
  id: string;
  provider: string;
  deployment_url: string | null;
  status: 'pending' | 'building' | 'deploying' | 'success' | 'failed';
  created_at: string;
  completed_at: string | null;
  error: string | null;
}

const statusIcon = (status: DeploymentRow['status']) => {
  switch (status) {
    case 'success':
      return <CheckCircle size={12} className="text-[var(--status-success)]" weight="fill" />;
    case 'failed':
      return <XCircle size={12} className="text-[var(--status-error)]" weight="fill" />;
    case 'building':
    case 'deploying':
      return <Spinner size={12} className="text-[var(--primary)] animate-spin" />;
    case 'pending':
    default:
      return <Clock size={12} className="text-[var(--text-subtle)]" />;
  }
};

const formatRelative = (iso: string) => {
  const date = new Date(iso);
  const diff = Date.now() - date.getTime();
  const m = Math.floor(diff / 60000);
  const h = Math.floor(diff / 3600000);
  const d = Math.floor(diff / 86400000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  if (h < 24) return `${h}h ago`;
  if (d < 7) return `${d}d ago`;
  return date.toLocaleDateString();
};

export function DeployHubDrawer({
  isOpen,
  onClose,
  projectSlug,
  canPublish,
  onOpenPublishDrawer,
  onOpenArchitectureWithDeploymentCategory,
  onOpenDeployModal,
  onOpenProviderConnectModal,
  refreshNonce = 0,
}: DeployHubDrawerProps) {
  const [credentials, setCredentials] = useState<Set<string>>(new Set());
  const [onGraph, setOnGraph] = useState<Set<string>>(new Set());
  const [deployments, setDeployments] = useState<DeploymentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [recentExpanded, setRecentExpanded] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [credsRes, targetsRes, deploysRes] = await Promise.all([
        deploymentCredentialsApi.list().catch(() => ({ credentials: [] })),
        deploymentTargetsApi.list(projectSlug).catch(() => []),
        deploymentsApi
          .listProjectDeployments(projectSlug, { limit: 10, offset: 0 })
          .catch(() => []),
      ]);
      const credSet = new Set<string>(
        (credsRes.credentials || []).map((c: { provider: string }) => c.provider)
      );
      const graphSet = new Set<string>(
        (Array.isArray(targetsRes) ? targetsRes : []).map(
          (t: { provider: string }) => t.provider
        )
      );
      setCredentials(credSet);
      setOnGraph(graphSet);
      setDeployments(Array.isArray(deploysRes) ? (deploysRes as DeploymentRow[]) : []);
    } finally {
      setLoading(false);
    }
  }, [projectSlug]);

  useEffect(() => {
    if (!isOpen) return;
    void loadAll();
  }, [isOpen, refreshNonce, loadAll]);

  const handleChipClick = useCallback(
    (provider: string) => {
      if (credentials.has(provider)) {
        onOpenDeployModal(provider);
      } else {
        onOpenProviderConnectModal(provider);
      }
    },
    [credentials, onOpenDeployModal, onOpenProviderConnectModal]
  );

  const handleDeleteDeployment = useCallback(
    async (deploymentId: string, evt: React.MouseEvent) => {
      evt.stopPropagation();
      if (!confirm('Delete this deployment record?')) return;
      setDeletingId(deploymentId);
      try {
        await deploymentsApi.delete(deploymentId);
        toast.success('Deployment deleted');
        await loadAll();
      } catch (err: unknown) {
        const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail;
        toast.error(detail || 'Failed to delete deployment');
      } finally {
        setDeletingId(null);
      }
    },
    [loadAll]
  );

  if (!isOpen) return null;

  const recentSlice = recentExpanded ? deployments : deployments.slice(0, 3);

  return (
    <>
      {/* Click-away backdrop — soft, non-blocking */}
      <div
        className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[1px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        role="dialog"
        aria-label="Deploy"
        className="fixed top-0 right-0 z-50 flex h-full w-full max-w-md flex-col border-l bg-[var(--surface)] shadow-2xl"
        style={{ borderColor: 'var(--border)' }}
      >
        {/* Header */}
        <header
          className="flex items-center justify-between px-5 py-4 border-b"
          style={{ borderColor: 'var(--border)' }}
        >
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-small)] bg-[var(--primary)]/10">
              <Rocket size={16} weight="fill" className="text-[var(--primary)]" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-[var(--text)]">Deploy</h2>
              <p className="text-[11px] text-[var(--text-subtle)]">
                Ship your project anywhere
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-icon btn-sm"
            aria-label="Close deploy panel"
          >
            <X size={14} />
          </button>
        </header>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Hero — Publish as a Tesslate App */}
          {canPublish && (
            <section
              className="relative overflow-hidden rounded-[var(--radius-large)] border p-5"
              style={{
                borderColor: 'var(--border-hover)',
                background:
                  'linear-gradient(135deg, color-mix(in srgb, var(--primary) 14%, var(--surface)) 0%, var(--surface) 70%)',
              }}
            >
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-medium)] bg-[var(--primary)] text-white">
                  <Stack size={20} weight="fill" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-[15px] font-semibold text-[var(--text)]">
                    Deploy as a Tesslate App
                  </h3>
                  <p className="mt-1 text-xs text-[var(--text-muted)]">
                    Publish to the Tesslate marketplace and turn this project into a
                    distributable, agent-callable app.
                  </p>
                  <ul className="mt-3 space-y-1.5 text-[11px] text-[var(--text-muted)]">
                    <li className="flex items-center gap-2">
                      <Lightning size={12} weight="fill" className="text-[var(--primary)]" />
                      Callable by agents — turn flows into tools
                    </li>
                    <li className="flex items-center gap-2">
                      <Package size={12} weight="fill" className="text-[var(--primary)]" />
                      Scales with replicas, no infra babysitting
                    </li>
                    <li className="flex items-center gap-2">
                      <GitBranch size={12} weight="fill" className="text-[var(--primary)]" />
                      Versioned, forkable, reviewable
                    </li>
                    <li className="flex items-center gap-2">
                      <ShieldCheck size={12} weight="fill" className="text-[var(--primary)]" />
                      Discoverable on the marketplace, with built-in approval
                    </li>
                  </ul>
                  <button
                    type="button"
                    onClick={() => {
                      onClose();
                      onOpenPublishDrawer();
                    }}
                    className="btn btn-filled mt-4 w-full justify-center"
                  >
                    <Rocket size={14} weight="bold" />
                    <span>Publish as App</span>
                  </button>
                </div>
              </div>
            </section>
          )}

          {/* Card B — Add provider to architecture graph */}
          <button
            type="button"
            onClick={() => {
              onClose();
              onOpenArchitectureWithDeploymentCategory();
            }}
            className="group flex w-full items-center gap-3 rounded-[var(--radius-large)] border bg-[var(--surface)] p-4 text-left transition-colors hover:bg-[var(--surface-hover)] hover:border-[var(--border-hover)]"
            style={{ borderColor: 'var(--border)' }}
          >
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-medium)] bg-[var(--surface-hover)] text-[var(--primary)]">
              <CloudArrowUp size={18} weight="fill" />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-[13px] font-semibold text-[var(--text)]">
                Add a deployment provider on the graph
              </h3>
              <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                Drop a provider onto the architecture canvas to wire connections,
                environments, and rollback.
              </p>
            </div>
            <ArrowRight
              size={16}
              weight="bold"
              className="shrink-0 text-[var(--text-subtle)] transition-transform group-hover:translate-x-0.5 group-hover:text-[var(--text)]"
            />
          </button>

          {/* Quick deploy grid */}
          <section>
            <header className="mb-2.5 flex items-center justify-between">
              <div>
                <h3 className="text-[12px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Quick deploy
                </h3>
                <p className="text-[10.5px] text-[var(--text-subtle)]">
                  Click a connected provider to deploy, or connect a new one.
                </p>
              </div>
              <Link
                to="/settings"
                onClick={onClose}
                className="text-[11px] text-[var(--primary)] hover:underline"
              >
                Manage credentials
              </Link>
            </header>
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Spinner size={18} className="animate-spin text-[var(--text-subtle)]" />
              </div>
            ) : (
              <ProviderQuickGrid
                connectedProviders={credentials}
                onGraphProviders={onGraph}
                onChipClick={handleChipClick}
              />
            )}
          </section>

          {/* Recent deployments */}
          <section>
            <button
              type="button"
              onClick={() => setRecentExpanded((v) => !v)}
              className="flex w-full items-center justify-between rounded-[var(--radius-medium)] px-2 py-2 text-left hover:bg-[var(--surface-hover)] transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className="text-[12px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Recent deployments
                </span>
                {deployments.length > 0 && (
                  <span className="rounded-full bg-[var(--surface-hover)] px-1.5 py-0.5 text-[9px] font-semibold text-[var(--text-muted)]">
                    {deployments.length}
                  </span>
                )}
              </div>
              {recentExpanded ? (
                <CaretUp size={12} weight="bold" className="text-[var(--text-subtle)]" />
              ) : (
                <CaretDown size={12} weight="bold" className="text-[var(--text-subtle)]" />
              )}
            </button>
            {deployments.length === 0 ? (
              <p className="px-2 pt-1.5 text-[11px] text-[var(--text-subtle)]">
                No deployments yet.
              </p>
            ) : (
              <ul className="mt-1 space-y-1">
                {recentSlice.map((d) => (
                  <li
                    key={d.id}
                    className="group rounded-[var(--radius-small)] border bg-[var(--surface)] px-3 py-2 transition-colors hover:bg-[var(--surface-hover)]"
                    style={{ borderColor: 'var(--border)' }}
                  >
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-[11px] font-semibold text-[var(--text)] capitalize">
                        {d.provider}
                      </span>
                      <span className="flex items-center gap-1 text-[10px] font-medium">
                        {statusIcon(d.status)}
                        <span
                          className={
                            d.status === 'success'
                              ? 'text-[var(--status-success)]'
                              : d.status === 'failed'
                                ? 'text-[var(--status-error)]'
                                : d.status === 'building' || d.status === 'deploying'
                                  ? 'text-[var(--primary)]'
                                  : 'text-[var(--text-subtle)]'
                          }
                        >
                          {d.status.charAt(0).toUpperCase() + d.status.slice(1)}
                        </span>
                      </span>
                      <span className="ml-auto text-[10px] text-[var(--text-subtle)]">
                        {formatRelative(d.created_at)}
                      </span>
                    </div>
                    {d.deployment_url && (
                      <a
                        href={d.deployment_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="flex items-center gap-1 text-[10px] text-[var(--primary)] hover:underline truncate"
                      >
                        <span className="truncate">{d.deployment_url}</span>
                        <ArrowSquareOut size={10} className="shrink-0" />
                      </a>
                    )}
                    {d.error && (
                      <p className="text-[10px] text-[var(--status-error)] line-clamp-1">
                        {d.error}
                      </p>
                    )}
                    <div className="mt-1.5 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      {d.deployment_url && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            window.open(d.deployment_url || '#', '_blank', 'noopener');
                          }}
                          className="btn btn-sm"
                        >
                          <ArrowSquareOut size={11} />
                          Open
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={(e) => handleDeleteDeployment(d.id, e)}
                        disabled={deletingId === d.id}
                        className="btn btn-sm btn-danger ml-auto disabled:opacity-50"
                      >
                        {deletingId === d.id ? (
                          <Spinner size={11} className="animate-spin" />
                        ) : (
                          <Trash size={11} />
                        )}
                        Delete
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </aside>
    </>
  );
}
