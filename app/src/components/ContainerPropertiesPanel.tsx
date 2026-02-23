import { useState, useEffect, useCallback } from 'react';
import {
  X,
  Play,
  Square,
  ArrowClockwise,
  Plus,
  Trash,
  PencilSimple,
  Check,
  Lock,
  Key,
  Rocket,
  Link,
  LinkBreak,
  CloudArrowUp,
  Spinner,
  Gear,
} from '@phosphor-icons/react';
import api, { projectsApi, deploymentsApi } from '../lib/api';
import { toast } from 'react-hot-toast';
import { connectionEvents } from '../utils/connectionEvents';
import {
  ExternalServiceCredentialModal,
  type ExternalServiceItem,
} from './ExternalServiceCredentialModal';
import { ProviderConnectModal } from './modals/ProviderConnectModal';

interface SavedEnvVar {
  key: string;
  isEditing: boolean;
  pendingValue: string;
}

interface ContainerPropertiesPanelProps {
  containerId: string;
  containerName: string;
  containerStatus: string;
  projectSlug: string;
  onClose: () => void;
  onStatusChange?: (newStatus: string) => void;
  onNameChange?: (newName: string) => void;
  port?: number;
  containerType?: 'base' | 'service';
  deploymentProvider?: 'vercel' | 'netlify' | 'cloudflare' | null;
  onDeploymentProviderChange?: (provider: 'vercel' | 'netlify' | 'cloudflare' | null) => void;
}

// Deployment provider display info
const DEPLOYMENT_PROVIDERS = {
  vercel: { name: 'Vercel', icon: '▲', color: 'bg-white text-black', borderColor: 'border-gray-300' },
  netlify: { name: 'Netlify', icon: '◆', color: 'bg-[#00C7B7] text-white', borderColor: 'border-[#00A799]' },
  cloudflare: { name: 'Cloudflare', icon: '🔥', color: 'bg-[#F38020] text-white', borderColor: 'border-[#D97218]' },
};

