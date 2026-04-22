import { useState, useRef, useEffect, useCallback } from 'react';
import { chatApi } from '../lib/api';
import type {
  AgentMessageData,
  SerializedAttachment,
  DBMessage,
  ToolCallDetail,
  AgentStep,
} from '../types/agent';
import type { ChatAgent } from '../types/chat';
import type { EditMode } from '../components/chat/EditModeStatus';
import { nodeConfigEvents } from '../utils/nodeConfigEvents';
import type {
  ArchitectureNodeAddedEvent,
  NodeConfigCancelledEvent,
  NodeConfigResumedEvent,
  SecretRotatedEvent,
  UserInputRequiredEvent,
} from '../types/nodeConfig';

/**
 * Re-dispatch a node-config-family SSE event onto the local bus so the
 * ProjectPage can manage dock tabs / canvas pulses without pulling in
 * UI dependencies here.
 */
function dispatchNodeConfigEvent(
  type: string,
  data: Record<string, unknown> | undefined
): boolean {
  if (!data) return false;
  switch (type) {
    case 'architecture_node_added':
      nodeConfigEvents.emit(
        'architecture-node-added',
        data as unknown as ArchitectureNodeAddedEvent
      );
      return true;
    case 'user_input_required':
      nodeConfigEvents.emit(
        'user-input-required',
        data as unknown as UserInputRequiredEvent
      );
      return true;
    case 'node_config_resumed':
      nodeConfigEvents.emit(
        'node-config-resumed',
        data as unknown as NodeConfigResumedEvent
      );
      return true;
    case 'node_config_cancelled':
      nodeConfigEvents.emit(
        'node-config-cancelled',
        data as unknown as NodeConfigCancelledEvent
      );
      return true;
    case 'secret_rotated':
      nodeConfigEvents.emit(
        'secret-rotated',
        data as unknown as SecretRotatedEvent
      );
      return true;
    default:
      return false;
  }
}

function formatAgentError(raw: string): string {
  if (raw.includes('does not exist') || raw.includes('NotFoundError'))
    return 'Model not available. Try selecting a different model.';
  if (raw.includes('429') || raw.includes('rate limit'))
    return 'Rate limited. Please wait a moment and try again.';
  if (raw.includes('timeout') || raw.includes('timed out'))
    return 'Request timed out. Please try again.';
  if (raw.includes('401') || raw.includes('authentication') || raw.includes('api_key'))
    return 'Authentication error. Check your API key configuration.';
  if (raw.includes('Resource limit')) return 'Resource limit exceeded for this session.';
  if (raw.includes('budget') || raw.includes('Budget'))
    return 'Usage limit reached. Please try again or purchase more credits.';
  return raw.length > 120 ? raw.slice(0, 120) + '...' : raw;
}

export interface ChatMessage {
  id: string;
  type: 'user' | 'ai' | 'approval_request';
  content: string;
  attachments?: SerializedAttachment[];
  agentData?: AgentMessageData;
  agentIcon?: string;
  agentAvatarUrl?: string;
  agentType?: string;
  approvalId?: string;
  toolName?: string;
  toolParameters?: Record<string, unknown>;
  toolDescription?: string;
}

interface UseAgentChatOptions {
  chatId: string | null;
  projectId?: string | null;
  agent: ChatAgent;
  editMode: EditMode;
  onTitleGenerated?: (chatId: string, title: string) => void;
  /** Called when sendMessage needs a session but chatId is null. Must return the new chat ID or null on failure. */
  onSessionNeeded?: () => Promise<string | null>;
}

