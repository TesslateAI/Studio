import { useState, useEffect, useRef, useCallback } from 'react';
import { tasksApi, projectsApi } from '../lib/api';

export type ContainerStartupStatus = 'idle' | 'starting' | 'health_checking' | 'ready' | 'error';

export interface ContainerStartupState {
  status: ContainerStartupStatus;
  phase: string;
  progress: number;
  message: string;
  logs: string[];
  error: string | null;
  containerUrl: string | null;
}

interface UseContainerStartupOptions {
  onReady?: (url: string) => void;
  onError?: (error: string) => void;
  healthCheckInterval?: number;
  healthCheckMaxRetries?: number;
}

const PHASE_MESSAGES: Record<string, string> = {
  queued: 'Preparing environment',
  running: 'Starting container',
  creating_namespace: 'Creating project environment',
  creating_deployment: 'Deploying container',
  installing_dependencies: 'Installing dependencies',
  starting_server: 'Starting development server',
  health_checking: 'Starting development server', // Don't show "health check" to users
  completed: 'Container ready!',
  failed: 'Container startup failed',
};

export function useContainerStartup(
  projectSlug: string | undefined,
  containerId: string | null,
  options: UseContainerStartupOptions = {}
) {
  const { onReady, onError, healthCheckInterval = 2000, healthCheckMaxRetries = 60 } = options;

  const [state, setState] = useState<ContainerStartupState>({
    status: 'idle',
    phase: '',
    progress: 0,
    message: '',
    logs: [],
    error: null,
    containerUrl: null,
  });

  const taskIdRef = useRef<string | null>(null);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const healthCheckIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const healthCheckRetriesRef = useRef(0);
  const isMountedRef = useRef(true);
  // Store the active containerId to use in health checks (avoids React state timing issues)
  const activeContainerIdRef = useRef<string | null>(null);

  // Cleanup function
  const cleanup = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    if (healthCheckIntervalRef.current) {
      clearInterval(healthCheckIntervalRef.current);
      healthCheckIntervalRef.current = null;
    }
  }, []);

  // Poll task status for logs and progress
  const pollTaskStatus = useCallback(
    async (taskId: string) => {
      try {
        const task = await tasksApi.getStatus(taskId);

        if (!isMountedRef.current) return;

        // Update state with task progress
        const progress = task.progress?.percentage ?? 0;
        const phase = task.progress?.message || task.status || 'running';
        const message = PHASE_MESSAGES[phase] || PHASE_MESSAGES[task.status] || 'Processing...';
        const logs = task.logs || [];

        setState((prev) => ({
          ...prev,
          phase,
          progress,
          message,
          logs,
        }));

        // Check if task completed
        if (task.status === 'completed') {
          cleanup();

          // Get container URL from result
          const containerUrl = task.result?.url || task.result?.container_url || null;

          if (containerUrl) {
            // Start health checking
            setState((prev) => ({
              ...prev,
              status: 'health_checking',
              phase: 'health_checking',
              progress: 90,
              message: PHASE_MESSAGES['health_checking'],
              containerUrl,
            }));
            startHealthChecking(containerUrl);
          } else {
            // No URL, consider it ready (maybe container doesn't have a web server)
            setState((prev) => ({
              ...prev,
              status: 'ready',
              phase: 'completed',
              progress: 100,
              message: PHASE_MESSAGES['completed'],
            }));
          }
        } else if (task.status === 'failed' || task.status === 'cancelled') {
          cleanup();
          const errorMsg = task.error || 'Container startup failed';
          setState((prev) => ({
            ...prev,
            status: 'error',
            phase: 'failed',
            message: PHASE_MESSAGES['failed'],
            error: errorMsg,
          }));
          onError?.(errorMsg);
        }
      } catch (error) {
        console.error('[useContainerStartup] Task poll error:', error);
        // Don't fail on transient poll errors, just continue
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cleanup, onError]
  );

  // Health check the container URL
  const startHealthChecking = useCallback(
    (url: string) => {
      healthCheckRetriesRef.current = 0;

      const checkHealth = async () => {
        if (!isMountedRef.current) {
          cleanup();
          return;
        }

        healthCheckRetriesRef.current++;

        try {
          // Use the backend health check endpoint
          // Use activeContainerIdRef to avoid React state timing issues
          const effectiveContainerId = activeContainerIdRef.current || containerId;
          if (projectSlug && effectiveContainerId) {
            const healthResponse = await projectsApi.checkContainerHealth(
              projectSlug,
              effectiveContainerId
            );

            if (healthResponse.healthy) {
              cleanup();
              setState((prev) => ({
                ...prev,
                status: 'ready',
                phase: 'completed',
                progress: 100,
                message: PHASE_MESSAGES['completed'],
                logs: [...prev.logs, `Server is responding at ${url}`],
              }));
              onReady?.(url);
              return;
            }
          }
        } catch (error) {
          // Health check failed, will retry
          console.debug('[useContainerStartup] Health check failed, retrying...', error);
        }

        // Don't spam logs with health check status - just keep existing logs

        // Check if max retries reached
        if (healthCheckRetriesRef.current >= healthCheckMaxRetries) {
          cleanup();
          const errorMsg = 'Container started but server did not respond in time';
          setState((prev) => ({
            ...prev,
            status: 'error',
            phase: 'failed',
            error: errorMsg,
          }));
          onError?.(errorMsg);
          return;
        }

        // Schedule next health check
        healthCheckIntervalRef.current = setTimeout(checkHealth, healthCheckInterval);
      };

      checkHealth();
    },
    [
      projectSlug,
      containerId,
      healthCheckInterval,
      healthCheckMaxRetries,
      cleanup,
      onReady,
      onError,
    ]
  );

  // Start container and begin monitoring
  // Can accept optional containerId to override hook state (useful when called before React re-renders)
  const startContainer = useCallback(
    async (overrideContainerId?: string) => {
      const effectiveContainerId = overrideContainerId || containerId;

      if (!projectSlug || !effectiveContainerId) {
        console.warn('[useContainerStartup] Missing projectSlug or containerId');
        return;
      }

      // Store the containerId in ref for use in health checks
      activeContainerIdRef.current = effectiveContainerId;

      cleanup();
      healthCheckRetriesRef.current = 0;

      setState({
        status: 'starting',
        phase: 'queued',
        progress: 0,
        message: PHASE_MESSAGES['queued'],
        logs: ['Starting container...'],
        error: null,
        containerUrl: null,
      });

      try {
        // Call start container API - this returns task_id immediately
        const response = await fetch(
          `/api/projects/${projectSlug}/containers/${effectiveContainerId}/start`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${localStorage.getItem('token')}`,
            },
            credentials: 'include',
          }
        );

        if (!response.ok) {
          throw new Error(`Failed to start container: ${response.statusText}`);
        }

        const data = await response.json();

        // FAST PATH: Container is already running (Docker mode returns task_id: null)
        if (data.already_running && data.url) {
          setState((prev) => ({
            ...prev,
            status: 'health_checking',
            phase: 'health_checking',
            progress: 90,
            message: PHASE_MESSAGES['health_checking'],
            containerUrl: data.url,
            logs: [...prev.logs, 'Container already running, verifying...'],
          }));
          startHealthChecking(data.url);
          return;
        }

        const taskId = data.task_id;
        taskIdRef.current = taskId;

        if (!taskId) {
          // No task and not already_running -- unexpected, treat as error
          throw new Error('No task_id returned from start endpoint');
        }

        // Start polling task status
        pollIntervalRef.current = setInterval(() => {
          pollTaskStatus(taskId);
        }, 1000);

        // Initial poll
        pollTaskStatus(taskId);
      } catch (error) {
        const errorMsg = error instanceof Error ? error.message : 'Failed to start container';
        setState((prev) => ({
          ...prev,
          status: 'error',
          phase: 'failed',
          error: errorMsg,
        }));
        onError?.(errorMsg);
      }
    },
    [projectSlug, containerId, cleanup, pollTaskStatus, onError, startHealthChecking]
  );

  // Retry function
  const retry = useCallback(() => {
    startContainer();
  }, [startContainer]);

  // Reset to idle
  const reset = useCallback(() => {
    cleanup();
    setState({
      status: 'idle',
      phase: '',
      progress: 0,
      message: '',
      logs: [],
      error: null,
      containerUrl: null,
    });
  }, [cleanup]);

  // Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      cleanup();
    };
  }, [cleanup]);

  return {
    ...state,
    startContainer,
    retry,
    reset,
    isLoading: state.status === 'starting' || state.status === 'health_checking',
  };
}
