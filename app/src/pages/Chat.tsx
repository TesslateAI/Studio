import { useState, useEffect, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import toast from 'react-hot-toast';
import { ChatSessionSidebar } from '../components/chat/ChatSessionSidebar';
import { ChatTopBar } from '../components/chat/ChatTopBar';
import { ChatMessageList } from '../components/chat/ChatMessageList';
import { ChatInput } from '../components/chat/ChatInput';
import { ProjectConnector } from '../components/chat/ProjectConnector';
import { CreateProjectModal } from '../components/modals/CreateProjectModal';
import { type EditMode } from '../components/chat/EditModeStatus';
import { useChatSessions } from '../hooks/useChatSessions';
import { useAgentChat } from '../hooks/useAgentChat';
import { marketplaceApi, projectsApi, tasksApi } from '../lib/api';
import { useTeam } from '../contexts/TeamContext';
import type { ChatAgent } from '../types/chat';
import type { SerializedAttachment, ChatMention } from '../types/agent';

const LANDING_SUGGESTIONS = [
  'Analyze my codebase',
  'Help me debug an issue',
  'Write a new feature',
  'Explain how something works',
];

export default function Chat() {
  const { teamSwitchKey } = useTeam();
  // Agent state
  const [agents, setAgents] = useState<ChatAgent[]>([]);
  const [currentAgent, setCurrentAgent] = useState<ChatAgent>({
    id: 'default',
    name: 'Agent',
    icon: '',
  });

  // Landing prompt from router state (replaces localStorage)
  const location = useLocation();
  const [landingPrompt] = useState<string | null>(
    () => ((location.state as Record<string, unknown>)?.landingPrompt as string) || null
  );

  // Vision support map (fetched once from models endpoint)
  const [modelVisionMap, setModelVisionMap] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    marketplaceApi
      .getAvailableModels()
      .then((data) => {
        if (cancelled) return;
        const map: Record<string, boolean> = {};
        for (const m of data.models || []) {
          map[m.id] = m.supports_vision ?? false;
        }
        setModelVisionMap(map);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const currentModelId = currentAgent.selectedModel || currentAgent.model;
  const currentModelSupportsVision = currentModelId ? modelVisionMap[currentModelId] : undefined;

  // Edit mode
  const [editMode, setEditMode] = useState<EditMode>('ask');

  // Tool calls collapsed by default
  const [toolCallsCollapsed, setToolCallsCollapsed] = useState(true);

  // Sidebar state
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

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
  } = useChatSessions({ standalone: true, teamSwitchKey });

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
    undoLastExchange,
    retryLastMessage,
  } = useAgentChat({
    chatId: currentSessionId,
    projectId: connectedProjectId,
    agent: currentAgent,
    editMode,
    onTitleGenerated: useCallback(
      (chatId: string, title: string) => {
        updateSessionTitle(chatId, title);
      },
      [updateSessionTitle]
    ),
    onSessionNeeded: createSession,
  });

  // Deep-link: if navigated with a specific sessionId (e.g. from sidebar Recent), switch to it
  useEffect(() => {
    const targetSessionId = (location.state as Record<string, unknown>)?.sessionId as
      | string
      | undefined;
    if (targetSessionId && targetSessionId !== currentSessionId) {
      clearMessages();
      switchSession(targetSessionId);
    }
  }, [location.state]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sidebar's "Show all" routes here with `openSessionsPanel: true`. Flip the
  // collapsed sessions panel open on arrival so the user lands directly in
  // the full thread list.
  useEffect(() => {
    const shouldOpen = (location.state as Record<string, unknown>)?.openSessionsPanel;
    if (shouldOpen) setIsSidebarOpen(true);
  }, [location.state]);

  // Load user's agents (same pattern as Project.tsx) — re-fetch on team switch
  useEffect(() => {
    let cancelled = false;
    marketplaceApi
      .getMyAgents()
      .then((libraryData) => {
        if (cancelled) return;
        const enabledAgents = (libraryData.agents || []).filter(
          (agent: Record<string, unknown>) =>
            agent.is_enabled && !agent.is_admin_disabled && !agent.is_system
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
          setCurrentAgent(agentList[0]);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [teamSwitchKey]);

  // Fetch installed skills for the current agent (slash command autocomplete)
  const [availableSkills, setAvailableSkills] = useState<{ name: string; description: string }[]>(
    []
  );

  useEffect(() => {
    if (!currentAgent.backendId) {
      setAvailableSkills([]);
      return;
    }
    let cancelled = false;
    marketplaceApi
      .getAgentSkills(currentAgent.backendId.toString())
      .then((data) => {
        if (!cancelled) {
          setAvailableSkills(
            (data.skills || []).map((s: { name: string; description: string }) => ({
              name: s.name,
              description: s.description,
            }))
          );
        }
      })
      .catch(() => {
        if (!cancelled) setAvailableSkills([]);
      });
    return () => {
      cancelled = true;
    };
  }, [currentAgent.backendId]);

  const handleSelectAgent = useCallback((agent: ChatAgent) => {
    setCurrentAgent(agent);
  }, []);

  // "New chat" from the topbar/sidebar header. Intentionally does NOT
  // create a DB session — that happens lazily on first send via
  // `onSessionNeeded` in useAgentChat. Clicking + repeatedly therefore
  // doesn't pollute the sidebar or DB with empty rows.
  const handleNewSession = useCallback(() => {
    clearMessages();
    switchSession(null);
  }, [clearMessages, switchSession]);

  // Handle send message — sendMessage handles session creation via onSessionNeeded
  const handleSendMessage = useCallback(
    async (
      message: string,
      attachments?: SerializedAttachment[],
      mentions?: ChatMention[]
    ) => {
      sendMessage(message, undefined, attachments, mentions);
    },
    [sendMessage]
  );

  // Handle model change
  const handleModelChange = useCallback(
    async (model: string) => {
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
    },
    [currentAgent]
  );

  // Handle project connection — persisted via session, survives reloads.
  // On the landing screen there's no session yet (lazy creation on first
  // send), but connecting a workspace is a meaningful action with persisted
  // state, so materialize the session now — same pattern as handleCreateWorkspace.
  const handleConnectProject = useCallback(
    async (projectId: string, projectName: string) => {
      let sessionId = currentSessionId;
      if (!sessionId) {
        sessionId = await createSession();
      }
      if (!sessionId) {
        toast.error('Failed to connect project');
        return;
      }
      try {
        await updateSessionProject(sessionId, projectId, projectName);
        toast.success(`Connected to ${projectName}`);
      } catch {
        toast.error('Failed to connect project');
      }
    },
    [currentSessionId, createSession, updateSessionProject]
  );

  const handleDisconnectProject = useCallback(async () => {
    if (!currentSessionId) return;
    try {
      await updateSessionProject(currentSessionId, null, null);
    } catch {
      toast.error('Failed to disconnect project');
    }
  }, [currentSessionId, updateSessionProject]);

  // "+ New Workspace" flow from the connector dropdown.
  // Modal collects name + base, then we create + auto-connect (no navigate
  // away — the user stays in chat with the new workspace already linked).
  const [showCreateWorkspace, setShowCreateWorkspace] = useState(false);
  const [isCreatingWorkspace, setIsCreatingWorkspace] = useState(false);

  const handleCreateWorkspace = useCallback(
    async (projectName: string, baseId?: string, baseVersion?: string) => {
      if (isCreatingWorkspace) return;
      setIsCreatingWorkspace(true);
      const loadingToast = toast.loading('Creating workspace...');
      try {
        const response = await projectsApi.create(
          projectName,
          '',
          'base',
          undefined,
          'main',
          baseId,
          baseVersion || undefined
        );
        const project = response.project;
        const taskId = response.task_id;

        // Ensure we have a session to attach the project to. On the
        // landing screen there's no session yet (lazy creation); creating
        // a workspace is a meaningful action so it's fine to materialize
        // the session now.
        let sessionId = currentSessionId;
        if (!sessionId) {
          sessionId = await createSession();
        }
        if (sessionId) {
          await updateSessionProject(sessionId, project.id, project.name);
        }

        toast.success(`Connected to ${project.name}`, {
          id: loadingToast,
          duration: 2000,
        });
        setShowCreateWorkspace(false);

        // Background setup continues — don't block the UI. The connection
        // is already recorded; file access becomes available once setup
        // finishes.
        if (taskId) {
          tasksApi.pollUntilComplete(taskId).catch(() => {
            /* non-blocking */
          });
        }
      } catch (err) {
        const detail = (err as { response?: { data?: { detail?: string } } })?.response
          ?.data?.detail;
        toast.error(detail || 'Failed to create workspace', { id: loadingToast });
      } finally {
        setIsCreatingWorkspace(false);
      }
    },
    [currentSessionId, createSession, updateSessionProject, isCreatingWorkspace]
  );

  // Handle approval with mode switching
  const handleApprovalResponse = useCallback(
    async (
      approvalId: string,
      response:
        | 'allow_once'
        | 'allow_all'
        | 'stop'
        | 'publish_and_activate'
        | 'save_draft'
        | 'cancel',
      toolName: string
    ) => {
      await handleApproval(approvalId, response);
      const WRITE_TOOLS = new Set(['write_file', 'patch_file', 'multi_edit']);
      if (response === 'allow_all' && WRITE_TOOLS.has(toolName)) {
        setEditMode('allow');
        toast.success('Switched to "Allow All Edits" mode');
      }
    },
    [handleApproval]
  );

  // ESC double-press to stop
  useEffect(() => {
    let count = 0;
    let timeout: ReturnType<typeof setTimeout>;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isExecuting) {
        count++;
        clearTimeout(timeout);
        timeout = setTimeout(() => {
          count = 0;
        }, 500);
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
    return () => {
      window.removeEventListener('keydown', handleKey);
      clearTimeout(timeout);
    };
  }, [isExecuting, stopExecution]);

  const sessionTitle = currentSession?.title || 'Agents';
  const isLanding = messages.length === 0 && !isExecuting && !isLoadingHistory;

  return (
    <div className="flex h-full w-full">
      {/* Session Sidebar — overlay on mobile, inline on desktop */}
      {isSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-20 md:hidden"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}
      {isSidebarOpen && (
        <div
          className="fixed inset-y-0 left-0 z-30 md:relative md:inset-auto"
        >
          <ChatSessionSidebar
            sessions={sessions}
            currentSessionId={currentSessionId}
            isOpen={isSidebarOpen}
            onToggle={() => setIsSidebarOpen((v: boolean) => !v)}
            onSelectSession={(id) => {
              clearMessages();
              switchSession(id);
              if (window.innerWidth < 768) setIsSidebarOpen(false);
            }}
            onNewSession={handleNewSession}
            onRenameSession={renameSession}
            onDeleteSession={deleteSession}
          />
        </div>
      )}

      {/* Main chat area */}
      <div
        key={teamSwitchKey}
        className="flex-1 flex flex-col min-w-0"
        style={{ animation: 'fade-in 0.25s ease-out' }}
      >
        <ChatTopBar
          isSidebarOpen={isSidebarOpen}
          onToggleSidebar={() => setIsSidebarOpen(true)}
          sessionTitle={sessionTitle}
          onNewSession={handleNewSession}
        />

        {isLanding ? (
          <div className="flex-1 flex flex-col items-center justify-center px-4">
            <img src="/favicon.svg" alt="" className="w-10 h-10 mb-4 opacity-60" />
            <h2 className="text-lg font-semibold text-[var(--text)] mb-6">What can I help with?</h2>
            <div className="w-full max-w-2xl">
              <ChatInput
                agents={agents}
                currentAgent={currentAgent}
                onSelectAgent={handleSelectAgent}
                onSendMessage={handleSendMessage}
                disabled={isLoadingSessions}
                isExecuting={isExecuting}
                onStop={stopExecution}
                onClearHistory={clearMessages}
                onUndo={undoLastExchange}
                onRetry={retryLastMessage}
                editMode={editMode}
                onModeChange={setEditMode}
                onModelChange={handleModelChange}
                currentModelSupportsVision={currentModelSupportsVision}
                availableSkills={availableSkills}
                toolCallsCollapsed={toolCallsCollapsed}
                onToggleToolCallsCollapsed={() => setToolCallsCollapsed((v) => !v)}
                prefillMessage={landingPrompt}
                onPrefillConsumed={() => {}}
              />

              {/* Shadow card peeking out from beneath the chat input — holds
                  the primary workspace-connector affordance for new
                  conversations. Slightly narrower + a touch elevated so the
                  card above looks like it's resting on a stack.

                  The card has `-mt-2` (8px overlap with the input above), so
                  the *visible* region runs from the input's bottom edge to
                  the card's bottom edge. To center the connector pill in
                  that visible region, we add +8px to the top padding so
                  pt > pb by exactly the overlap. */}
              <div className="mx-4 -mt-2 px-3 pt-4 pb-2 flex items-center bg-[var(--surface-hover)] border border-[var(--border)] border-t-0 rounded-b-[var(--radius)]">
                <ProjectConnector
                  projectId={connectedProjectId}
                  projectName={connectedProjectName}
                  onConnect={handleConnectProject}
                  onDisconnect={handleDisconnectProject}
                  onRequestNewWorkspace={() => setShowCreateWorkspace(true)}
                />
              </div>
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
          // Once the conversation starts, the input "lifts off" the bottom
          // and floats centered inside the chat area (not the viewport, so
          // it stays centered regardless of sidebar state). Message list
          // scrolls beneath, with bottom padding so the floating input never
          // covers the most recent message.
          <div className="flex-1 relative overflow-hidden">
            <div className="absolute inset-0 overflow-y-auto pb-[180px]">
              <div className="max-w-3xl mx-auto">
                <ChatMessageList
                  messages={messages}
                  isExecuting={isExecuting}
                  onApproval={handleApprovalResponse}
                  toolCallsCollapsed={toolCallsCollapsed}
                />
              </div>
            </div>

            <div
              className="absolute left-1/2 -translate-x-1/2 bottom-6 z-30
                         w-[min(760px,calc(100%-48px))]
                         bg-[var(--bg)] border border-[var(--border-hover)]
                         rounded-[var(--radius)]
                         max-md:bottom-0 max-md:left-0 max-md:right-0 max-md:translate-x-0
                         max-md:w-full max-md:rounded-b-none"
            >
              <ChatInput
                agents={agents}
                currentAgent={currentAgent}
                onSelectAgent={handleSelectAgent}
                onSendMessage={handleSendMessage}
                disabled={isLoadingHistory || isLoadingSessions}
                isExecuting={isExecuting}
                onStop={stopExecution}
                onClearHistory={clearMessages}
                onUndo={undoLastExchange}
                onRetry={retryLastMessage}
                editMode={editMode}
                onModeChange={setEditMode}
                onModelChange={handleModelChange}
                currentModelSupportsVision={currentModelSupportsVision}
                availableSkills={availableSkills}
                toolCallsCollapsed={toolCallsCollapsed}
                onToggleToolCallsCollapsed={() => setToolCallsCollapsed((v) => !v)}
                isDocked
              />
            </div>
          </div>
        )}
      </div>

      <CreateProjectModal
        isOpen={showCreateWorkspace}
        onClose={() => !isCreatingWorkspace && setShowCreateWorkspace(false)}
        onConfirm={handleCreateWorkspace}
        isLoading={isCreatingWorkspace}
      />
    </div>
  );
}
