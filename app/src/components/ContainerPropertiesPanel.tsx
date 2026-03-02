import { useState, useEffect, useCallback, useRef } from 'react';
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
  CaretDown,
  CaretRight,
  Pause,
  ArrowLineDown,
} from '@phosphor-icons/react';
import api, { createLogStreamWebSocket } from '../lib/api';
import { toast } from 'react-hot-toast';
import { connectionEvents } from '../utils/connectionEvents';
import {
  ExternalServiceCredentialModal,
  type ExternalServiceItem,
} from './ExternalServiceCredentialModal';

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
}

export const ContainerPropertiesPanel = ({
  containerId,
  containerName,
  containerStatus,
  projectSlug,
  onClose,
  onStatusChange,
  onNameChange,
  port,
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

  const isExternalService = deploymentMode === 'external' && !!serviceSlug;

  // --- Container Logs ---
  const [isLogsOpen, setIsLogsOpen] = useState(false);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [isLogsPaused, setIsLogsPaused] = useState(false);
  const [isLogsAutoScroll, setIsLogsAutoScroll] = useState(true);
  const logContainerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const pauseBufferRef = useRef<string[]>([]);
  const isPausedRef = useRef(false);
  const isAutoScrollRef = useRef(true);
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const MAX_LOG_LINES = 500;

  useEffect(() => {
    isPausedRef.current = isLogsPaused;
  }, [isLogsPaused]);
  useEffect(() => {
    isAutoScrollRef.current = isLogsAutoScroll;
  }, [isLogsAutoScroll]);

  // Auto-scroll log container
  useEffect(() => {
    if (isLogsAutoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logLines, isLogsAutoScroll]);

  const cleanupWs = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }
    if (wsRef.current) {
      // Null out handlers BEFORE closing to prevent the onclose handler from
      // firing a zombie reconnect with a stale connectLogs closure (wrong containerId)
      wsRef.current.onclose = null;
      wsRef.current.onmessage = null;
      wsRef.current.onerror = null;
      wsRef.current.close();
      wsRef.current = null;
    }
    reconnectAttemptsRef.current = 0;
  }, []);

  const connectLogs = useCallback(() => {
    cleanupWs();

    try {
      const ws = createLogStreamWebSocket(projectSlug);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttemptsRef.current = 0;
        // Send switch_container to target this specific container
        ws.send(JSON.stringify({ type: 'switch_container', container_id: containerId }));
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
        }, 30000);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'log') {
            const line = data.data ?? '';
            if (isPausedRef.current) {
              pauseBufferRef.current.push(line);
            } else {
              setLogLines((prev) => {
                const next = [...prev, line];
                return next.length > MAX_LOG_LINES ? next.slice(-MAX_LOG_LINES) : next;
              });
            }
          } else if (data.type === 'error') {
            setLogLines((prev) => [...prev, `[ERROR] ${data.message ?? 'Unknown error'}`]);
          }
        } catch {
          /* ignore parse errors */
        }
      };

      ws.onerror = () => {};
      ws.onclose = () => {
        wsRef.current = null;
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }
        if (reconnectAttemptsRef.current < 5) {
          reconnectAttemptsRef.current++;
          const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current - 1), 15000);
          reconnectTimerRef.current = setTimeout(connectLogs, delay);
        }
      };
    } catch {
      /* ignore */
    }
  }, [projectSlug, containerId, cleanupWs]);

  // Connect/disconnect when logs section is opened/closed or container changes
  useEffect(() => {
    const streamable = containerStatus === 'running' || containerStatus === 'starting';
    if (isLogsOpen && streamable) {
      setLogLines([]);
      pauseBufferRef.current = [];
      connectLogs();
    } else if (!streamable) {
      cleanupWs();
    }
    return cleanupWs;
  }, [isLogsOpen, containerId, containerStatus, connectLogs, cleanupWs]);

  const toggleLogsPause = useCallback(() => {
    setIsLogsPaused((prev) => {
      if (prev) {
        // Flush buffer on resume
        const buffer = pauseBufferRef.current;
        pauseBufferRef.current = [];
        if (buffer.length > 0) {
          setLogLines((lines) => {
            const next = [...lines, ...buffer];
            return next.length > MAX_LOG_LINES ? next.slice(-MAX_LOG_LINES) : next;
          });
        }
      }
      return !prev;
    });
  }, []);

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

          {/* Container Logs */}
          <div className="pt-3 mt-3 border-t border-[var(--border-color)]">
            <button
              onClick={() => setIsLogsOpen((prev) => !prev)}
              className="flex items-center gap-1.5 w-full text-left mb-2"
            >
              {isLogsOpen ? (
                <CaretDown size={12} className="text-[var(--text)]/60" />
              ) : (
                <CaretRight size={12} className="text-[var(--text)]/60" />
              )}
              <span className="text-xs font-medium text-[var(--text)]">Container Logs</span>
              {isLogsOpen && (containerStatus === 'running' || containerStatus === 'starting') && (
                <span className="ml-auto flex items-center gap-1">
                  <span
                    className={`w-1.5 h-1.5 rounded-full animate-pulse ${containerStatus === 'running' ? 'bg-green-500' : 'bg-yellow-500'}`}
                  />
                  <span
                    className={`text-[10px] ${containerStatus === 'running' ? 'text-green-400' : 'text-yellow-400'}`}
                  >
                    {containerStatus === 'running' ? 'live' : 'starting'}
                  </span>
                </span>
              )}
            </button>

            {isLogsOpen && (
              <div>
                {containerStatus !== 'running' &&
                containerStatus !== 'starting' &&
                containerStatus !== 'failed' ? (
                  <p className="text-xs text-[var(--text)]/40 py-4 text-center">
                    Start the container to view logs
                  </p>
                ) : (
                  <>
                    {/* Log controls */}
                    <div className="flex items-center gap-1 mb-1.5">
                      <button
                        onClick={toggleLogsPause}
                        className="p-1 rounded text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)] transition-colors"
                        title={isLogsPaused ? 'Resume' : 'Pause'}
                      >
                        {isLogsPaused ? <Play size={12} /> : <Pause size={12} />}
                      </button>
                      <button
                        onClick={() => {
                          setLogLines([]);
                          pauseBufferRef.current = [];
                        }}
                        className="p-1 rounded text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)] transition-colors"
                        title="Clear"
                      >
                        <Trash size={12} />
                      </button>
                      <button
                        onClick={() => setIsLogsAutoScroll((prev) => !prev)}
                        className={`p-1 rounded transition-colors ${
                          isLogsAutoScroll
                            ? 'text-green-400 hover:bg-green-500/10'
                            : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)]'
                        }`}
                        title={isLogsAutoScroll ? 'Auto-scroll on' : 'Auto-scroll off'}
                      >
                        <ArrowLineDown size={12} />
                      </button>
                      {isLogsPaused && (
                        <span className="text-[10px] text-yellow-400 ml-auto">paused</span>
                      )}
                    </div>

                    {/* Log output */}
                    <div
                      ref={logContainerRef}
                      className="h-48 overflow-y-auto overflow-x-auto bg-[#0a0a0a] rounded border border-[var(--border-color)] p-1.5 font-mono text-[10px] leading-relaxed text-[#d4d4d4] select-text"
                    >
                      {logLines.length === 0 ? (
                        <span className="text-[var(--text)]/30">Waiting for logs...</span>
                      ) : (
                        logLines.map((line, i) => (
                          <div key={i} className="whitespace-pre">
                            {line}
                          </div>
                        ))
                      )}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
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
    </>
  );
};