export const ContainerPropertiesPanel = ({
  containerId,
  containerName,
  containerStatus,
  projectSlug,
  onClose,
  onStatusChange,
  onNameChange,
  port,
  containerType = 'base',
  deploymentProvider,
  onDeploymentProviderChange,
}: ContainerPropertiesPanelProps) => {
  const [savedEnvVars, setSavedEnvVars] = useState<SavedEnvVar[]>([]);
  const [busyKeys, setBusyKeys] = useState<Set<string>>(new Set());
  const [isAdding, setIsAdding] = useState(false);
  const [newEnvKey, setNewEnvKey] = useState('');
  const [newEnvValue, setNewEnvValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isEditingName, setIsEditingName] = useState(false);
  const [editedName, setEditedName] = useState(containerName);
  const [isRenamingContainer, setIsRenamingContainer] = useState(false);
  const [deploymentMode, setDeploymentMode] = useState<string>('container');
  const [serviceSlug, setServiceSlug] = useState<string | null>(null);
  const [serviceOutputs, setServiceOutputs] = useState<Record<string, string> | null>(null);
  const [isCredentialModalOpen, setIsCredentialModalOpen] = useState(false);
  const [credentialServiceItem, setCredentialServiceItem] = useState<ExternalServiceItem | null>(
    null
  );
  const [hasDeploymentCredentials, setHasDeploymentCredentials] = useState<Record<string, boolean>>({});
  const [isLoadingCredentials, setIsLoadingCredentials] = useState(false);
  const [showProviderConnectModal, setShowProviderConnectModal] = useState(false);
  const [connectModalDefaultProvider, setConnectModalDefaultProvider] = useState<'vercel' | 'netlify' | 'cloudflare' | undefined>(undefined);
  const [pendingTargetChange, setPendingTargetChange] = useState<'vercel' | 'netlify' | 'cloudflare' | null>(null);
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [isDeploying, setIsDeploying] = useState(false);

  const isExternalService = deploymentMode === 'external' && !!serviceSlug;

  const fetchContainerDetailsCallback = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await api.get(`/api/projects/${projectSlug}/containers/${containerId}`);
      const keys: string[] = response.data.env_var_keys || [];
      setSavedEnvVars(keys.map((key) => ({ key, isEditing: false, pendingValue: '' })));
      setDeploymentMode(response.data.deployment_mode || 'container');
      setServiceSlug(response.data.service_slug || null);
      setServiceOutputs(response.data.service_outputs || null);
    } catch (error: unknown) {
      console.error('Failed to fetch container details:', error);
      if ((error as { response?: { status?: number } }).response?.status === 404) {
        toast.error('Container not found. Please refresh the page to sync with the latest data.');
        onClose();
      } else {
        toast.error('Failed to load container details');
      }
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onClose is stable enough; including it causes infinite re-fetch loops since parent passes an inline arrow function
  }, [containerId, projectSlug]);

  useEffect(() => {
    fetchContainerDetailsCallback();
    if (containerType === 'base') {
      fetchDeploymentCredentials();
    }
  }, [fetchContainerDetailsCallback]);

  // Re-fetch when connections change (env injection added/removed)
  useEffect(() => {
    const unsubscribe = connectionEvents.on((detail) => {
      if (detail.sourceContainerId === containerId || detail.targetContainerId === containerId) {
        fetchContainerDetailsCallback();
      }
    });
    return unsubscribe;
  }, [containerId, fetchContainerDetailsCallback]);

  // Fetch deployment credentials status
  const fetchDeploymentCredentials = useCallback(async () => {
    try {
      setIsLoadingCredentials(true);
      const response = await api.get('/api/deployments/credentials');
      const credentials = response.data || [];
      const credMap: Record<string, boolean> = {};
      credentials.forEach((cred: { provider: string }) => {
        credMap[cred.provider] = true;
      });
      setHasDeploymentCredentials(credMap);
    } catch (error) {
      console.error('Failed to fetch deployment credentials:', error);
    } finally {
      setIsLoadingCredentials(false);
    }
  }, []);

  // Handle requesting to assign a deployment target (with confirmation if needed)
  const handleRequestAssignTarget = (provider: 'vercel' | 'netlify' | 'cloudflare') => {
    // If there's already a deployment target, show confirmation
    if (deploymentProvider && deploymentProvider !== provider) {
      setPendingTargetChange(provider);
      setShowConfirmDialog(true);
    } else {
      // No existing target, assign directly
      handleAssignDeploymentTarget(provider);
    }
  };

  // Handle the actual assignment
  const handleAssignDeploymentTarget = async (provider: 'vercel' | 'netlify' | 'cloudflare') => {
    try {
      await projectsApi.assignDeploymentTarget(projectSlug, containerId, provider);
      onDeploymentProviderChange?.(provider);
      toast.success(`${DEPLOYMENT_PROVIDERS[provider].name} assigned as deployment target`);
    } catch (error) {
      console.error('Failed to assign deployment target:', error);
      toast.error('Failed to assign deployment target');
    }
  };

  // Confirm target change
  const handleConfirmTargetChange = async () => {
    if (pendingTargetChange) {
      await handleAssignDeploymentTarget(pendingTargetChange);
    }
    setShowConfirmDialog(false);
    setPendingTargetChange(null);
  };

  // Cancel target change
  const handleCancelTargetChange = () => {
    setShowConfirmDialog(false);
    setPendingTargetChange(null);
  };

  // Handle opening the connect modal
  const handleOpenConnectModal = (provider?: 'vercel' | 'netlify' | 'cloudflare') => {
    setConnectModalDefaultProvider(provider);
    setShowProviderConnectModal(true);
  };

  // Handle provider connected - refresh credentials and auto-assign if this was for the current deployment provider
  const handleProviderConnected = async (provider: string) => {
    await fetchDeploymentCredentials();
    // If this provider is the current deployment target, the status will now show as connected
  };

  // Handle removing a deployment target
  const handleRemoveDeploymentTarget = async () => {
    try {
      await projectsApi.assignDeploymentTarget(projectSlug, containerId, null);
      onDeploymentProviderChange?.(null);
      toast.success('Deployment target removed');
    } catch (error) {
      console.error('Failed to remove deployment target:', error);
      toast.error('Failed to remove deployment target');
    }
  };

  // Handle deploying a single container
  const handleDeployContainer = async () => {
    if (!deploymentProvider || !hasDeploymentCredentials[deploymentProvider]) {
      toast.error('Please connect your deployment provider first');
      return;
    }

    setIsDeploying(true);
    try {
      const result = await deploymentsApi.deployContainer(projectSlug, containerId);

      if (result.status === 'success') {
        toast.success(`Deployed to ${deploymentProvider}!`);
        if (result.deployment_url) {
          // Open deployment URL in new tab
          window.open(result.deployment_url, '_blank', 'noopener,noreferrer');
        }
      } else {
        toast.error(result.error || `Deployment failed: ${result.status}`);
      }
    } catch (error) {
      console.error('Failed to deploy container:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to deploy container');
    } finally {
      setIsDeploying(false);
    }
  };

  // Reset edited name when container changes
  useEffect(() => {
    setEditedName(containerName);
    setIsEditingName(false);
  }, [containerName]);

  const handleRenameContainer = async () => {
    if (!editedName.trim() || editedName === containerName) {
      setIsEditingName(false);
      setEditedName(containerName);
      return;
    }

    try {
      setIsRenamingContainer(true);
      await api.post(`/api/projects/${projectSlug}/containers/${containerId}/rename`, {
        new_name: editedName.trim(),
      });

      toast.success('Container renamed successfully');
      onNameChange?.(editedName.trim());
      setIsEditingName(false);
    } catch (error: unknown) {
      console.error('Failed to rename container:', error);
      const errorMessage =
        (error as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        'Failed to rename container';
      toast.error(errorMessage);
      setEditedName(containerName); // Reset on error
    } finally {
      setIsRenamingContainer(false);
    }
  };

  const handleAddEnvVar = async () => {
    if (!newEnvKey.trim()) {
      toast.error('Key cannot be empty');
      return;
    }
    if (savedEnvVars.some((e) => e.key === newEnvKey)) {
      toast.error('Key already exists');
      return;
    }
    if (!newEnvValue.trim()) {
      toast.error('Value cannot be empty');
      return;
    }

    const key = newEnvKey.trim();
    const value = newEnvValue.trim();
    setIsAdding(true);
    try {
      await api.patch(`/api/projects/${projectSlug}/containers/${containerId}`, {
        env_vars_to_set: { [key]: value },
      });
      setSavedEnvVars((prev) => [...prev, { key, isEditing: false, pendingValue: '' }]);
      setNewEnvKey('');
      setNewEnvValue('');
      toast.success(`Added ${key}`);
    } catch (error) {
      console.error('Failed to add env var:', error);
      toast.error('Failed to add variable');
    } finally {
      setIsAdding(false);
    }
  };

  const handleDeleteEnvVar = async (key: string) => {
    setBusyKeys((prev) => new Set(prev).add(key));
    try {
      await api.patch(`/api/projects/${projectSlug}/containers/${containerId}`, {
        env_vars_to_delete: [key],
      });
      setSavedEnvVars((prev) => prev.filter((e) => e.key !== key));
      toast.success(`Deleted ${key}`);
    } catch (error) {
      console.error('Failed to delete env var:', error);
      toast.error('Failed to delete variable');
    } finally {
      setBusyKeys((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  const handleStartEdit = (key: string) => {
    setSavedEnvVars((prev) =>
      prev.map((e) => (e.key === key ? { ...e, isEditing: true, pendingValue: '' } : e))
    );
  };

  const handleCancelEdit = (key: string) => {
    setSavedEnvVars((prev) =>
      prev.map((e) => (e.key === key ? { ...e, isEditing: false, pendingValue: '' } : e))
    );
  };

  const handleSaveEdit = async (key: string) => {
    const envVar = savedEnvVars.find((e) => e.key === key);
    if (!envVar || !envVar.pendingValue.trim()) {
      toast.error('Value cannot be empty');
      return;
    }

    setBusyKeys((prev) => new Set(prev).add(key));
    try {
      await api.patch(`/api/projects/${projectSlug}/containers/${containerId}`, {
        env_vars_to_set: { [key]: envVar.pendingValue.trim() },
      });
      setSavedEnvVars((prev) =>
        prev.map((e) => (e.key === key ? { ...e, isEditing: false, pendingValue: '' } : e))
      );
      toast.success(`Updated ${key}`);
    } catch (error) {
      console.error('Failed to update env var:', error);
      toast.error('Failed to update variable');
    } finally {
      setBusyKeys((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  const handleContainerAction = async (action: 'start' | 'stop' | 'restart') => {
    try {
      setIsLoading(true);

      // For start and restart, the backend returns a task_id for async processing
      // Set status to 'starting' immediately and let polling update to 'running'
      if (action === 'start' || action === 'restart') {
        onStatusChange?.('starting');
        toast.success(action === 'start' ? 'Starting container...' : 'Restarting container...');
      }

      const response = await api.post(
        `/api/projects/${projectSlug}/containers/${containerId}/${action}`
      );

      if (action === 'stop') {
        // Stop is synchronous, update status immediately
        onStatusChange?.('stopped');
        toast.success('Container stopped');
      } else {
        // For start/restart, the polling will update the status when container is running
        // Show task info in console for debugging
        console.log(`Container ${action} task started:`, response.data);
      }
    } catch (error: unknown) {
      console.error(`Failed to ${action} container:`, error);
      const errorMessage =
        (error as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        `Failed to ${action} container`;
      toast.error(errorMessage);
      // Reset to stopped on error if we were trying to start
      if (action === 'start' || action === 'restart') {
        onStatusChange?.('stopped');
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleEditCredentials = async () => {
    if (!serviceSlug) return;
    try {
      const response = await api.get(`/api/marketplace/services/${serviceSlug}`);
      const svc = response.data;
      setCredentialServiceItem({
        id: serviceSlug,
        name: svc.name,
        slug: svc.slug,
        icon: svc.icon,
        service_type: svc.service_type,
        credential_fields: svc.credential_fields || [],
        auth_type: svc.auth_type,
        docs_url: svc.docs_url,
      });
      setIsCredentialModalOpen(true);
    } catch (error) {
      console.error('Failed to fetch service definition:', error);
      toast.error('Failed to load service details');
    }
  };

  const handleCredentialSubmit = async (
    credentials: Record<string, string>,
    externalEndpoint?: string
  ) => {
    try {
      await api.put(`/api/projects/${projectSlug}/containers/${containerId}/credentials`, {
        credentials,
        external_endpoint: externalEndpoint,
      });
      toast.success('Credentials updated successfully');
      setIsCredentialModalOpen(false);
      // Refresh to pick up any changes
      fetchContainerDetailsCallback();
    } catch (error) {
      console.error('Failed to update credentials:', error);
      toast.error('Failed to update credentials');
      setIsCredentialModalOpen(false);
    }
  };

  return (
    <>
      {/* Mobile backdrop */}
      <div className="md:hidden fixed inset-0 bg-black/50 z-40" onClick={onClose} />

      {/* Panel */}
      <div className="fixed md:absolute inset-y-4 md:inset-y-auto md:top-4 md:bottom-4 right-4 w-[calc(100%-2rem)] max-w-sm md:w-80 bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] flex flex-col overflow-hidden z-50 shadow-2xl">
        {/* Header */}
        <div className="px-4 py-3 border-b border-[#2a2a2a] flex items-center justify-between flex-shrink-0">
          <div className="min-w-0 flex-1">
            {isEditingName ? (
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={editedName}
                  onChange={(e) => setEditedName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleRenameContainer();
                    if (e.key === 'Escape') {
                      setEditedName(containerName);
                      setIsEditingName(false);
                    }
                  }}
                  className="flex-1 px-2 py-1 bg-[var(--bg)] border border-[var(--primary)] text-[var(--text)] rounded text-sm font-semibold focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                  autoFocus
                  disabled={isRenamingContainer}
                />
                <button
                  onClick={handleRenameContainer}
                  disabled={isRenamingContainer}
                  className="p-1 hover:bg-green-500/20 rounded transition-colors"
                  title="Save name"
                >
                  <Check size={16} className="text-green-400" />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-[var(--text)] truncate">
                  {containerName}
                </h2>
                <button
                  onClick={() => setIsEditingName(true)}
                  className="p-1 hover:bg-[var(--sidebar-hover)] rounded transition-colors flex-shrink-0"
                  title="Rename container"
                >
                  <PencilSimple size={14} className="text-[var(--text)]/60" />
                </button>
              </div>
            )}
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              <span
                className={`px-2 py-0.5 text-xs font-medium rounded flex-shrink-0 ${
                  containerStatus === 'running'
                    ? 'bg-green-500/20 text-green-400'
                    : containerStatus === 'starting'
                      ? 'bg-yellow-500/20 text-yellow-400'
                      : containerStatus === 'stopped'
                        ? 'bg-gray-500/20 text-gray-400'
                        : containerStatus === 'failed'
                          ? 'bg-red-500/20 text-red-400'
                          : containerStatus === 'connected'
                            ? 'bg-purple-500/20 text-purple-400'
                            : 'bg-gray-500/20 text-gray-400'
                }`}
              >
                {containerStatus}
              </span>
              {port && (
                <span className="px-2 py-0.5 text-xs font-medium rounded bg-blue-500/20 text-blue-400 flex-shrink-0">
                  Port: {port}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 hover:bg-[var(--sidebar-hover)] rounded-lg transition-colors flex-shrink-0 ml-2"
          >
            <X size={16} className="text-[var(--text)]" />
          </button>
        </div>

        {/* Container Controls */}
        <div className="px-3 py-2 border-b border-[var(--border-color)] flex-shrink-0">
          <p className="text-xs font-medium text-[var(--text)] mb-2">Container Controls</p>
          <div className="flex gap-1.5">
            <button
              onClick={() => handleContainerAction('start')}
              disabled={
                isLoading || containerStatus === 'running' || containerStatus === 'starting'
              }
              className="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors text-xs font-medium"
            >
              <Play size={12} weight="fill" />
              {containerStatus === 'starting' ? 'Starting...' : 'Start'}
            </button>
            <button
              onClick={() => handleContainerAction('stop')}
              disabled={
                isLoading || containerStatus === 'stopped' || containerStatus === 'connected'
              }
              className="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors text-xs font-medium"
            >
              <Square size={12} weight="fill" />
              Stop
            </button>
            <button
              onClick={() => handleContainerAction('restart')}
              disabled={
                isLoading || containerStatus === 'starting' || containerStatus === 'connected'
              }
              className="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors text-xs font-medium"
            >
              <ArrowClockwise size={12} />
              Restart
            </button>
          </div>
        </div>

        {/* Edit Credentials (external services only) */}
        {isExternalService && (
          <div className="px-3 py-2 border-b border-[var(--border-color)] flex-shrink-0">
            <button
              onClick={handleEditCredentials}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-[var(--sidebar-hover)] hover:bg-[var(--border-color)] text-[var(--text)] rounded-lg text-xs font-medium transition-colors"
            >
              <Key size={14} />
              Edit Credentials
            </button>
          </div>
        )}

        {/* Deployment Target - Only show for base containers */}
        {containerType === 'base' && (
          <div className="px-3 py-2 border-b border-[var(--border-color)] flex-shrink-0">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-medium text-[var(--text)] flex items-center gap-1.5">
                <Rocket size={12} weight="fill" />
                Deployment Target
              </p>
            </div>

            {deploymentProvider ? (
              // Show current deployment target
              <div className="space-y-2">
                <div className={`flex items-center gap-2 p-2 rounded-lg border ${DEPLOYMENT_PROVIDERS[deploymentProvider].borderColor} bg-[var(--bg)]`}>
                  <div className={`w-6 h-6 rounded flex items-center justify-center text-xs font-bold ${DEPLOYMENT_PROVIDERS[deploymentProvider].color}`}>
                    {DEPLOYMENT_PROVIDERS[deploymentProvider].icon}
                  </div>
                  <div className="flex-1">
                    <p className="text-xs font-medium text-[var(--text)]">{DEPLOYMENT_PROVIDERS[deploymentProvider].name}</p>
                    <p className="text-[10px] text-[var(--text)]/60">
                      {hasDeploymentCredentials[deploymentProvider] ? (
                        <span className="text-green-400 flex items-center gap-1">
                          <Link size={10} /> Connected
                        </span>
                      ) : (
                        <span className="text-yellow-400 flex items-center gap-1">
                          <LinkBreak size={10} /> Not connected
                        </span>
                      )}
                    </p>
                  </div>
                  <button
                    onClick={handleRemoveDeploymentTarget}
                    className="p-1 hover:bg-red-500/20 rounded transition-colors"
                    title="Remove deployment target"
                  >
                    <Trash size={12} className="text-red-400" />
                  </button>
                </div>

                {!hasDeploymentCredentials[deploymentProvider] ? (
                  <button
                    onClick={() => handleOpenConnectModal(deploymentProvider)}
                    className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-lg text-xs font-medium transition-colors"
                  >
                    <Link size={12} />
                    Connect {DEPLOYMENT_PROVIDERS[deploymentProvider].name} Account
                  </button>
                ) : (
                  <button
                    onClick={handleDeployContainer}
                    disabled={isDeploying}
                    className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg text-xs font-medium transition-colors"
                  >
                    {isDeploying ? (
                      <>
                        <Spinner size={12} className="animate-spin" />
                        Deploying...
                      </>
                    ) : (
                      <>
                        <CloudArrowUp size={12} weight="bold" />
                        Deploy to {DEPLOYMENT_PROVIDERS[deploymentProvider].name}
                      </>
                    )}
                  </button>
                )}
              </div>
            ) : (
              // Show deployment target options
              <div className="space-y-1.5">
                <p className="text-[10px] text-[var(--text)]/60 mb-2">
                  Assign a deployment target to enable external deployment
                </p>
                {Object.entries(DEPLOYMENT_PROVIDERS).map(([key, provider]) => (
                  <button
                    key={key}
                    onClick={() => handleRequestAssignTarget(key as 'vercel' | 'netlify' | 'cloudflare')}
                    className="w-full flex items-center gap-2 p-2 rounded-lg border border-[var(--border-color)] hover:border-[var(--primary)] hover:bg-[var(--bg)] transition-colors"
                  >
                    <div className={`w-6 h-6 rounded flex items-center justify-center text-xs font-bold ${provider.color}`}>
                      {provider.icon}
                    </div>
                    <span className="text-xs font-medium text-[var(--text)]">{provider.name}</span>
                    {hasDeploymentCredentials[key] && (
                      <span className="ml-auto text-[10px] text-green-400 flex items-center gap-1">
                        <Link size={10} /> Ready
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Environment Variables */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden px-3 py-2">
          <p className="text-xs font-medium text-[var(--text)] mb-2">Environment Variables</p>

          {isLoading ? (
            <div className="flex items-center justify-center py-6">
              <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-[var(--primary)]"></div>
            </div>
          ) : (
            <div className="space-y-2">
              {/* Service-provided env vars (what this service gives to connected containers) */}
              {serviceOutputs && Object.keys(serviceOutputs).length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-blue-400/80">
                    Provides to connected containers
                  </p>
                  {Object.entries(serviceOutputs).map(([key, description]) => (
                    <div
                      key={`output-${key}`}
                      className="flex gap-1.5 items-center min-w-0 px-2 py-1.5 bg-blue-500/5 border border-blue-500/15 rounded"
                      title={description}
                    >
                      <Lock size={12} className="text-blue-400/60 flex-shrink-0" />
                      <span className="text-xs font-mono text-blue-300/90 truncate flex-1 min-w-0">
                        {key}
                      </span>
                      <span className="text-[10px] text-blue-400/50 truncate max-w-[80px]">
                        {description}
                      </span>
                    </div>
                  ))}
                  <div className="border-b border-[var(--border-color)] mt-2" />
                </div>
              )}

              {/* Saved environment variables */}
              {savedEnvVars.map((envVar) => {
                const isBusy = busyKeys.has(envVar.key);
                return (
                  <div key={envVar.key} className="flex gap-1.5 items-center min-w-0">
                    <span className="text-xs font-mono text-[var(--text)] truncate flex-1 min-w-0">
                      {envVar.key}
                    </span>
                    {envVar.isEditing ? (
                      <>
                        <input
                          type="text"
                          value={envVar.pendingValue}
                          onChange={(e) =>
                            setSavedEnvVars((prev) =>
                              prev.map((ev) =>
                                ev.key === envVar.key ? { ...ev, pendingValue: e.target.value } : ev
                              )
                            )
                          }
                          placeholder="new value"
                          className="w-24 px-2 py-1 bg-[var(--bg)] border border-[var(--border-color)] text-[var(--text)] rounded text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                          autoFocus
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleSaveEdit(envVar.key);
                            if (e.key === 'Escape') handleCancelEdit(envVar.key);
                          }}
                        />
                        <button
                          onClick={() => handleSaveEdit(envVar.key)}
                          disabled={isBusy}
                          className="p-1 hover:bg-green-500/20 rounded transition-colors flex-shrink-0"
                        >
                          <Check size={12} className="text-green-400" />
                        </button>
                        <button
                          onClick={() => handleCancelEdit(envVar.key)}
                          className="p-1 hover:bg-[var(--sidebar-hover)] rounded transition-colors flex-shrink-0"
                        >
                          <X size={12} className="text-[var(--text)]/60" />
                        </button>
                      </>
                    ) : (
                      <>
                        <span className="text-xs text-[var(--text)]/40 font-mono">••••••••</span>
                        <button
                          onClick={() => handleStartEdit(envVar.key)}
                          disabled={isBusy}
                          className="p-1 hover:bg-[var(--sidebar-hover)] rounded transition-colors flex-shrink-0"
                          title="Edit value"
                        >
                          <PencilSimple size={12} className="text-[var(--text)]/60" />
                        </button>
                        <button
                          onClick={() => handleDeleteEnvVar(envVar.key)}
                          disabled={isBusy}
                          className="p-1 hover:bg-red-500/20 rounded transition-colors flex-shrink-0"
                          title="Delete"
                        >
                          <Trash size={12} className="text-red-400" />
                        </button>
                      </>
                    )}
                  </div>
                );
              })}

              {/* Add new environment variable */}
              <div className="pt-2 border-t border-[var(--border-color)]">
                <p className="text-xs font-medium text-[var(--text)]/60 mb-2">Add New Variable</p>
                <div className="space-y-1.5">
                  <input
                    type="text"
                    value={newEnvKey}
                    onChange={(e) =>
                      setNewEnvKey(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_'))
                    }
                    placeholder="KEY_NAME"
                    className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border-color)] text-[var(--text)] rounded text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                  />
                  <input
                    type="text"
                    value={newEnvValue}
                    onChange={(e) => setNewEnvValue(e.target.value)}
                    placeholder="value"
                    className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border-color)] text-[var(--text)] rounded text-xs focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                  />
                  <button
                    onClick={handleAddEnvVar}
                    disabled={isAdding}
                    className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 bg-[var(--sidebar-hover)] hover:bg-[var(--border-color)] disabled:opacity-50 text-[var(--text)] rounded text-xs font-medium transition-colors"
                  >
                    <Plus size={12} />
                    {isAdding ? 'Adding...' : 'Add Variable'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Credential edit modal for external services */}
      {credentialServiceItem && (
        <ExternalServiceCredentialModal
          isOpen={isCredentialModalOpen}
          onClose={() => setIsCredentialModalOpen(false)}
          onSubmit={handleCredentialSubmit}
          item={credentialServiceItem}
          mode="edit"
        />
      )}

      {/* Confirmation Dialog for Changing Deployment Target */}
      {showConfirmDialog && pendingTargetChange && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-[55]"
          onClick={handleCancelTargetChange}
        >
          <div
            className="bg-[var(--surface)] rounded-xl w-full max-w-sm shadow-2xl border border-white/10 p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-sm font-semibold text-[var(--text)] mb-2">
              Change Deployment Target?
            </h3>
            <p className="text-xs text-[var(--text)]/60 mb-4">
              This container is currently assigned to <strong className="text-[var(--text)]">{deploymentProvider && DEPLOYMENT_PROVIDERS[deploymentProvider].name}</strong>.
              Do you want to change it to <strong className="text-[var(--text)]">{DEPLOYMENT_PROVIDERS[pendingTargetChange].name}</strong>?
            </p>
            <div className="flex gap-2">
              <button
                onClick={handleCancelTargetChange}
                className="flex-1 px-3 py-2 bg-white/5 border border-white/10 text-[var(--text)] rounded-lg text-xs font-medium hover:bg-white/10 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmTargetChange}
                className="flex-1 px-3 py-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-lg text-xs font-medium transition-colors"
              >
                Change Target
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Provider Connect Modal */}
      <ProviderConnectModal
        isOpen={showProviderConnectModal}
        onClose={() => setShowProviderConnectModal(false)}
        onConnected={handleProviderConnected}
        defaultProvider={connectModalDefaultProvider}
        connectedProviders={Object.keys(hasDeploymentCredentials).filter(k => hasDeploymentCredentials[k])}
      />
    </>
  );
};
