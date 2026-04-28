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
  Pause,
  ArrowLineDown,
} from '@phosphor-icons/react';
import api, { createLogStreamWebSocket } from '../lib/api';
import { toast } from 'react-hot-toast';
import { connectionEvents } from '../utils/connectionEvents';
import { inspectorFocusEvents } from '../utils/inspectorFocusEvents';
import { AnsiLine } from '../lib/ansi';
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
  /** When provided, renders a "Configure" button that opens the node-config tab. */
  onConfigure?: () => void;
}

// ---------------------------------------------------------------------------
// App Contract annotations
// ---------------------------------------------------------------------------
//
// Phase 5: the Canvas inspector lets a creator annotate a container with the
// pieces the Publish Drawer eventually emits into ``opensail.app.yaml``. We
// keep these annotations as local React state today; persistence lives on a
// future ``POST /api/projects/{slug}/canvas-annotations`` endpoint that the
// Publish Drawer will consume when emitting the manifest.
//
// Why local state instead of round-tripping yaml here?
// * Round-tripping yaml from the canvas would require us to load + parse the
//   full ``opensail.app.yaml`` (which the publisher already does server-side).
// * The Publish Drawer is the single writer of the manifest; the canvas is
//   the source of intent. Persisting these as a small JSON blob keyed by
//   container id keeps the canvas non-blocking on a yaml refactor.
// * The publisher (`publish_inferrer.py`) already infers exposed actions
//   from project structure — these annotations are the explicit overrides /
//   additions the creator makes from the canvas.
// ---------------------------------------------------------------------------

type AppSurfaceKind = 'ui' | 'chat' | 'full_page' | 'card' | 'drawer' | 'mcp_tool';
type ConnectorKind = 'oauth' | 'api_key' | 'basic_auth' | 'webhook';
type ConnectorExposure = 'proxy' | 'env';
type ActionPayer = 'installer' | 'creator';

interface AppSurfaceAnnotation {
  enabled: boolean;
  kind: AppSurfaceKind;
  entrypoint: string;
}

interface AppActionAnnotation {
  name: string;
  handler_path: string;
  input_schema: string;
  output_schema: string;
  payer_default: ActionPayer;
}

interface DataResourceAnnotation {
  name: string;
  backed_by_action: string;
}

interface ConnectorAnnotation {
  id: string;
  kind: ConnectorKind;
  scopes: string[];
  exposure: ConnectorExposure;
}

interface ContainerCanvasAnnotations {
  surface: AppSurfaceAnnotation;
  actions: AppActionAnnotation[];
  data_resources: DataResourceAnnotation[];
  connectors: ConnectorAnnotation[];
}

const EMPTY_ANNOTATIONS: ContainerCanvasAnnotations = {
  surface: { enabled: false, kind: 'ui', entrypoint: '' },
  actions: [],
  data_resources: [],
  connectors: [],
};

/** Storage key prefix — annotations are scoped per project + container. */
function annotationsStorageKey(projectSlug: string, containerId: string): string {
  return `canvas-annotations:${projectSlug}:${containerId}`;
}

const PANEL_MIN_WIDTH = 280;
const PANEL_MAX_WIDTH = 640;
const PANEL_STORAGE_KEY = 'containerPanelWidth';

