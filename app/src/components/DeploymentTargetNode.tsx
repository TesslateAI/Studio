import { memo, useState } from 'react';
import { Handle, Position, type Node } from '@xyflow/react';
import { DEPLOYMENT_PROVIDERS } from '../lib/deployment-providers';
import {
  Rocket,
  X,
  CaretDown,
  CaretUp,
  ArrowCounterClockwise,
  LinkSimple,
  CheckCircle,
  XCircle,
  CircleNotch,
  Clock,
  Plus,
} from '@phosphor-icons/react';
import { PROVIDER_CREDENTIAL_HELP } from '../lib/deployment-providers';
import { InfoTooltip } from './ui/InfoTooltip';

// Provider info interface
interface ProviderInfo {
  display_name: string;
  icon: string;
  color: string;
  types: string[];
  frameworks: string[];
  supports_serverless: boolean;
  supports_static: boolean;
  supports_fullstack: boolean;
  deployment_mode: string;
}

// Connected container summary
interface ConnectedContainer {
  id: string;
  name: string;
  container_type?: string;
  framework?: string;
  status?: string;
}

// Deployment history entry
interface DeploymentHistoryEntry {
  id: string;
  version?: string;
  status: 'success' | 'failed' | 'deploying' | 'pending' | 'building';
  deployment_url?: string;
  container_id?: string;
  container_name?: string;
  created_at: string;
  completed_at?: string;
}

// Node data interface
interface DeploymentTargetNodeData extends Record<string, unknown> {
  provider: string;
  environment: 'production' | 'staging' | 'preview';
  name?: string;
  isConnected: boolean;
  providerInfo?: ProviderInfo;
  connectedContainers: ConnectedContainer[];
  deploymentHistory: DeploymentHistoryEntry[];
  onDeploy?: (targetId: string) => void;
  onDeployContainer?: (targetId: string) => void;
  onExport?: (targetId: string) => void;
  onConnect?: (targetId: string) => void;
  onEnvironmentChange?: (
    targetId: string,
    environment: 'production' | 'staging' | 'preview'
  ) => void;
  onDelete?: (targetId: string) => void;
  onRollback?: (targetId: string, deploymentId: string) => void;
  onDisconnectContainer?: (targetId: string, containerId: string) => void;
}

type DeploymentTargetNodeProps = Node<DeploymentTargetNodeData> & {
  id: string;
  data: DeploymentTargetNodeData;
};

// Provider deploy type classification — mirrors backend DeploymentManager sets
export type DeployType = 'source' | 'container' | 'export';

const CONTAINER_PUSH_PROVIDERS = new Set([
  'aws-apprunner',
  'gcp-cloudrun',
  'azure-container-apps',
  'do-container',
  'fly',
]);

const EXPORT_PROVIDERS = new Set(['dockerhub', 'ghcr', 'download']);

// eslint-disable-next-line react-refresh/only-export-components
export function getDeployType(provider: string): DeployType {
  if (EXPORT_PROVIDERS.has(provider)) return 'export';
  if (CONTAINER_PUSH_PROVIDERS.has(provider)) return 'container';
  return 'source';
}

// Derived from centralized provider config
const PROVIDER_LOGOS: Record<string, string> = Object.fromEntries(
  Object.entries(DEPLOYMENT_PROVIDERS).map(([k, v]) => [k, v.icon])
);
const PROVIDER_DISPLAY_NAMES: Record<string, string> = Object.fromEntries(
  Object.entries(DEPLOYMENT_PROVIDERS).map(([k, v]) => [k, v.displayName])
);
const PROVIDER_COLORS: Record<string, string> = Object.fromEntries(
  Object.entries(DEPLOYMENT_PROVIDERS).map(([k, v]) => [k, v.color])
);

// Status colors and icons
const STATUS_CONFIG: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  success: {
    color: 'text-green-400',
    icon: <CheckCircle size={12} weight="fill" className="text-green-400" />,
    label: 'Live',
  },
  failed: {
    color: 'text-red-400',
    icon: <XCircle size={12} weight="fill" className="text-red-400" />,
    label: 'Failed',
  },
  deploying: {
    color: 'text-yellow-400',
    icon: <CircleNotch size={12} weight="bold" className="text-yellow-400 animate-spin" />,
    label: 'Deploying',
  },
  building: {
    color: 'text-yellow-400',
    icon: <CircleNotch size={12} weight="bold" className="text-yellow-400 animate-spin" />,
    label: 'Building',
  },
  pending: {
    color: 'text-gray-400',
    icon: <Clock size={12} weight="fill" className="text-gray-400" />,
    label: 'Pending',
  },
};

// Format relative time
function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