export function useAgentChat({
  chatId,
  projectId,
  agent,
  editMode,
  onTitleGenerated,
  onSessionNeeded,
}: UseAgentChatOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isExecuting, setIsExecuting] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const isMountedRef = useRef(true);
  const isExecutingRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const agentTaskIdRef = useRef<string | null>(null);
  const editModeRef = useRef<EditMode>(editMode);
  const onTitleGeneratedRef = useRef(onTitleGenerated);
  const onSessionNeededRef = useRef(onSessionNeeded);

  useEffect(() => {
    editModeRef.current = editMode;
  }, [editMode]);

  useEffect(() => {
    onTitleGeneratedRef.current = onTitleGenerated;
  }, [onTitleGenerated]);

  useEffect(() => {
    onSessionNeededRef.current = onSessionNeeded;
  }, [onSessionNeeded]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // Active task reconnection EventSource ref
  const activeEventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevChatIdRef = useRef<string | null>(null);

  // Load chat history + reconnect to active agent task when chatId changes
  useEffect(() => {
    const prevChatId = prevChatIdRef.current;
    prevChatIdRef.current = chatId;

    // Only reset local UI state when switching between real sessions. We no
    // longer abort the SSE stream / running task — AgentRunsContext keeps
    // background streams alive so switching sessions doesn't kill parallel
    // agents. The hook just stops rendering events for the old chat.
    const isTempSwap = prevChatId?.startsWith('temp-') && chatId && !chatId.startsWith('temp-');
    if (prevChatId !== null && prevChatId !== chatId && !isTempSwap) {
      if (activeEventSourceRef.current) {
        activeEventSourceRef.current.close();
        activeEventSourceRef.current = null;
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      // IMPORTANT: do NOT abort abortControllerRef — that would kill an
      // in-flight agent in the previous chat. The previous chat keeps its
      // AbortController; the old stream continues in the background via
      // AgentRunsContext, and this hook just detaches from it.
      isExecutingRef.current = false;
      setIsExecuting(false);
    }

    if (!chatId) {
      setMessages([]);
      return;
    }

    // Skip history load if we're mid-execution (e.g. just created a session
    // and immediately sent a message — the user message is already in state)
    if (isExecutingRef.current) return;

    let cancelled = false;

    const loadHistory = async (): Promise<ChatMessage[]> => {
      setIsLoadingHistory(true);
      try {
        const dbMessages = await chatApi.getStandaloneMessages(chatId);

        if (cancelled) return [];

        const expandedMessages: ChatMessage[] = [];
        (dbMessages as DBMessage[]).forEach((msg: DBMessage, idx: number) => {
          const messageType = msg.role === 'assistant' ? 'ai' : 'user';
          if (messageType === 'user' || !msg.message_metadata?.agent_mode) {
            if (msg.content && msg.content.trim()) {
              expandedMessages.push({
                id: `msg-${idx}`,
                type: messageType,
                content: msg.content,
                attachments: msg.message_metadata?.attachments as
                  | SerializedAttachment[]
                  | undefined,
              });
            }
            return;
          }

          const finalResponse = msg.content && msg.content.trim() ? msg.content : '';

          if (msg.message_metadata.steps && msg.message_metadata.steps.length > 0) {
            msg.message_metadata.steps.forEach((step, stepIdx: number) => {
              const stepRecord = step as unknown as Record<string, unknown>;
              const hasContent =
                (stepRecord.tool_calls && (stepRecord.tool_calls as unknown[]).length > 0) ||
                (stepRecord.thought && (stepRecord.thought as string).trim());
              if (!hasContent) return;

              expandedMessages.push({
                id: `msg-${idx}-step-${stepIdx}`,
                type: 'ai',
                content: '',
                agentData: {
                  steps: [stepRecord],
                  iterations: (stepRecord.iteration as number) || stepIdx + 1,
                  tool_calls_made: (stepRecord.tool_calls as unknown[])?.length || 0,
                  completion_reason: 'step_complete',
                } as unknown as AgentMessageData,
              });
            });

            if (finalResponse) {
              expandedMessages.push({
                id: `msg-${idx}-final`,
                type: 'ai',
                content: finalResponse,
                agentData: {
                  steps: [],
                  iterations: 0,
                  tool_calls_made: 0,
                  completion_reason: 'complete',
                },
              });
            }
          } else if (finalResponse) {
            expandedMessages.push({
              id: `msg-${idx}-result`,
              type: 'ai',
              content: finalResponse,
              agentData: {
                steps: [],
                iterations: 0,
                tool_calls_made: 0,
                completion_reason: 'complete',
              },
            });
          }
        });

        setMessages(expandedMessages);
        return expandedMessages;
      } catch (err) {
        console.error('[CHAT] Failed to load history:', err);
        if (!cancelled) setMessages([]);
        return [];
      } finally {
        if (!cancelled) setIsLoadingHistory(false);
      }
    };

    // Check for active agent task and reconnect to its SSE stream
    const checkActiveTask = async (currentMessages: ChatMessage[]) => {
      if (cancelled) return;
      try {
        // Use empty string for projectId — backend accepts it for standalone chats
        const activeTask = await chatApi.getActiveTask('', chatId);
        if (!activeTask?.task_id || cancelled) return;

        isExecutingRef.current = true;
        setIsExecuting(true);
        agentTaskIdRef.current = activeTask.task_id;

        const thinkingId = `reconnect-${activeTask.task_id}`;

        // Only add thinking placeholder if history didn't already have one
        const alreadyHasPlaceholder = currentMessages.some(
          (m) => m.agentData?.completion_reason === 'in_progress'
        );
        if (!alreadyHasPlaceholder) {
          setMessages((prev) => [
            ...prev,
            {
              id: thinkingId,
              type: 'ai',
              content: '',
              agentData: {
                steps: [],
                iterations: 0,
                tool_calls_made: 0,
                completion_reason: 'in_progress',
              },
              agentIcon: agent.icon,
              agentAvatarUrl: agent.avatar_url,
              agentType: agent.name,
            },
          ]);
        }

        // Subscribe to live events via EventSource (SSE)
        const eventSource = chatApi.subscribeToTask(activeTask.task_id);
        activeEventSourceRef.current = eventSource;

        const cleanupReconnect = () => {
          if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
          eventSource.close();
          activeEventSourceRef.current = null;
          if (!cancelled) {
            isExecutingRef.current = false;
            setIsExecuting(false);
            agentTaskIdRef.current = null;
          }
        };

        // Safety timeout: if no events within 30s, task is likely stale
        const resetSafetyTimeout = () => {
          if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
          reconnectTimeoutRef.current = setTimeout(() => {
            cleanupReconnect();
            if (!cancelled) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === thinkingId && m.agentData?.completion_reason === 'in_progress'
                    ? { ...m, agentData: { ...m.agentData!, completion_reason: 'error' } }
                    : m
                )
              );
            }
          }, 30000);
        };
        resetSafetyTimeout();

        eventSource.onmessage = (event) => {
          if (cancelled) return;
          try {
            const data = JSON.parse(event.data);
            resetSafetyTimeout();

            if (data.type === 'agent_step') {
              const transformedStep = {
                ...data.data,
                tool_calls:
                  (data.data.tool_calls as Array<{ name: string; parameters: unknown }>)?.map(
                    (tc: { name: string; parameters: unknown }, index: number) => ({
                      name: tc.name,
                      parameters: tc.parameters,
                      result: (data.data.tool_results as unknown[])?.[index] || {},
                    })
                  ) || [],
              };
              delete transformedStep.tool_results;

              const stepMessage: ChatMessage = {
                id: `msg-${crypto.randomUUID()}-step-${data.data.iteration}`,
                type: 'ai',
                content: '',
                agentData: {
                  steps: [transformedStep],
                  iterations: (data.data.iteration as number) || 0,
                  tool_calls_made: (data.data.tool_calls as unknown[])?.length || 0,
                  completion_reason: 'step_complete',
                },
                agentIcon: agent.icon,
                agentAvatarUrl: agent.avatar_url,
                agentType: agent.name,
              };
              setMessages((prev) => {
                const withoutThinking = prev.filter((m) => m.id !== thinkingId);
                return [
                  ...withoutThinking,
                  stepMessage,
                  {
                    id: thinkingId,
                    type: 'ai',
                    content: '',
                    agentData: {
                      steps: [],
                      iterations: 0,
                      tool_calls_made: 0,
                      completion_reason: 'in_progress',
                    },
                    agentIcon: agent.icon,
                    agentAvatarUrl: agent.avatar_url,
                    agentType: agent.name,
                  },
                ];
              });
            } else if (
              dispatchNodeConfigEvent(
                data.type as string,
                data.data as Record<string, unknown> | undefined
              )
            ) {
              // handled via nodeConfigEvents bus
            } else if (data.type === 'approval_required') {
              const approvalData = data.data || data;
              if (editModeRef.current === 'allow') {
                chatApi
                  .sendApprovalResponse(approvalData.approval_id, 'allow_all')
                  .catch((err) => console.error('[APPROVAL] Auto-approve failed:', err));
              } else {
                setMessages((prev) => [
                  ...prev,
                  {
                    id: `approval-${crypto.randomUUID()}`,
                    type: 'approval_request',
                    content: '',
                    approvalId: approvalData.approval_id,
                    toolName: approvalData.tool_name,
                    toolParameters: approvalData.tool_parameters,
                    toolDescription: approvalData.tool_description,
                  },
                ]);
              }
            } else if (data.type === 'chat_title') {
              const title = data.data.title as string;
              const titleChatId = data.data.chat_id as string;
              if (title && titleChatId && onTitleGeneratedRef.current) {
                onTitleGeneratedRef.current(titleChatId, title);
              }
            } else if (data.type === 'credits_used') {
              window.dispatchEvent(
                new CustomEvent('credits-updated', {
                  detail: {
                    newBalance: data.data.new_balance,
                    creditsUsed: data.data.credits_deducted,
                  },
                })
              );
            } else if (data.type === 'complete') {
              setMessages((prev) => prev.filter((m) => m.id !== thinkingId));
              const completeData = data.data || {};
              const finalContent = completeData.final_response || '';
              if (finalContent && finalContent.trim()) {
                setMessages((prev) => {
                  const lastMsg = prev[prev.length - 1];
                  if (lastMsg && lastMsg.agentData) {
                    return [...prev.slice(0, -1), { ...lastMsg, content: finalContent }];
                  }
                  return [
                    ...prev,
                    {
                      id: `msg-${crypto.randomUUID()}-result`,
                      type: 'ai',
                      content: finalContent,
                      agentData: {
                        steps: [],
                        iterations: 0,
                        tool_calls_made: 0,
                        completion_reason: 'complete',
                      },
                      agentIcon: agent.icon,
                      agentAvatarUrl: agent.avatar_url,
                      agentType: agent.name,
                    },
                  ];
                });
              }
              cleanupReconnect();
            } else if (data.type === 'error') {
              const errorMsg = data.data?.message || 'Agent execution failed';
              setMessages((prev) => {
                const withoutThinking = prev.filter((m) => m.id !== thinkingId);
                return [
                  ...withoutThinking,
                  {
                    id: `msg-${crypto.randomUUID()}-error`,
                    type: 'ai',
                    content: `I encountered an error: ${errorMsg}`,
                    agentData: {
                      steps: [],
                      iterations: 0,
                      tool_calls_made: 0,
                      completion_reason: 'error',
                    },
                    agentIcon: agent.icon,
                    agentAvatarUrl: agent.avatar_url,
                    agentType: agent.name,
                  },
                ];
              });
              cleanupReconnect();
            } else if (data.type === 'done') {
              cleanupReconnect();
            }
          } catch {
            // ignore parse errors
          }
        };

        eventSource.onerror = () => {
          cleanupReconnect();
          if (!cancelled) {
            setMessages((prev) => prev.filter((m) => m.id !== thinkingId));
          }
        };
      } catch {
        // No active task — that's fine
      }
    };

    // Sequential: load history first, then check for active task
    loadHistory().then((msgs) => {
      if (!cancelled) checkActiveTask(msgs);
    });

    return () => {
      cancelled = true;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (activeEventSourceRef.current) {
        activeEventSourceRef.current.close();
        activeEventSourceRef.current = null;
      }
    };
  }, [chatId, agent]);

  const sendMessage = useCallback(
    async (message: string, overrideChatId?: string, attachments?: SerializedAttachment[]) => {
      if ((!message.trim() && (!attachments || attachments.length === 0)) || isExecuting) return;

      // Resolve the chat ID — create a session on the fly if needed
      let effectiveChatId = overrideChatId || chatId;
      if (!effectiveChatId) {
        if (!onSessionNeededRef.current) return;
        isExecutingRef.current = true; // prevent history-load race during session creation
        const newId = await onSessionNeededRef.current();
        if (!newId) {
          isExecutingRef.current = false;
          return;
        }
        effectiveChatId = newId;
      }

      const userMessage: ChatMessage = {
        id: `msg-${crypto.randomUUID()}`,
        type: 'user',
        content: message,
        attachments,
      };
      setMessages((prev) => [...prev, userMessage]);
      isExecutingRef.current = true;
      setIsExecuting(true);

      const controller = new AbortController();
      abortControllerRef.current = controller;

      const thinkingMessageId = `msg-${crypto.randomUUID()}-thinking`;
      const thinkingMessage: ChatMessage = {
        id: thinkingMessageId,
        type: 'ai',
        content: '',
        agentData: {
          steps: [],
          iterations: 0,
          tool_calls_made: 0,
          completion_reason: 'in_progress',
        },
        agentIcon: agent.icon,
        agentAvatarUrl: agent.avatar_url,
        agentType: agent.name,
      };
      setMessages((prev) => [...prev, thinkingMessage]);

      try {
        await chatApi.sendAgentMessageStreaming(
          {
            project_id: projectId || undefined,
            chat_id: effectiveChatId,
            message,
            agent_id: agent.backendId?.toString(),
            max_iterations: undefined,
            edit_mode: editModeRef.current,
            attachments,
          },
          (event) => {
            if (!isMountedRef.current) return;

            if (event.data?.task_id) {
              agentTaskIdRef.current = event.data.task_id as string;
            }

            if (event.type === 'tool_call') {
              // Per-tool streaming — accumulate into ONE message per iteration
              const tc = event.data || {};
              const iterMsgId = `${thinkingMessageId}-iter-${tc.iteration}`;
              const newTool = {
                name: tc.name as string,
                parameters: tc.parameters,
                result: tc.result,
              } as ToolCallDetail;

              setMessages((prev) => {
                const withoutThinking = prev.filter((m) => m.id !== thinkingMessageId);
                const existingIdx = withoutThinking.findIndex((m) => m.id === iterMsgId);

                if (existingIdx >= 0) {
                  const existing = withoutThinking[existingIdx];
                  const currentTools = existing.agentData?.steps?.[0]?.tool_calls || [];
                  withoutThinking[existingIdx] = {
                    ...existing,
                    agentData: {
                      ...existing.agentData!,
                      steps: [
                        {
                          ...existing.agentData!.steps[0],
                          tool_calls: [...currentTools, newTool],
                        } as AgentStep,
                      ],
                      tool_calls_made: currentTools.length + 1,
                    },
                  };
                } else {
                  withoutThinking.push({
                    id: iterMsgId,
                    type: 'ai',
                    content: '',
                    agentData: {
                      steps: [{ tool_calls: [newTool] } as AgentStep],
                      iterations: (tc.iteration as number) || 0,
                      tool_calls_made: 1,
                      completion_reason: 'tool_streaming',
                    },
                    agentIcon: agent.icon,
                    agentAvatarUrl: agent.avatar_url,
                    agentType: agent.name,
                  });
                }

                return [...withoutThinking, { ...thinkingMessage, id: thinkingMessageId }];
              });
            } else if (event.type === 'agent_step') {
              // Finalize iteration message with canonical data
              const iterMsgId = `${thinkingMessageId}-iter-${event.data.iteration}`;
              const transformedStep = {
                ...event.data,
                tool_calls:
                  (event.data.tool_calls as Array<{ name: string; parameters: unknown }>)?.map(
                    (tc: { name: string; parameters: unknown }, index: number) => ({
                      name: tc.name,
                      parameters: tc.parameters,
                      result:
                        ((event.data as Record<string, unknown>).tool_results as unknown[])?.[
                          index
                        ] || {},
                    })
                  ) || [],
              } as AgentStep;
              delete (transformedStep as unknown as Record<string, unknown>).tool_results;

              const stepMessage: ChatMessage = {
                id: iterMsgId,
                type: 'ai',
                content: '',
                agentData: {
                  steps: [transformedStep],
                  iterations: (event.data.iteration as number) || 0,
                  tool_calls_made: (event.data.tool_calls as unknown[])?.length || 0,
                  completion_reason: 'step_complete',
                },
                agentIcon: agent.icon,
                agentAvatarUrl: agent.avatar_url,
                agentType: agent.name,
              };

              setMessages((prev) => {
                const withoutThinking = prev.filter((msg) => msg.id !== thinkingMessageId);
                const existingIdx = withoutThinking.findIndex((m) => m.id === iterMsgId);
                if (existingIdx >= 0) {
                  withoutThinking[existingIdx] = stepMessage;
                } else {
                  withoutThinking.push(stepMessage);
                }
                return [...withoutThinking, { ...thinkingMessage, id: thinkingMessageId }];
              });
            } else if (event.type === 'complete') {
              setMessages((prev) => prev.filter((msg) => msg.id !== thinkingMessageId));

              if (event.data.success === false) {
                const errorDetail = event.data.error
                  ? formatAgentError(event.data.error as string)
                  : 'Agent could not complete the task';

                setMessages((prev) => {
                  const lastMsg = prev[prev.length - 1];
                  const errorContent = `I encountered an error: ${errorDetail}`;
                  if (lastMsg && lastMsg.agentData) {
                    return [
                      ...prev.slice(0, -1),
                      {
                        ...lastMsg,
                        content: errorContent,
                        agentData: { ...lastMsg.agentData, completion_reason: 'error' },
                      },
                    ];
                  }
                  return [
                    ...prev,
                    {
                      id: `msg-${crypto.randomUUID()}-error`,
                      type: 'ai',
                      content: errorContent,
                      agentData: {
                        steps: [],
                        iterations: (event.data.iterations as number) || 0,
                        tool_calls_made: (event.data.tool_calls_made as number) || 0,
                        completion_reason: 'error',
                      },
                      agentIcon: agent.icon,
                      agentAvatarUrl: agent.avatar_url,
                      agentType: agent.name,
                    },
                  ];
                });
              } else {
                const finalContent = event.data.final_response as string;
                if (finalContent && finalContent.trim()) {
                  setMessages((prev) => {
                    const lastMsg = prev[prev.length - 1];
                    if (lastMsg && lastMsg.agentData) {
                      return [...prev.slice(0, -1), { ...lastMsg, content: finalContent }];
                    }
                    return [
                      ...prev,
                      {
                        id: `msg-${crypto.randomUUID()}-result`,
                        type: 'ai',
                        content: finalContent,
                        agentData: {
                          steps: [],
                          iterations: 0,
                          tool_calls_made: 0,
                          completion_reason: 'complete',
                        },
                        agentIcon: agent.icon,
                        agentAvatarUrl: agent.avatar_url,
                        agentType: agent.name,
                      },
                    ];
                  });
                }
              }
            } else if (event.type === 'chat_title') {
              const title = event.data.title as string;
              const titleChatId = event.data.chat_id as string;
              if (title && titleChatId && onTitleGeneratedRef.current) {
                onTitleGeneratedRef.current(titleChatId, title);
              }
            } else if (event.type === 'credits_used') {
              window.dispatchEvent(
                new CustomEvent('credits-updated', {
                  detail: {
                    newBalance: event.data.new_balance,
                    creditsUsed: event.data.credits_deducted,
                    costTotal: event.data.cost_total,
                  },
                })
              );
            } else if (event.type === 'error') {
              const errorData = event.data || {};
              if ((errorData as { code?: string }).code === 'insufficient_credits') {
                setMessages((prev) => prev.filter((msg) => msg.id !== thinkingMessageId));
                return;
              }
              const errorMsg =
                (event.data as { message?: string })?.message || 'Agent execution failed';
              throw new Error(errorMsg);
            } else if (
              dispatchNodeConfigEvent(
                event.type as string,
                event.data as Record<string, unknown> | undefined
              )
            ) {
              // handled via nodeConfigEvents bus
            } else if (event.type === 'approval_required') {
              if (editModeRef.current === 'allow') {
                chatApi
                  .sendApprovalResponse(event.data.approval_id as string, 'allow_all')
                  .catch((err) => console.error('[APPROVAL] Auto-approve failed:', err));
              } else {
                const approvalMessage: ChatMessage = {
                  id: `approval-${crypto.randomUUID()}`,
                  type: 'approval_request',
                  content: '',
                  approvalId: event.data.approval_id as string,
                  toolName: event.data.tool_name as string,
                  toolParameters: event.data.tool_parameters as Record<string, unknown>,
                  toolDescription: event.data.tool_description as string,
                };
                setMessages((prev) => [...prev, approvalMessage]);
              }
            } else if (event.type === 'text_delta') {
              const delta = (event.data?.content as string) || '';
              if (delta) {
                setMessages((prev) => {
                  const updated = [...prev];
                  // Find the last non-thinking message
                  const nonThinking = updated.filter((m) => m.id !== thinkingMessageId);
                  const lastMsg = nonThinking[nonThinking.length - 1];
                  if (lastMsg && lastMsg.type === 'ai' && !lastMsg.agentData?.steps?.length) {
                    const idx = updated.indexOf(lastMsg);
                    updated[idx] = { ...lastMsg, content: (lastMsg.content || '') + delta };
                  } else {
                    const streamMsg: ChatMessage = {
                      id: `${thinkingMessageId}-stream`,
                      type: 'ai',
                      content: delta,
                      agentIcon: agent.icon,
                      agentAvatarUrl: agent.avatar_url,
                      agentType: agent.name,
                    };
                    const thinkingIdx = updated.findIndex((m) => m.id === thinkingMessageId);
                    if (thinkingIdx >= 0) {
                      updated.splice(thinkingIdx, 0, streamMsg);
                    } else {
                      updated.push(streamMsg);
                    }
                  }
                  return updated;
                });
              }
            }
          },
          controller.signal
        );
      } catch (error: unknown) {
        if (error instanceof Error && error.name === 'AbortError') {
          setMessages((prev) => {
            const withoutThinking = prev.filter((msg) => msg.id !== thinkingMessageId);
            const lastIdx = withoutThinking.length - 1;
            if (lastIdx >= 0 && withoutThinking[lastIdx].agentData) {
              withoutThinking[lastIdx] = {
                ...withoutThinking[lastIdx],
                content: withoutThinking[lastIdx].content || '_Execution stopped by user_',
                agentData: {
                  ...withoutThinking[lastIdx].agentData!,
                  completion_reason: 'cancelled',
                },
              };
              return withoutThinking;
            }
            return withoutThinking;
          });
          return;
        }

        setMessages((prev) => {
          const withoutThinking = prev.filter((msg) => msg.id !== thinkingMessageId);
          return [
            ...withoutThinking,
            {
              id: `msg-${crypto.randomUUID()}-error`,
              type: 'ai',
              content: 'I encountered an error while working on your request. Please try again.',
            },
          ];
        });
      } finally {
        isExecutingRef.current = false;
        setIsExecuting(false);
        abortControllerRef.current = null;
        setMessages((prev) => prev.filter((msg) => msg.id !== thinkingMessageId));
      }
    },
    [chatId, projectId, agent, isExecuting]
  );

  const stopExecution = useCallback(async () => {
    const controller = abortControllerRef.current;
    if (controller) {
      controller.abort();
      abortControllerRef.current = null;
    }
    const taskId = agentTaskIdRef.current;
    if (taskId) {
      try {
        await chatApi.cancelAgentTask(taskId);
      } catch {
        /* best effort */
      }
      agentTaskIdRef.current = null;
    }
    isExecutingRef.current = false;
    setIsExecuting(false);
  }, []);

  const handleApproval = useCallback(
    async (approvalId: string, response: 'allow_once' | 'allow_all' | 'stop') => {
      try {
        await chatApi.sendApprovalResponse(approvalId, response);
      } catch (err) {
        console.error('[APPROVAL] Failed to send response:', err);
      }
      setMessages((prev) =>
        prev.filter((msg) => !(msg.type === 'approval_request' && msg.approvalId === approvalId))
      );
    },
    []
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  const undoLastExchange = useCallback(async (): Promise<string | null> => {
    if (isExecutingRef.current) return null;
    const targetChatId = chatId;
    if (!targetChatId) return null;

    try {
      const result = await chatApi.undoLastExchange(targetChatId);
      if (!result.success || result.removed_count === 0) return null;

      // Remove the last user + ai messages from local state
      setMessages((prev) => {
        // Walk backwards: remove last ai, then last user
        const copy = [...prev];
        // Remove last ai message
        for (let i = copy.length - 1; i >= 0; i--) {
          if (copy[i].type === 'ai') {
            copy.splice(i, 1);
            break;
          }
        }
        // Remove last user message
        for (let i = copy.length - 1; i >= 0; i--) {
          if (copy[i].type === 'user') {
            copy.splice(i, 1);
            break;
          }
        }
        return copy;
      });

      return result.last_user_message;
    } catch (err) {
      console.error('[UNDO] Failed:', err);
      return null;
    }
  }, [chatId]);

  const retryLastMessage = useCallback(async () => {
    const lastContent = await undoLastExchange();
    if (lastContent) {
      sendMessage(lastContent);
    }
  }, [undoLastExchange, sendMessage]);

  return {
    messages,
    isExecuting,
    isLoadingHistory,
    currentTaskId: agentTaskIdRef.current,
    sendMessage,
    stopExecution,
    handleApproval,
    clearMessages,
    undoLastExchange,
    retryLastMessage,
  };
}