function getStoredWidth(): number {
  try {
    const v = localStorage.getItem(PANEL_STORAGE_KEY);
    if (v) {
      const n = Number(v);
      if (n >= PANEL_MIN_WIDTH && n <= PANEL_MAX_WIDTH) return n;
    }
  } catch {
    /* ignore */
  }
  return 320;
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
  onConfigure,
}: ContainerPropertiesPanelProps) => {
  const [panelWidth, setPanelWidth] = useState(getStoredWidth);
  const isResizingRef = useRef(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!isResizingRef.current) return;
      // Dragging left edge: moving mouse left = wider panel
      const delta = startXRef.current - e.clientX;
      const newWidth = Math.min(
        PANEL_MAX_WIDTH,
        Math.max(PANEL_MIN_WIDTH, startWidthRef.current + delta)
      );
      setPanelWidth(newWidth);
    };
    const onMouseUp = () => {
      if (!isResizingRef.current) return;
      isResizingRef.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      // persist
      setPanelWidth((w) => {
        try {
          localStorage.setItem(PANEL_STORAGE_KEY, String(w));
        } catch {
          /* ignore */
        }
        return w;
      });
    };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, []);

  const onResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      isResizingRef.current = true;
      startXRef.current = e.clientX;
      startWidthRef.current = panelWidth;
      document.body.style.cursor = 'ew-resize';
      document.body.style.userSelect = 'none';
    },
    [panelWidth]
  );

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

  // --- Collapsible sections ---
  const [isEnvExpanded, setIsEnvExpanded] = useState(false);
  const [isAddingInline, setIsAddingInline] = useState(false);

  // --- App Contract annotations (Phase 5 canvas annotations) ---
  const [isAppContractExpanded, setIsAppContractExpanded] = useState(false);
  const [annotations, setAnnotations] = useState<ContainerCanvasAnnotations>(() => {
    try {
      const raw = localStorage.getItem(annotationsStorageKey(projectSlug, containerId));
      if (raw) return { ...EMPTY_ANNOTATIONS, ...(JSON.parse(raw) as Partial<ContainerCanvasAnnotations>) };
    } catch {
      /* ignore */
    }
    return EMPTY_ANNOTATIONS;
  });
  const [annotationsDirty, setAnnotationsDirty] = useState(false);

  // Hydrate when the panel switches to a different container.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(annotationsStorageKey(projectSlug, containerId));
      if (raw) {
        setAnnotations({
          ...EMPTY_ANNOTATIONS,
          ...(JSON.parse(raw) as Partial<ContainerCanvasAnnotations>),
        });
      } else {
        setAnnotations(EMPTY_ANNOTATIONS);
      }
      setAnnotationsDirty(false);
    } catch {
      setAnnotations(EMPTY_ANNOTATIONS);
      setAnnotationsDirty(false);
    }
  }, [projectSlug, containerId]);

  const updateAnnotations = useCallback(
    (patch: Partial<ContainerCanvasAnnotations>) => {
      setAnnotations((prev) => ({ ...prev, ...patch }));
      setAnnotationsDirty(true);
    },
    []
  );

  // Phase 5 inspector-jump listener.
  //
  // PublishAsAppDrawer's "Fix in inspector" handler emits an
  // ``inspector-focus-request`` after the canvas selects this container.
  // We expand the App Contract section, then scroll the matching action
  // or connector row into view via ``scrollIntoView({ block: 'center' })``.
  // Up to 4 rAF retries give the section's render pass time to mount the
  // child rows before we look them up.
  const panelRootRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const off = inspectorFocusEvents.on('inspector-focus-request', (req) => {
      if (req.containerId !== containerId) return;
      setIsAppContractExpanded(true);
      const tryFocus = (attempt: number) => {
        const root = panelRootRef.current;
        if (!root) {
          if (attempt < 4) requestAnimationFrame(() => tryFocus(attempt + 1));
          return;
        }
        const selector =
          req.kind === 'action'
            ? req.name
              ? `[data-action-name="${CSS.escape(req.name)}"]`
              : '[data-action-name]'
            : req.name
              ? `[data-connector-id="${CSS.escape(req.name)}"]`
              : '[data-connector-id]';
        const el = root.querySelector<HTMLElement>(selector);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          // Highlight pulse — additive Tailwind ring; auto-removed after 1.5s.
          el.classList.add('ring-2', 'ring-[var(--primary)]', 'ring-offset-2');
          window.setTimeout(() => {
            el.classList.remove(
              'ring-2',
              'ring-[var(--primary)]',
              'ring-offset-2'
            );
          }, 1500);
        } else if (attempt < 4) {
          requestAnimationFrame(() => tryFocus(attempt + 1));
        }
      };
      requestAnimationFrame(() => tryFocus(0));
    });
    return off;
  }, [containerId]);

  const saveAnnotations = useCallback(() => {
    try {
      localStorage.setItem(
        annotationsStorageKey(projectSlug, containerId),
        JSON.stringify(annotations)
      );
      // TODO: POST /api/projects/{slug}/canvas-annotations once the
      // backend stub lands (Phase 5 follow-up). The Publish Drawer will
      // read these when emitting opensail.app.yaml.
      setAnnotationsDirty(false);
      toast.success('Annotations saved locally');
    } catch (err) {
      console.error('Failed to persist annotations:', err);
      toast.error('Failed to save annotations');
    }
  }, [projectSlug, containerId, annotations]);

  // --- Container Logs ---
  const [isLogsOpen, setIsLogsOpen] = useState(true);
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
      toast.success(`Added ${key} — restart container to apply`);
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
      toast.success(`Deleted ${key} — restart container to apply`);
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
      toast.success(`Updated ${key} — restart container to apply`);
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

      {/* Panel — no outer container, cards float directly */}
      <div
        ref={panelRootRef}
        className="fixed md:absolute inset-y-4 md:inset-y-auto md:top-4 md:bottom-4 right-4 w-[calc(100%-2rem)] max-w-sm md:w-[var(--panel-w)] md:max-w-none flex flex-col overflow-hidden z-50"
        style={{ '--panel-w': `${panelWidth}px` } as React.CSSProperties}
      >
        {/* Left resize handle */}
        <div
          onMouseDown={onResizeStart}
          className="hidden md:block absolute left-0 top-0 bottom-0 w-1.5 cursor-ew-resize z-10 hover:bg-[var(--border-hover)] active:bg-[var(--border)] transition-colors"
        />

        {/* Scrollable card stack */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden p-1 space-y-2">
          {/* Identity card — name + status + close */}
          <div className="bg-[var(--surface-hover)] rounded-[var(--radius)] border border-[var(--border)] overflow-hidden">
            <div className="flex items-center justify-between h-10 px-4 border-b border-[var(--border)]">
              {isEditingName ? (
                <div className="flex items-center gap-2 flex-1 min-w-0">
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
                    className="flex-1 px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-semibold focus:outline-none focus:border-[var(--border-hover)]"
                    autoFocus
                    disabled={isRenamingContainer}
                  />
                  <button
                    onClick={handleRenameContainer}
                    disabled={isRenamingContainer}
                    className="btn btn-icon btn-sm"
                    title="Save name"
                  >
                    <Check size={14} className="text-[var(--status-success)]" />
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  <span
                    className={`w-2 h-2 rounded-full flex-shrink-0 ${
                      containerStatus === 'running'
                        ? 'bg-[var(--status-success)]'
                        : containerStatus === 'starting'
                          ? 'bg-[var(--status-warning)]'
                          : containerStatus === 'failed'
                            ? 'bg-[var(--status-error)]'
                            : containerStatus === 'connected'
                              ? 'bg-purple-400'
                              : 'bg-[var(--text-subtle)]'
                    }`}
                  />
                  <span className="text-xs font-semibold text-[var(--text)] truncate">
                    {containerName}
                  </span>
                  <button
                    onClick={() => setIsEditingName(true)}
                    className="btn btn-icon btn-sm"
                    title="Rename container"
                  >
                    <PencilSimple size={12} />
                  </button>
                </div>
              )}
              <div className="flex items-center gap-1.5 flex-shrink-0 ml-2">
                {port && (
                  <span className="text-[10px] text-[var(--text-subtle)] font-mono">:{port}</span>
                )}
                {onConfigure && (
                  <button
                    onClick={onConfigure}
                    className="btn btn-icon btn-sm"
                    title="Configure container (opens config tab)"
                    aria-label="Configure container"
                  >
                    <Key size={13} />
                  </button>
                )}
                <button onClick={onClose} className="btn btn-icon btn-sm">
                  <X size={14} />
                </button>
              </div>
            </div>

            {/* Container Controls */}
            <div className="px-4 py-3">
              <div className="flex gap-1.5">
                <button
                  onClick={() => handleContainerAction('start')}
                  disabled={
                    isLoading || containerStatus === 'running' || containerStatus === 'starting'
                  }
                  className="btn flex-1"
                  style={
                    containerStatus !== 'running' && containerStatus !== 'starting' && !isLoading
                      ? {
                          background: 'rgba(var(--status-green-rgb), 0.1)',
                          borderColor: 'rgba(var(--status-green-rgb), 0.3)',
                          color: 'var(--status-success)',
                        }
                      : undefined
                  }
                >
                  <Play size={12} weight="fill" />
                  {containerStatus === 'starting' ? 'Starting...' : 'Start'}
                </button>
                <button
                  onClick={() => handleContainerAction('stop')}
                  disabled={
                    isLoading || containerStatus === 'stopped' || containerStatus === 'connected'
                  }
                  className="btn btn-danger flex-1"
                >
                  <Square size={12} weight="fill" />
                  Stop
                </button>
                <button
                  onClick={() => handleContainerAction('restart')}
                  disabled={
                    isLoading || containerStatus === 'starting' || containerStatus === 'connected'
                  }
                  className="btn flex-1"
                >
                  <ArrowClockwise size={12} />
                  Restart
                </button>
              </div>
            </div>
          </div>

          {/* Edit Credentials card (external services only) */}
          {isExternalService && (
            <div className="bg-[var(--surface-hover)] rounded-[var(--radius)] border border-[var(--border)] overflow-hidden">
              <div className="px-4 py-3">
                <button onClick={handleEditCredentials} className="btn w-full">
                  <Key size={14} />
                  Edit Credentials
                </button>
              </div>
            </div>
          )}

          {/* Environment Variables card */}
          <div className="bg-[var(--surface-hover)] rounded-[var(--radius)] border border-[var(--border)] overflow-hidden">
            <div className="flex items-center">
              <button
                type="button"
                onClick={() => setIsEnvExpanded((v) => !v)}
                className="flex-1 flex items-center gap-2 px-4 py-2.5 hover:bg-[var(--surface-hover)] transition-colors group"
              >
                <span className="text-[11px] font-medium text-[var(--text-muted)] group-hover:text-[var(--text)]">
                  Environment Variables
                </span>
                {savedEnvVars.length > 0 && (
                  <span className="text-[10px] text-[var(--text-subtle)]">
                    {savedEnvVars.length}
                  </span>
                )}
                <span
                  className={`transition-transform duration-200 text-[var(--text-subtle)] ${isEnvExpanded ? 'rotate-0' : '-rotate-90'}`}
                >
                  <CaretDown size={10} />
                </span>
              </button>
              <div className="pr-3 flex-shrink-0">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setIsEnvExpanded(true);
                    setIsAddingInline(true);
                  }}
                  className="btn btn-icon btn-sm"
                  title="Add variable"
                >
                  <Plus size={12} />
                </button>
              </div>
            </div>
            {isEnvExpanded && (
              <div className="px-4 pb-4 space-y-2">
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
                        <div className="border-b border-[var(--border)] mt-2" />
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
                                      ev.key === envVar.key
                                        ? { ...ev, pendingValue: e.target.value }
                                        : ev
                                    )
                                  )
                                }
                                placeholder="new value"
                                className="w-24 px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
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
                              <span className="text-xs text-[var(--text)]/40 font-mono">
                                ••••••••
                              </span>
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

                    {/* Add new environment variable — toggled by + button */}
                    {isAddingInline && (
                      <div className="pt-2 border-t border-[var(--border)]">
                        <div className="space-y-1.5">
                          <input
                            type="text"
                            value={newEnvKey}
                            onChange={(e) =>
                              setNewEnvKey(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_'))
                            }
                            placeholder="KEY_NAME"
                            className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
                            autoFocus
                            onKeyDown={(e) => {
                              if (e.key === 'Escape') {
                                setIsAddingInline(false);
                                setNewEnvKey('');
                                setNewEnvValue('');
                              }
                            }}
                          />
                          <input
                            type="text"
                            value={newEnvValue}
                            onChange={(e) => setNewEnvValue(e.target.value)}
                            placeholder="value"
                            className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') handleAddEnvVar();
                              if (e.key === 'Escape') {
                                setIsAddingInline(false);
                                setNewEnvKey('');
                                setNewEnvValue('');
                              }
                            }}
                          />
                          <div className="flex gap-1.5">
                            <button
                              onClick={handleAddEnvVar}
                              disabled={isAdding}
                              className="btn btn-sm flex-1"
                            >
                              <Plus size={12} />
                              {isAdding ? 'Adding...' : 'Add'}
                            </button>
                            <button
                              onClick={() => {
                                setIsAddingInline(false);
                                setNewEnvKey('');
                                setNewEnvValue('');
                              }}
                              className="btn btn-sm"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* App Contract annotations card (Phase 5 canvas annotations).
              Persists to localStorage today; the Publish Drawer reads these
              when emitting opensail.app.yaml. See annotation-system docstring
              at the top of this file. */}
          <div className="bg-[var(--surface-hover)] rounded-[var(--radius)] border border-[var(--border)] overflow-hidden">
            <button
              type="button"
              onClick={() => setIsAppContractExpanded((v) => !v)}
              className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-[var(--surface-hover)] transition-colors group"
              data-testid="app-contract-toggle"
            >
              <span className="text-[11px] font-medium text-[var(--text-muted)] group-hover:text-[var(--text)]">
                App Contract
              </span>
              {annotationsDirty && (
                <span className="text-[10px] text-[var(--status-warning)]">
                  unsaved
                </span>
              )}
              <span
                className={`ml-auto transition-transform duration-200 text-[var(--text-subtle)] ${isAppContractExpanded ? 'rotate-0' : '-rotate-90'}`}
              >
                <CaretDown size={10} />
              </span>
            </button>
            {isAppContractExpanded && (
              <div className="px-4 pb-4 space-y-4">
                {/* Surface */}
                <div className="space-y-2">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={annotations.surface.enabled}
                      onChange={(e) =>
                        updateAnnotations({
                          surface: { ...annotations.surface, enabled: e.target.checked },
                        })
                      }
                      data-testid="surface-enabled"
                    />
                    <span className="text-xs font-medium text-[var(--text)]">
                      Expose as app surface
                    </span>
                  </label>
                  {annotations.surface.enabled && (
                    <div className="space-y-1.5 pl-5">
                      <div>
                        <label className="block text-[10px] uppercase tracking-wider text-[var(--text-subtle)] mb-1">
                          Kind
                        </label>
                        <select
                          value={annotations.surface.kind}
                          onChange={(e) =>
                            updateAnnotations({
                              surface: {
                                ...annotations.surface,
                                kind: e.target.value as AppSurfaceKind,
                              },
                            })
                          }
                          data-testid="surface-kind"
                          className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
                        >
                          <option value="ui">ui</option>
                          <option value="chat">chat</option>
                          <option value="full_page">full_page</option>
                          <option value="card">card</option>
                          <option value="drawer">drawer</option>
                          <option value="mcp_tool">mcp_tool</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-[10px] uppercase tracking-wider text-[var(--text-subtle)] mb-1">
                          Entrypoint
                        </label>
                        <input
                          type="text"
                          value={annotations.surface.entrypoint}
                          onChange={(e) =>
                            updateAnnotations({
                              surface: {
                                ...annotations.surface,
                                entrypoint: e.target.value,
                              },
                            })
                          }
                          placeholder="/index.html"
                          className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
                        />
                      </div>
                    </div>
                  )}
                </div>

                {/* Actions */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-[var(--text)]">
                      Expose as app actions
                    </span>
                    <button
                      onClick={() =>
                        updateAnnotations({
                          actions: [
                            ...annotations.actions,
                            {
                              name: '',
                              handler_path: '',
                              input_schema: '{}',
                              output_schema: '{}',
                              payer_default: 'installer',
                            },
                          ],
                        })
                      }
                      className="btn btn-icon btn-sm"
                      title="Add action"
                      data-testid="add-action"
                    >
                      <Plus size={12} />
                    </button>
                  </div>
                  {annotations.actions.map((action, idx) => (
                    <div
                      key={idx}
                      // Phase 5 inspector-jump scroll target. The panel
                      // listens for ``inspector-focus-request`` events and
                      // resolves the matching row by ``data-action-name``.
                      data-action-name={action.name || `__unnamed_${idx}`}
                      className="space-y-1.5 pl-3 border-l-2 border-[var(--border)]"
                    >
                      <input
                        type="text"
                        value={action.name}
                        onChange={(e) => {
                          const next = [...annotations.actions];
                          next[idx] = { ...action, name: e.target.value };
                          updateAnnotations({ actions: next });
                        }}
                        placeholder="action_name"
                        className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
                      />
                      <input
                        type="text"
                        value={action.handler_path}
                        onChange={(e) => {
                          const next = [...annotations.actions];
                          next[idx] = { ...action, handler_path: e.target.value };
                          updateAnnotations({ actions: next });
                        }}
                        placeholder="handler.path (e.g. POST /api/foo)"
                        className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
                      />
                      <textarea
                        value={action.input_schema}
                        onChange={(e) => {
                          const next = [...annotations.actions];
                          next[idx] = { ...action, input_schema: e.target.value };
                          updateAnnotations({ actions: next });
                        }}
                        placeholder='{"type":"object"}'
                        rows={3}
                        className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-[10px] font-mono focus:outline-none focus:border-[var(--border-hover)]"
                      />
                      <textarea
                        value={action.output_schema}
                        onChange={(e) => {
                          const next = [...annotations.actions];
                          next[idx] = { ...action, output_schema: e.target.value };
                          updateAnnotations({ actions: next });
                        }}
                        placeholder='{"type":"object"}'
                        rows={3}
                        className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-[10px] font-mono focus:outline-none focus:border-[var(--border-hover)]"
                      />
                      <div className="flex items-center gap-2">
                        <select
                          value={action.payer_default}
                          onChange={(e) => {
                            const next = [...annotations.actions];
                            next[idx] = {
                              ...action,
                              payer_default: e.target.value as ActionPayer,
                            };
                            updateAnnotations({ actions: next });
                          }}
                          className="flex-1 px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
                        >
                          <option value="installer">payer: installer</option>
                          <option value="creator">payer: creator</option>
                        </select>
                        <button
                          onClick={() => {
                            const next = annotations.actions.filter(
                              (_, i) => i !== idx
                            );
                            updateAnnotations({ actions: next });
                          }}
                          className="btn btn-icon btn-sm"
                          title="Remove"
                        >
                          <Trash size={12} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Data resources */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-[var(--text)]">
                      Expose as data resources
                    </span>
                    <button
                      onClick={() =>
                        updateAnnotations({
                          data_resources: [
                            ...annotations.data_resources,
                            { name: '', backed_by_action: '' },
                          ],
                        })
                      }
                      className="btn btn-icon btn-sm"
                      title="Add data resource"
                    >
                      <Plus size={12} />
                    </button>
                  </div>
                  {annotations.data_resources.map((dr, idx) => (
                    <div
                      key={idx}
                      className="flex items-center gap-1.5 pl-3 border-l-2 border-[var(--border)]"
                    >
                      <input
                        type="text"
                        value={dr.name}
                        onChange={(e) => {
                          const next = [...annotations.data_resources];
                          next[idx] = { ...dr, name: e.target.value };
                          updateAnnotations({ data_resources: next });
                        }}
                        placeholder="resource_name"
                        className="flex-1 px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
                      />
                      <select
                        value={dr.backed_by_action}
                        onChange={(e) => {
                          const next = [...annotations.data_resources];
                          next[idx] = { ...dr, backed_by_action: e.target.value };
                          updateAnnotations({ data_resources: next });
                        }}
                        className="flex-1 px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
                      >
                        <option value="">— action —</option>
                        {annotations.actions
                          .filter((a) => a.name)
                          .map((a) => (
                            <option key={a.name} value={a.name}>
                              {a.name}
                            </option>
                          ))}
                      </select>
                      <button
                        onClick={() => {
                          const next = annotations.data_resources.filter(
                            (_, i) => i !== idx
                          );
                          updateAnnotations({ data_resources: next });
                        }}
                        className="btn btn-icon btn-sm"
                        title="Remove"
                      >
                        <Trash size={12} />
                      </button>
                    </div>
                  ))}
                </div>

                {/* Connectors */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-[var(--text)]">
                      Require connectors
                    </span>
                    <button
                      onClick={() =>
                        updateAnnotations({
                          connectors: [
                            ...annotations.connectors,
                            {
                              id: '',
                              kind: 'oauth',
                              scopes: [],
                              exposure: 'proxy',
                            },
                          ],
                        })
                      }
                      className="btn btn-icon btn-sm"
                      title="Add connector"
                    >
                      <Plus size={12} />
                    </button>
                  </div>
                  {annotations.connectors.map((conn, idx) => {
                    const oauthEnvBlocked =
                      conn.kind === 'oauth' && conn.exposure === 'env';
                    const envWarn = conn.exposure === 'env' && conn.kind !== 'oauth';
                    return (
                      <div
                        key={idx}
                        // Phase 5 inspector-jump scroll target. Same data
                        // attribute pattern as the action row above.
                        data-connector-id={conn.id || `__unnamed_${idx}`}
                        className="space-y-1.5 pl-3 border-l-2 border-[var(--border)]"
                      >
                        <input
                          type="text"
                          value={conn.id}
                          onChange={(e) => {
                            const next = [...annotations.connectors];
                            next[idx] = { ...conn, id: e.target.value };
                            updateAnnotations({ connectors: next });
                          }}
                          placeholder="connector_id"
                          className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--border-hover)]"
                        />
                        <div className="flex items-center gap-1.5">
                          <select
                            value={conn.kind}
                            onChange={(e) => {
                              const next = [...annotations.connectors];
                              next[idx] = {
                                ...conn,
                                kind: e.target.value as ConnectorKind,
                              };
                              updateAnnotations({ connectors: next });
                            }}
                            className="flex-1 px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
                          >
                            <option value="oauth">oauth</option>
                            <option value="api_key">api_key</option>
                            <option value="basic_auth">basic_auth</option>
                            <option value="webhook">webhook</option>
                          </select>
                          <select
                            value={conn.exposure}
                            onChange={(e) => {
                              const next = [...annotations.connectors];
                              next[idx] = {
                                ...conn,
                                exposure: e.target.value as ConnectorExposure,
                              };
                              updateAnnotations({ connectors: next });
                            }}
                            data-testid={`connector-exposure-${idx}`}
                            className="flex-1 px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
                          >
                            <option value="proxy">proxy</option>
                            <option value="env">env</option>
                          </select>
                          <button
                            onClick={() => {
                              const next = annotations.connectors.filter(
                                (_, i) => i !== idx
                              );
                              updateAnnotations({ connectors: next });
                            }}
                            className="btn btn-icon btn-sm"
                            title="Remove"
                          >
                            <Trash size={12} />
                          </button>
                        </div>
                        <input
                          type="text"
                          value={conn.scopes.join(', ')}
                          onChange={(e) => {
                            const next = [...annotations.connectors];
                            next[idx] = {
                              ...conn,
                              scopes: e.target.value
                                .split(',')
                                .map((s) => s.trim())
                                .filter(Boolean),
                            };
                            updateAnnotations({ connectors: next });
                          }}
                          placeholder="scope1, scope2"
                          className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-[10px] font-mono focus:outline-none focus:border-[var(--border-hover)]"
                        />
                        {oauthEnvBlocked && (
                          <p
                            data-testid={`connector-error-${idx}`}
                            className="text-[10px] text-red-400"
                          >
                            OAuth + env is rejected at install. Use proxy
                            exposure for OAuth connectors.
                          </p>
                        )}
                        {envWarn && (
                          <p
                            data-testid={`connector-warn-${idx}`}
                            className="text-[10px] text-amber-400"
                          >
                            the app process will see this secret directly.
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Save */}
                {annotationsDirty && (
                  <div className="pt-2 border-t border-[var(--border)]">
                    <button
                      onClick={saveAnnotations}
                      className="btn btn-sm w-full"
                      data-testid="save-annotations"
                    >
                      <Check size={12} />
                      Save annotations
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Container Logs card */}
          <div className="bg-[var(--surface-hover)] rounded-[var(--radius)] border border-[var(--border)] overflow-hidden">
            <button
              type="button"
              onClick={() => setIsLogsOpen((prev) => !prev)}
              className="flex items-center gap-2 px-4 py-2.5 hover:bg-[var(--surface-hover)] transition-colors group w-full"
            >
              <span className="text-[11px] font-medium text-[var(--text-muted)] group-hover:text-[var(--text)]">
                Container Logs
              </span>
              {isLogsOpen && (containerStatus === 'running' || containerStatus === 'starting') && (
                <span className="flex items-center gap-1">
                  <span
                    className={`w-1.5 h-1.5 rounded-full animate-pulse ${containerStatus === 'running' ? 'bg-[var(--status-success)]' : 'bg-[var(--status-warning)]'}`}
                  />
                  <span className="text-[10px] text-[var(--text-subtle)]">
                    {containerStatus === 'running' ? 'live' : 'starting'}
                  </span>
                </span>
              )}
              <span
                className={`transition-transform duration-200 text-[var(--text-subtle)] ${isLogsOpen ? 'rotate-0' : '-rotate-90'}`}
              >
                <CaretDown size={10} />
              </span>
            </button>

            {isLogsOpen && (
              <div className="px-4 pb-4">
                {containerStatus !== 'running' &&
                containerStatus !== 'starting' &&
                containerStatus !== 'failed' ? (
                  <p className="text-xs text-[var(--text-subtle)] py-4 text-center">
                    Start the container to view logs
                  </p>
                ) : (
                  <>
                    {/* Log controls */}
                    <div className="flex items-center gap-1 mb-1.5">
                      <button
                        onClick={toggleLogsPause}
                        className="btn btn-icon btn-sm"
                        title={isLogsPaused ? 'Resume' : 'Pause'}
                      >
                        {isLogsPaused ? <Play size={12} /> : <Pause size={12} />}
                      </button>
                      <button
                        onClick={() => {
                          setLogLines([]);
                          pauseBufferRef.current = [];
                        }}
                        className="btn btn-icon btn-sm"
                        title="Clear"
                      >
                        <Trash size={12} />
                      </button>
                      <button
                        onClick={() => setIsLogsAutoScroll((prev) => !prev)}
                        className={`btn btn-icon btn-sm ${isLogsAutoScroll ? 'btn-active' : ''}`}
                        title={isLogsAutoScroll ? 'Auto-scroll on' : 'Auto-scroll off'}
                      >
                        <ArrowLineDown size={12} />
                      </button>
                      {isLogsPaused && (
                        <span className="text-[10px] text-[var(--status-warning)] ml-auto">
                          paused
                        </span>
                      )}
                    </div>

                    {/* Log output */}
                    <div
                      ref={logContainerRef}
                      className="h-48 overflow-y-auto overflow-x-auto bg-[var(--bg)] rounded-[var(--radius-small)] border border-[var(--border)] p-1.5 font-mono text-[10px] leading-relaxed text-[#d4d4d4] select-text"
                    >
                      {logLines.length === 0 ? (
                        <span className="text-[var(--text-subtle)]">Waiting for logs...</span>
                      ) : (
                        logLines.map((line, i) => (
                          <div key={i} className="whitespace-pre">
                            <AnsiLine text={line} />
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
