import { useState, useRef, useEffect, useCallback } from 'react';
import { projectsApi } from '../lib/api';
import { fileEvents } from '../utils/fileEvents';

export interface FileTreeEntry {
  path: string;
  name: string;
  is_dir: boolean;
  size: number;
  mod_time: number;
}

interface UseFileTreeOptions {
  slug: string;
  containerDir?: string;
  enabled?: boolean;
}

interface UseFileTreeReturn {
  fileTree: FileTreeEntry[];
  isLoaded: boolean;
  refresh: () => Promise<void>;
  refreshWithRetry: () => void;
  cancelRetry: () => void;
}

const FILE_RETRY_MAX = 8;

export function useFileTree({
  slug,
  containerDir,
  enabled = true,
}: UseFileTreeOptions): UseFileTreeReturn {
  const [fileTree, setFileTree] = useState<FileTreeEntry[]>([]);
  const [isLoaded, setIsLoaded] = useState(false);

  const retryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryCountRef = useRef(0);
  const cancelledRef = useRef(false);

  const loadFileTree = useCallback(async () => {
    if (!slug) return;
    try {
      const entries = await projectsApi.getFileTree(slug, containerDir);
      setFileTree((prev) => {
        const prevPaths = prev.map((f) => f.path).join('\0');
        const newPaths = entries.map((f) => f.path).join('\0');
        if (prevPaths === newPaths) return prev;
        return entries;
      });
    } catch (error) {
      console.error('Failed to load file tree:', error);
    }
  }, [slug, containerDir]);

  const loadFileTreeRef = useRef(loadFileTree);
  loadFileTreeRef.current = loadFileTree;

  const cancelRetry = useCallback(() => {
    cancelledRef.current = true;
    if (retryTimeoutRef.current) {
      clearTimeout(retryTimeoutRef.current);
      retryTimeoutRef.current = null;
    }
    retryCountRef.current = 0;
  }, []);

  const refreshWithRetry = useCallback(() => {
    if (!slug) return;

    cancelledRef.current = false;

    const attempt = async () => {
      try {
        const entries = await projectsApi.getFileTree(slug, containerDir);

        if (cancelledRef.current) return;

        if (entries.length > 0) {
          setFileTree(entries);
          setIsLoaded(true);
          retryCountRef.current = 0;
          return;
        }

        if (retryCountRef.current < FILE_RETRY_MAX) {
          const delay = Math.min((retryCountRef.current + 1) * 1000, 5000);
          retryCountRef.current += 1;
          retryTimeoutRef.current = setTimeout(attempt, delay);
        } else {
          setFileTree([]);
          setIsLoaded(true);
          retryCountRef.current = 0;
        }
      } catch (error) {
        if (cancelledRef.current) return;
        console.error('Failed to load file tree (retry):', error);

        if (retryCountRef.current < FILE_RETRY_MAX) {
          const delay = Math.min((retryCountRef.current + 1) * 1000, 5000);
          retryCountRef.current += 1;
          retryTimeoutRef.current = setTimeout(attempt, delay);
        } else {
          setIsLoaded(true);
          retryCountRef.current = 0;
        }
      }
    };

    attempt();
  }, [slug, containerDir]);

  // File events listener — refresh on all events except 'file-updated' to avoid
  // recursion when saving a file triggers an event that reloads the tree.
  useEffect(() => {
    if (!enabled) return;

    const unsubscribe = fileEvents.on((detail) => {
      if (detail.type !== 'file-updated') {
        loadFileTreeRef.current();
      }
    });

    return unsubscribe;
  }, [slug, enabled]);

  // Smart polling: 60s interval, pauses when tab is hidden.
  useEffect(() => {
    if (!slug || !enabled) return;

    let pollInterval: ReturnType<typeof setInterval> | null = null;
    let isTabVisible = !document.hidden;

    const startPolling = () => {
      pollInterval = setInterval(() => {
        if (isTabVisible && slug) {
          loadFileTreeRef.current();
        }
      }, 60_000);
    };

    const handleVisibilityChange = () => {
      isTabVisible = !document.hidden;

      if (isTabVisible && !pollInterval) {
        startPolling();
      } else if (!isTabVisible && pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    if (isTabVisible) {
      startPolling();
    }

    return () => {
      if (pollInterval) {
        clearInterval(pollInterval);
      }
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [slug, containerDir, enabled]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
      }
      cancelledRef.current = true;
    };
  }, []);

  return {
    fileTree,
    isLoaded,
    refresh: loadFileTree,
    refreshWithRetry,
    cancelRetry,
  };
}
