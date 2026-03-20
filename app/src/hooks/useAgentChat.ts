import { useState, useRef, useEffect, useCallback } from 'react';
import { chatApi } from '../lib/api';
import type { AgentMessageData, DBMessage, SerializedAttachment } from '../types/agent';
import type { ChatAgent } from '../types/chat';
import type { EditMode } from '../components/chat/EditModeStatus';

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
}

export function useAgentChat({
  chatId,
  projectId,
  agent,
  editMode,
  onTitleGenerated,
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

  useEffect(() => {
    editModeRef.current = editMode;
  }, [editMode]);

  useEffect(() => {
    onTitleGeneratedRef.current = onTitleGenerated;
  }, [onTitleGenerated]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => { isMountedRef.current = false; };
  }, []);

  // Load chat history when chatId changes
  useEffect(() => {
    if (!chatId) {
      setMessages([]);
      return;
    }

    // Skip history load if we're mid-execution (e.g. just created a session
    // and immediately sent a message — the user message is already in state)
    if (isExecutingRef.current) return;

    let cancelled = false;

    const loadHistory = async () => {
      setIsLoadingHistory(true);
      try {
        const dbMessages = await chatApi.getStandaloneMessages(chatId);

        if (cancelled) return;

        const expandedMessages: ChatMessage[] = [];
        dbMessages.forEach((msg, idx) => {
          const messageType = msg.role === 'assistant' ? 'ai' : 'user';
          if (messageType === 'user' || !msg.message_metadata?.agent_mode) {
            if (msg.content && msg.content.trim()) {
              expandedMessages.push({
                id: `msg-${idx}`,
                type: messageType,
                content: msg.content,
                attachments: msg.message_metadata?.attachments as SerializedAttachment[] | undefined,
              });
            }
            return;
          }

          const finalResponse = msg.content && msg.content.trim() ? msg.content : '';

          if (msg.message_metadata.steps && msg.message_metadata.steps.length > 0) {
            msg.message_metadata.steps.forEach((step: Record<string, unknown>, stepIdx: number) => {
              const hasContent =
                (step.tool_calls && (step.tool_calls as unknown[]).length > 0) ||
                (step.thought && (step.thought as string).trim());
              if (!hasContent) return;

              expandedMessages.push({
                id: `msg-${idx}-step-${stepIdx}`,
                type: 'ai',
                content: '',
                agentData: {
                  steps: [step],
                  iterations: (step.iteration as number) || stepIdx + 1,
                  tool_calls_made: (step.tool_calls as unknown[])?.length || 0,
                  completion_reason: 'step_complete',
                } as AgentMessageData,
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
      } catch (err) {
        console.error('[CHAT] Failed to load history:', err);
        if (!cancelled) setMessages([]);
      } finally {
        if (!cancelled) setIsLoadingHistory(false);
      }
    };

    loadHistory();

    return () => { cancelled = true; };
  }, [chatId, projectId]);

  const sendMessage = useCallback(async (message: string, overrideChatId?: string, attachments?: SerializedAttachment[]) => {
    const effectiveChatId = overrideChatId || chatId;
    if ((!message.trim() && (!attachments || attachments.length === 0)) || isExecuting || !effectiveChatId) return;

    const userMessage: ChatMessage = {
      id: `msg-${Date.now()}`,
      type: 'user',
      content: message,
      attachments,
    };
    setMessages((prev) => [...prev, userMessage]);
    isExecutingRef.current = true;
    setIsExecuting(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    const thinkingMessageId = `msg-${Date.now()}-thinking`;
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

          if (event.type === 'agent_step') {
            const transformedStep = {
              ...event.data,
              tool_calls:
                (event.data.tool_calls as Array<{ name: string; parameters: unknown }>)?.map(
                  (tc: { name: string; parameters: unknown }, index: number) => ({
                    name: tc.name,
                    parameters: tc.parameters,
                    result: (event.data.tool_results as unknown[])?.[index] || {},
                  })
                ) || [],
            };
            delete transformedStep.tool_results;

            const stepMessage: ChatMessage = {
              id: `msg-${Date.now()}-step-${event.data.iteration}`,
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
              return [
                ...withoutThinking,
                stepMessage,
                { ...thinkingMessage, id: thinkingMessageId },
              ];
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
                    id: `msg-${Date.now()}-error`,
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
                      id: `msg-${Date.now()}-result`,
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
          } else if (event.type === 'approval_required') {
            if (editModeRef.current === 'allow') {
              chatApi
                .sendApprovalResponse(event.data.approval_id as string, 'allow_all')
                .catch((err) => console.error('[APPROVAL] Auto-approve failed:', err));
            } else {
              const approvalMessage: ChatMessage = {
                id: `approval-${Date.now()}`,
                type: 'approval_request',
                content: '',
                approvalId: event.data.approval_id as string,
                toolName: event.data.tool_name as string,
                toolParameters: event.data.tool_parameters as Record<string, unknown>,
                toolDescription: event.data.tool_description as string,
              };
              setMessages((prev) => [...prev, approvalMessage]);
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
            id: `msg-${Date.now()}-error`,
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
  }, [chatId, projectId, agent, isExecuting]);

  const stopExecution = useCallback(async () => {
    const controller = abortControllerRef.current;
    if (controller) {
      controller.abort();
      abortControllerRef.current = null;
    }
    const taskId = agentTaskIdRef.current;
    if (taskId) {
      try { await chatApi.cancelAgentTask(taskId); } catch { /* best effort */ }
      agentTaskIdRef.current = null;
    }
    isExecutingRef.current = false;
    setIsExecuting(false);
  }, []);

  const handleApproval = useCallback(async (
    approvalId: string,
    response: 'allow_once' | 'allow_all' | 'stop',
  ) => {
    try {
      await chatApi.sendApprovalResponse(approvalId, response);
    } catch (err) {
      console.error('[APPROVAL] Failed to send response:', err);
    }
    setMessages((prev) =>
      prev.filter((msg) => !(msg.type === 'approval_request' && msg.approvalId === approvalId))
    );
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  return {
    messages,
    isExecuting,
    isLoadingHistory,
    currentTaskId: agentTaskIdRef.current,
    sendMessage,
    stopExecution,
    handleApproval,
    clearMessages,
  };
}