// Custom comparison for memo
const arePropsEqual = (
  prevProps: DeploymentTargetNodeProps,
  nextProps: DeploymentTargetNodeProps
): boolean => {
  const prevData = prevProps.data;
  const nextData = nextProps.data;

  return (
    prevProps.id === nextProps.id &&
    prevData.provider === nextData.provider &&
    prevData.environment === nextData.environment &&
    prevData.name === nextData.name &&
    prevData.isConnected === nextData.isConnected &&
    prevData.connectedContainers?.length === nextData.connectedContainers?.length &&
    prevData.deploymentHistory?.length === nextData.deploymentHistory?.length &&
    prevData.deploymentHistory?.[0]?.id === nextData.deploymentHistory?.[0]?.id &&
    prevData.deploymentHistory?.[0]?.status === nextData.deploymentHistory?.[0]?.status
  );
};

const DeploymentTargetNodeComponent = ({ data, id }: DeploymentTargetNodeProps) => {
  const [isHistoryExpanded, setIsHistoryExpanded] = useState(true);
  const [isDeploying, setIsDeploying] = useState(false);

  const providerLogo = PROVIDER_LOGOS[data.provider] || '🚀';
  const providerColor = PROVIDER_COLORS[data.provider] || '#888888';
  const providerName =
    data.providerInfo?.display_name || PROVIDER_DISPLAY_NAMES[data.provider] || data.provider;

  // Route deploy action based on provider type
  const deployType = getDeployType(data.provider);

  const handleDeploy = async () => {
    if (isDeploying) return;

    const handler =
      deployType === 'container'
        ? (data.onDeployContainer ?? data.onDeploy)
        : deployType === 'export'
          ? (data.onExport ?? data.onDeploy)
          : data.onDeploy;

    if (!handler) return;

    setIsDeploying(true);
    try {
      await handler(id);
    } finally {
      setIsDeploying(false);
    }
  };

  // Determine if deploy is possible — check that the appropriate handler exists
  const hasHandler =
    deployType === 'container'
      ? !!(data.onDeployContainer ?? data.onDeploy)
      : deployType === 'export'
        ? !!(data.onExport ?? data.onDeploy)
        : !!data.onDeploy;
  const canDeploy =
    data.isConnected && data.connectedContainers.length > 0 && !isDeploying && hasHandler;

  // Button label based on deploy type
  const deployLabel =
    deployType === 'export' ? 'Export' : deployType === 'container' ? 'Push & Deploy' : 'Deploy';

  return (
    <div className="group" style={{ contain: 'layout style' }}>
      {/* Target handle on the left - containers connect TO this */}
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-[var(--primary)] !w-3 !h-3 !border-2 !border-[var(--surface)]"
        style={{ left: -6 }}
      />

      {/* Main card */}
      <div
        className="bg-[var(--surface)] rounded-xl min-w-[280px] max-w-[320px] shadow-lg border-2 overflow-hidden"
        style={{ borderColor: `${providerColor}60` }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-3 py-2"
          style={{ backgroundColor: `${providerColor}15` }}
        >
          <div className="flex items-center gap-2">
            <span className="text-lg">{providerLogo}</span>
            <div>
              <div className="text-sm font-medium text-[var(--text)]">{providerName}</div>
              <div
                className="text-xs text-[var(--text-muted)] cursor-pointer hover:text-[var(--text)] transition-colors"
                title="Click to change environment"
                onClick={(e) => {
                  e.stopPropagation();
                  const envs: Array<'production' | 'staging' | 'preview'> = [
                    'production',
                    'staging',
                    'preview',
                  ];
                  const currentIdx = envs.indexOf(data.environment);
                  const nextEnv = envs[(currentIdx + 1) % envs.length];
                  data.onEnvironmentChange?.(id, nextEnv);
                }}
              >
                {data.environment}
              </div>
            </div>
          </div>

          {/* Delete button */}
          {data.onDelete && (
            <button
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                data.onDelete?.(id);
              }}
              className="p-1 text-[var(--text-muted)] hover:text-red-400 hover:bg-red-500/10 rounded opacity-0 group-hover:opacity-100 transition-opacity"
              title="Delete deployment target"
            >
              <X size={14} weight="bold" />
            </button>
          )}
        </div>

        {/* Not Connected Warning */}
        {!data.isConnected &&
          (() => {
            const providerHelp = PROVIDER_CREDENTIAL_HELP[data.provider];
            const helpFields = providerHelp ? Object.entries(providerHelp) : [];
            return (
              <div className="px-3 py-2 bg-yellow-500/10 border-b border-yellow-500/20">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <LinkSimple size={14} className="text-yellow-500" />
                    <span className="text-xs text-yellow-500">Not Connected</span>
                    {helpFields.length > 0 && (
                      <InfoTooltip size={13}>
                        <p className="font-semibold text-[var(--text)] mb-1.5">
                          How to connect {providerName}
                        </p>
                        <div className="space-y-1.5">
                          {helpFields.map(([field, help]) => (
                            <div key={field}>
                              <span className="font-medium text-[var(--text)]/70">
                                {field
                                  .split('_')
                                  .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                                  .join(' ')}
                                :
                              </span>
                              <p className="text-[var(--text)]/60 leading-snug">{help}</p>
                            </div>
                          ))}
                        </div>
                      </InfoTooltip>
                    )}
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      data.onConnect?.(id);
                    }}
                    className="px-2 py-0.5 text-xs bg-yellow-500 text-black rounded hover:bg-yellow-400 transition-colors font-medium"
                  >
                    Connect
                  </button>
                </div>
              </div>
            );
          })()}

        {/* Connected Containers Section */}
        <div className="px-3 py-2 border-b border-[var(--border)]">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-[var(--text-muted)]">
              Deployed Containers ({data.connectedContainers.length})
            </span>
          </div>

          {data.connectedContainers.length > 0 ? (
            <div className="space-y-1.5">
              {data.connectedContainers.map((container) => (
                <div
                  key={container.id}
                  className="flex items-center justify-between bg-[var(--bg)]/50 rounded px-2 py-1"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        container.status === 'running'
                          ? 'bg-green-400'
                          : container.status === 'starting'
                            ? 'bg-yellow-400 animate-pulse'
                            : 'bg-gray-400'
                      }`}
                    />
                    <span className="text-xs text-[var(--text)]">{container.name}</span>
                    {container.framework && (
                      <span className="text-[10px] text-[var(--text-muted)] bg-[var(--surface)] px-1 rounded">
                        {container.framework}
                      </span>
                    )}
                  </div>
                  {data.onDisconnectContainer && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        data.onDisconnectContainer?.(id, container.id);
                      }}
                      className="p-0.5 text-[var(--text-muted)] hover:text-red-400 opacity-0 group-hover:opacity-100"
                      title="Disconnect container"
                    >
                      <X size={10} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-2 text-xs text-[var(--text-muted)] py-2">
              <Plus size={12} />
              <span>Connect containers by drawing edges</span>
            </div>
          )}
        </div>

        {/* Deployment History Section */}
        <div className="px-3 py-2 border-b border-[var(--border)]">
          <button
            onClick={() => setIsHistoryExpanded(!isHistoryExpanded)}
            className="flex items-center justify-between w-full text-xs text-[var(--text-muted)] hover:text-[var(--text)]"
          >
            <span>Deployment History</span>
            {isHistoryExpanded ? <CaretUp size={12} /> : <CaretDown size={12} />}
          </button>

          {isHistoryExpanded && (
            <div className="mt-2 space-y-1.5 max-h-32 overflow-y-auto">
              {data.deploymentHistory.length > 0 ? (
                data.deploymentHistory.slice(0, 5).map((deployment, index) => {
                  const statusConfig = STATUS_CONFIG[deployment.status] || STATUS_CONFIG.pending;
                  const isLatest = index === 0 && deployment.status === 'success';

                  return (
                    <div
                      key={deployment.id}
                      className="flex items-center justify-between bg-[var(--bg)]/50 rounded px-2 py-1.5"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono text-[var(--text)]">
                          {deployment.version || 'v?.?.?'}
                        </span>
                        <div className="flex items-center gap-1">
                          {statusConfig.icon}
                          {isLatest && (
                            <span className="text-[10px] text-green-400 font-medium">Live</span>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-[var(--text-muted)]">
                          {formatRelativeTime(deployment.created_at)}
                        </span>
                        {deployment.status === 'success' && !isLatest && data.onRollback && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              data.onRollback?.(id, deployment.id);
                            }}
                            className="px-1.5 py-0.5 text-[10px] text-[var(--text-muted)] hover:text-[var(--primary)] hover:bg-[var(--primary)]/10 rounded transition-colors flex items-center gap-0.5"
                            title="Rollback to this version"
                          >
                            <ArrowCounterClockwise size={10} />
                            Rollback
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="text-[10px] text-[var(--text-muted)] py-2 text-center">
                  No deployments yet
                </div>
              )}
            </div>
          )}
        </div>

        {/* Deploy Button */}
        <div className="p-3">
          <button
            onClick={handleDeploy}
            disabled={!canDeploy}
            className={`w-full py-2 px-4 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-all ${
              canDeploy
                ? 'bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white'
                : 'bg-[var(--surface-hover)] text-[var(--text-muted)] cursor-not-allowed'
            }`}
            style={canDeploy ? { backgroundColor: providerColor } : undefined}
          >
            {isDeploying ? (
              <>
                <CircleNotch size={16} weight="bold" className="animate-spin" />
                <span>{deployType === 'export' ? 'Exporting...' : 'Deploying...'}</span>
              </>
            ) : (
              <>
                <Rocket size={16} weight="fill" />
                <span>{deployLabel}</span>
              </>
            )}
          </button>

          {/* Status message */}
          {!data.isConnected && (
            <p className="text-[10px] text-[var(--text-muted)] text-center mt-2">
              Connect your {providerName} account to deploy
            </p>
          )}
          {data.isConnected && data.connectedContainers.length === 0 && (
            <p className="text-[10px] text-[var(--text-muted)] text-center mt-2">
              Connect containers to this target to deploy
            </p>
          )}
        </div>
      </div>
    </div>
  );
};

// Export memoized component
export const DeploymentTargetNode = memo(DeploymentTargetNodeComponent, arePropsEqual);

DeploymentTargetNode.displayName = 'DeploymentTargetNode';
