import { useState, useEffect, useCallback, useRef } from 'react';
import { chatApi } from '../lib/api';

export interface ChatSession {
  id: string;
  title: string;
  status: string;
  origin: string | null;
  project_id: string | null;
  project_name: string | null;
  created_at: string | null;
  updated_at: string | null;
}

interface UseChatSessionsOptions {
  /** When true, only fetch standalone (project-less) sessions */
  standalone?: boolean;
}

export function useChatSessions({ standalone = true }: UseChatSessionsOptions = {}) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const mountedRef = useRef(true);
  const currentSessionIdRef = useRef<string | null>(null);

  useEffect(() => {
    currentSessionIdRef.current = currentSessionId;
  }, [currentSessionId]);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchSessions = useCallback(async () => {
    try {
      if (!standalone) return;
      const data = await chatApi.getUserSessions({ limit: 30, offset: 0 });
      if (!mountedRef.current) return;
      setSessions(data.sessions || []);
      return data.sessions || [];
    } catch (err) {
      console.error('[SESSIONS] Failed to fetch sessions:', err);
      return [];
    }
  }, [standalone]);

  // Initial load
  useEffect(() => {
    setIsLoading(true);
    fetchSessions().then((sessions) => {
      if (!mountedRef.current) return;
      // Auto-select the most recent session
      if (sessions && sessions.length > 0 && !currentSessionId) {
        setCurrentSessionId(sessions[0].id);
      }
      setIsLoading(false);
    });
  }, [fetchSessions]); // eslint-disable-line react-hooks/exhaustive-deps

  const createSession = useCallback(async () => {
    const tempId = `temp-${Date.now()}`;
    const tempSession: ChatSession = {
      id: tempId,
      title: 'New Chat',
      status: 'active',
      origin: 'standalone',
      project_id: null,
      project_name: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    setSessions((prev) => [tempSession, ...prev]);
    setCurrentSessionId(tempId);

    try {
      const newChat = await chatApi.create();
      if (!mountedRef.current) return tempId;
      setSessions((prev) =>
        prev.map((s) => (s.id === tempId ? { ...s, id: newChat.id, title: newChat.title || 'New Chat' } : s))
      );
      setCurrentSessionId(newChat.id);
      return newChat.id;
    } catch (err) {
      console.error('[SESSIONS] Failed to create session:', err);
      setSessions((prev) => prev.filter((s) => s.id !== tempId));
      setCurrentSessionId(null);
      return null;
    }
  }, []);

  const updateSessionTitle = useCallback((sessionId: string, newTitle: string) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === sessionId ? { ...s, title: newTitle } : s))
    );
  }, []);

  const renameSession = useCallback(async (sessionId: string, newTitle: string) => {
    try {
      await chatApi.updateChatSession(sessionId, { title: newTitle });
      if (!mountedRef.current) return;
      setSessions((prev) =>
        prev.map((s) => (s.id === sessionId ? { ...s, title: newTitle } : s))
      );
    } catch (err) {
      console.error('[SESSIONS] Failed to rename session:', err);
    }
  }, []);

  const deleteSession = useCallback(async (sessionId: string) => {
    try {
      await chatApi.deleteChat(sessionId);
      if (!mountedRef.current) return;
      setSessions((prev) => {
        const remaining = prev.filter((s) => s.id !== sessionId);
        // If we deleted the current session, switch to the first remaining
        if (sessionId === currentSessionIdRef.current && remaining.length > 0) {
          setCurrentSessionId(remaining[0].id);
        } else if (remaining.length === 0) {
          setCurrentSessionId(null);
        }
        return remaining;
      });
    } catch (err) {
      console.error('[SESSIONS] Failed to delete session:', err);
    }
  }, []);

  const switchSession = useCallback((sessionId: string) => {
    setCurrentSessionId(sessionId);
  }, []);

  const updateSessionProject = useCallback(
    async (sessionId: string, projectId: string | null, projectName: string | null) => {
      try {
        await chatApi.updateChatProject(sessionId, projectId);
        if (!mountedRef.current) return;
        // Optimistic update — avoids a full refetch
        setSessions((prev) =>
          prev.map((s) =>
            s.id === sessionId
              ? { ...s, project_id: projectId, project_name: projectName }
              : s
          )
        );
      } catch (err) {
        console.error('[SESSIONS] Failed to update session project:', err);
        throw err; // Re-throw so caller can show toast
      }
    },
    []
  );

  const refreshSessions = useCallback(async () => {
    await fetchSessions();
  }, [fetchSessions]);

  return {
    sessions,
    currentSessionId,
    isLoading,
    createSession,
    renameSession,
    updateSessionTitle,
    deleteSession,
    switchSession,
    updateSessionProject,
    refreshSessions,
  };
}
