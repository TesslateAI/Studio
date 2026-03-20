import { useState, useEffect, useCallback, useRef } from 'react';
import toast from 'react-hot-toast';
import { ChatSessionSidebar } from '../components/chat/ChatSessionSidebar';
import { ChatTopBar } from '../components/chat/ChatTopBar';
import { ChatMessageList } from '../components/chat/ChatMessageList';
import { ChatInput } from '../components/chat/ChatInput';
import { type EditMode } from '../components/chat/EditModeStatus';
import { useChatSessions } from '../hooks/useChatSessions';
import { useAgentChat } from '../hooks/useAgentChat';
import { chatApi, marketplaceApi } from '../lib/api';
import type { ChatAgent } from '../types/chat';
import type { SerializedAttachment } from '../types/agent';

const LANDING_SUGGESTIONS = [
  'Analyze my codebase',
  'Help me debug an issue',
  'Write a new feature',
  'Explain how something works',
];

export default function Chat() {
  // Agent state
  const [agents, setAgents] = useState<ChatAgent[]>([]);
  const [currentAgent, setCurrentAgent] = useState<ChatAgent>({
    id: 'default',
    name: 'Agent',
    icon: '',
  });

  // Edit mode (persisted)
  const [editMode, setEditMode] = useState<EditMode>(() => {
    const stored = localStorage.getItem('chatPageEditMode');
    return stored === 'ask' || stored === 'allow' || stored === 'plan' ? stored : 'ask';
  });
  useEffect(() => {
    localStorage.setItem('chatPageEditMode', editMode);
  }, [editMode]);

  // Sidebar state (persisted)
  const [isSidebarOpen, setIsSidebarOpen] = useState(() => {
    const stored = localStorage.getItem('chatSessionSidebarOpen');
    return stored !== null ? JSON.parse(stored) : true;
  });
  useEffect(() => {
    localStorage.setItem('chatSessionSidebarOpen', JSON.stringify(isSidebarOpen));
  }, [isSidebarOpen]);

  // Auto-close sidebar on mobile
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)');
    const handleChange = (e: MediaQueryListEvent | MediaQueryList) => {
      if (e.matches) setIsSidebarOpen(false);
    };
    handleChange(mq);
    mq.addEventListener('change', handleChange);
    return () => mq.removeEventListener('change', handleChange);
  }, []);

  // Session management
  const {
    sessions,
    currentSessionId,
    isLoading: isLoadingSessions,
    createSession,
    renameSession,
    updateSessionTitle,
    deleteSession,
    switchSession,
    updateSessionProject,
    refreshSessions,
  } = useChatSessions({ standalone: true });

  // Derive connected project from the current session (persisted server-side)
  const currentSession = sessions.find((s) => s.id === currentSessionId);
  const connectedProjectId = currentSession?.project_id ?? null;
  const connectedProjectName = currentSession?.project_name ?? null;

  // Agent chat
  const {
    messages,
    isExecuting,
    isLoadingHistory,
    sendMessage,
    stopExecution,
    handleApproval,
    clearMessages,
  } = useAgentChat({
    chatId: currentSessionId,
    projectId: connectedProjectId,
    agent: currentAgent,
    editMode,
    onTitleGenerated: useCallback((chatId: string, title: string) => {
      // Update sidebar immediately when worker generates a title
      updateSessionTitle(chatId, title);
    }, [updateSessionTitle]),
  });

  // Load user's agents (same pattern as Project.tsx)
  useEffect(() => {
    let cancelled = false;
    marketplaceApi.getMyAgents()
      .then((libraryData) => {
        if (cancelled) return;
        const enabledAgents = (libraryData.agents || []).filter(
          (agent: Record<string, unknown>) =>
            agent.is_enabled && !agent.is_admin_disabled && agent.slug !== 'librarian'
        );
        const agentList: ChatAgent[] = enabledAgents.map((agent: Record<string, unknown>) => ({
          id: agent.slug as string,
          name: agent.name as string,
          icon: (agent.icon as string) || '',
          avatar_url: (agent.avatar_url as string) || undefined,
          backendId: agent.id as number,
          mode: (agent.mode as string) || 'agent',
          model: agent.model as string | undefined,
          selectedModel: agent.selected_model as string | null | undefined,
          sourceType: agent.source_type as 'open' | 'closed' | undefined,
          isCustom: agent.is_custom as boolean | undefined,
        }));
        if (agentList.length > 0) {
          setAgents(agentList);
          // Restore last-used agent from localStorage, fall back to first
          const savedSlug = localStorage.getItem('chatPageAgentSlug');
          const restored = savedSlug ? agentList.find((a) => a.id === savedSlug) : null;
          setCurrentAgent(restored || agentList[0]);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // Persist agent selection
  const handleSelectAgent = useCallback((agent: ChatAgent) => {
    setCurrentAgent(agent);
    localStorage.setItem('chatPageAgentSlug', agent.id);
  }, []);

  // Handle new session
  const handleNewSession = useCallback(async () => {
    clearMessages();
    const newId = await createSession();
    if (!newId) {
      toast.error('Failed to create new session');
    }
  }, [createSession, clearMessages]);

  // Handle send message — auto-create session if none exists
  const handleSendMessage = useCallback(async (message: string, attachments?: SerializedAttachment[]) => {
    if (!currentSessionId) {
      clearMessages();
      const newId = await createSession();
      if (!newId) {
        toast.error('Failed to create session');
        return;
      }
      sendMessage(message, newId, attachments);
      return;
    }
    sendMessage(message, undefined, attachments);
  }, [currentSessionId, sendMessage, createSession, clearMessages]);

  // Handle model change
  const handleModelChange = useCallback(async (model: string) => {
    const agentBackendId = currentAgent.backendId;
    const previousModel = currentAgent.selectedModel;
    setCurrentAgent((prev) => ({ ...prev, selectedModel: model }));
    try {
      if (agentBackendId) {
        await marketplaceApi.selectAgentModel(String(agentBackendId), model);
      }
      toast.success(`Model changed to ${model}`, { duration: 2000 });
    } catch {
      setCurrentAgent((prev) =>
        prev.backendId === agentBackendId ? { ...prev, selectedModel: previousModel } : prev
      );
      toast.error('Failed to change model');
    }
  }, [currentAgent]);

  // Handle project connection — persisted via session, survives reloads
  const handleConnectProject = useCallback(async (projectId: string, projectName: string) => {
    if (!currentSessionId) return;
    try {
      await updateSessionProject(currentSessionId, projectId, projectName);
      toast.success(`Connected to ${projectName}`);
    } catch {
      toast.error('Failed to connect project');
    }
  }, [currentSessionId, updateSessionProject]);

  const handleDisconnectProject = useCallback(async () => {
    if (!currentSessionId) return;
    try {
      await updateSessionProject(currentSessionId, null, null);
    } catch {
      toast.error('Failed to disconnect project');
    }
  }, [currentSessionId, updateSessionProject]);

  // Handle approval with mode switching
  const handleApprovalResponse = useCallback(async (
    approvalId: string,
    response: 'allow_once' | 'allow_all' | 'stop',
    toolName: string
  ) => {
    await handleApproval(approvalId, response);
    const WRITE_TOOLS = new Set(['write_file', 'patch_file', 'multi_edit']);
    if (response === 'allow_all' && WRITE_TOOLS.has(toolName)) {
      setEditMode('allow');
      toast.success('Switched to "Allow All Edits" mode');
    }
  }, [handleApproval]);

  // ESC double-press to stop
  useEffect(() => {
    let count = 0;
    let timeout: ReturnType<typeof setTimeout>;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isExecuting) {
        count++;
        clearTimeout(timeout);
        timeout = setTimeout(() => { count = 0; }, 500);
        if (count >= 2) {
          stopExecution();
          count = 0;
          toast.success('Agent stopped');
        } else {
          toast('Press ESC again to stop', { duration: 500 });
        }
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => { window.removeEventListener('keydown', handleKey); clearTimeout(timeout); };
  }, [isExecuting, stopExecution]);

  const sessionTitle = currentSession?.title || 'Chat';
  const isLanding = messages.length === 0 && !isExecuting && !isLoadingHistory;

  return (
    <div className="flex h-full w-full">
      {/* Session Sidebar — overlay on mobile, inline on desktop */}
      {isSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-40 md:hidden"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}
      <div className={`${isSidebarOpen ? 'fixed inset-y-0 left-0 z-50 md:relative md:inset-auto' : ''}`}>
        <ChatSessionSidebar
          sessions={sessions}
          currentSessionId={currentSessionId}
          isOpen={isSidebarOpen}
          onToggle={() => setIsSidebarOpen((v: boolean) => !v)}
          onSelectSession={(id) => { clearMessages(); switchSession(id); if (window.innerWidth < 768) setIsSidebarOpen(false); }}
          onNewSession={handleNewSession}
          onRenameSession={renameSession}
          onDeleteSession={deleteSession}
        />
      </div>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        <ChatTopBar
          isSidebarOpen={isSidebarOpen}
          onToggleSidebar={() => setIsSidebarOpen(true)}
          sessionTitle={sessionTitle}
          projectId={connectedProjectId}
          projectName={connectedProjectName}
          onConnectProject={handleConnectProject}
          onDisconnectProject={handleDisconnectProject}
        />

        {isLanding ? (
          <div className="flex-1 flex flex-col items-center justify-center px-4">
            <img src="/favicon.svg" alt="" className="w-10 h-10 mb-4 opacity-60" />
            <h2 className="text-lg font-semibold text-[var(--text)] mb-1">
              What can I help with?
            </h2>
            <p className="text-xs text-[var(--text-muted)] mb-6 text-center max-w-sm">
              Ask anything — connect a project for file access
            </p>
            <div className="w-full max-w-2xl">
              <ChatInput
                agents={agents}
                currentAgent={currentAgent}
                onSelectAgent={handleSelectAgent}
                onSendMessage={handleSendMessage}
                disabled={isLoadingSessions}
                isExecuting={false}
                onStop={stopExecution}
                editMode={editMode}
                onModeChange={setEditMode}
                onModelChange={handleModelChange}
              />
            </div>
            <div className="flex flex-wrap gap-2 mt-4 max-w-2xl justify-center">
              {LANDING_SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => handleSendMessage(s)}
                  className="px-3 py-1.5 text-[11px] rounded-full border border-[var(--border)]
                             text-[var(--text-muted)] hover:text-[var(--text)]
                             hover:border-[var(--border-hover)] hover:bg-[var(--surface-hover)]
                             transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            <ChatMessageList
              messages={messages}
              isExecuting={isExecuting}
              onApproval={handleApprovalResponse}
            />
            <div className="flex-shrink-0 border-t border-[var(--border)]">
              <ChatInput
                agents={agents}
                currentAgent={currentAgent}
                onSelectAgent={handleSelectAgent}
                onSendMessage={handleSendMessage}
                disabled={isLoadingHistory || isLoadingSessions}
                isExecuting={isExecuting}
                onStop={stopExecution}
                editMode={editMode}
                onModeChange={setEditMode}
                onModelChange={handleModelChange}
                isDocked
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
