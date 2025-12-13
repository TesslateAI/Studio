import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, FileCode, X } from 'lucide-react';
import { PencilSimple, Storefront, Books } from '@phosphor-icons/react';
import { ChatMessage } from './ChatMessage';
import { ChatInput } from './ChatInput';
import { EditModeStatus, type EditMode } from './EditModeStatus';
import { ApprovalRequestCard } from './ApprovalRequestCard';
import { createWebSocket, chatApi } from '../../lib/api';
import toast from 'react-hot-toast';
import AgentMessage from '../AgentMessage';
import { type AgentMessageData, type DBMessage } from '../../types/agent';

interface Agent {
  id: string;
  name: string;
  icon: string;  // Emoji string from backend
  avatar_url?: string;  // Uploaded logo URL
  active?: boolean;
  backendId?: number;  // Link to backend agent ID
  mode?: 'stream' | 'agent';
}

interface Message {
  id: string;
  type: 'user' | 'ai' | 'approval_request';
  content: string;
  agentData?: AgentMessageData;
  agentIcon?: string;
  agentAvatarUrl?: string;
  agentType?: string;
  toolCalls?: Array<{
    name: string;
    description: string;
  }>;
  actions?: Array<{
    label: string;
    onClick: () => void;
  }>;
  // Approval-specific fields
  approvalId?: string;
  toolName?: string;
  toolParameters?: any;
  toolDescription?: string;
}

interface StreamingFile {
  fileName: string;
  isStreaming: boolean;
}

interface ProjectFile {
  file_path: string;
  content: string;
}

interface ChatContainerProps {
  projectId: number;
  containerId?: string;  // Container ID for container-scoped agents
  agents: Agent[];
  currentAgent: Agent;
  onSelectAgent: (agent: Agent) => void;
  onFileUpdate: (filePath: string, content: string) => void;
  projectFiles?: ProjectFile[];
  projectName?: string;
  className?: string;
  sidebarExpanded?: boolean;
  containerId?: string;  // Container ID for multi-container projects
}

export function ChatContainer({
  projectId,
  containerId,
  agents: initialAgents,
  currentAgent: initialCurrentAgent,
  onSelectAgent,
  onFileUpdate,
  projectFiles = [],
  projectName = 'project',
  className = '',
  sidebarExpanded = true,
}: ChatContainerProps) {
  const navigate = useNavigate();
  const [isExpanded, setIsExpanded] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [agents, setAgents] = useState<Agent[]>(initialAgents);
  const [currentAgent, setCurrentAgent] = useState<Agent>(initialCurrentAgent);
  const [editMode, setEditMode] = useState<EditMode>('ask');
  const [isStreaming, setIsStreaming] = useState(false);
  const [agentExecuting, setAgentExecuting] = useState(false);
  const [currentStream, setCurrentStream] = useState('');
  const [streamingFiles, setStreamingFiles] = useState<Map<string, StreamingFile>>(new Map());
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isDesktop, setIsDesktop] = useState(window.innerWidth >= 768);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const isUserScrollingRef = useRef(false);
  const previousMessageCountRef = useRef(0);
  const animatedMessagesRef = useRef<Set<string>>(new Set());

  // Load chat history from database
  useEffect(() => {
    const loadChatHistory = async () => {
      setIsLoadingHistory(true);
      try {
        const dbMessages: DBMessage[] = await chatApi.getProjectMessages(projectId.toString());

        const expandedMessages: Message[] = [];

        dbMessages.forEach((msg, idx) => {
          // Map 'assistant' role to 'ai' type for frontend
          const messageType = msg.role === 'assistant' ? 'ai' : 'user';

          // For user messages or non-agent assistant messages, add as-is
          // Skip messages with empty content to prevent empty chat bubbles
          if (messageType === 'user' || !msg.message_metadata?.agent_mode) {
            if (msg.content && msg.content.trim()) {
              expandedMessages.push({
                id: `msg-${idx}`,
                type: messageType,
                content: msg.content
              });
            }
            return;
          }

          // For agent messages, split iterations into separate messages
          // Find agent icon from initialAgents if available
          const agentData = initialAgents.length > 0
            ? initialAgents.find(a => a.name === msg.message_metadata?.agent_type)
            : null;
          const agentIcon = agentData?.icon || '🤖'; // Fallback icon if agents not loaded yet
          const agentType = msg.message_metadata.agent_type;
          const finalResponse = msg.content && msg.content.trim() ? msg.content : '';

          // Add each step as a separate message (filter out steps with no content)
          if (msg.message_metadata.steps && msg.message_metadata.steps.length > 0) {
            msg.message_metadata.steps.forEach((step, stepIdx) => {
              // Only add steps that have tool calls or thoughts (match AgentMessage filtering)
              const hasContent = (step.tool_calls && step.tool_calls.length > 0) || (step.thought && step.thought.trim());
              if (!hasContent) return;

              expandedMessages.push({
                id: `msg-${idx}-step-${stepIdx}`,
                type: 'ai',
                content: '', // Don't include final response in steps
                agentData: {
                  steps: [step],
                  iterations: step.iteration || stepIdx + 1,
                  tool_calls_made: step.tool_calls?.length || 0,
                  completion_reason: 'step_complete'
                },
                agentIcon,
                agentType
              });
            });

            // Always add final response as a separate message if it exists
            if (finalResponse) {
              expandedMessages.push({
                id: `msg-${idx}-final`,
                type: 'ai',
                content: finalResponse,
                agentData: {
                  steps: [],
                  iterations: 0,
                  tool_calls_made: 0,
                  completion_reason: 'complete'
                },
                agentIcon,
                agentType
              });
            }
          } else if (finalResponse) {
            // If no steps but has final response, create a message with empty agentData
            expandedMessages.push({
              id: `msg-${idx}-result`,
              type: 'ai',
              content: finalResponse,
              agentData: {
                steps: [],
                iterations: 0,
                tool_calls_made: 0,
                completion_reason: 'complete'
              },
              agentIcon,
              agentType
            });
          }
        });

        setMessages(expandedMessages);
      } catch (error) {
        console.error('[CHAT] Failed to load chat history:', error);
        setMessages([]);
      } finally {
        setIsLoadingHistory(false);
      }
    };

    loadChatHistory();
  }, [projectId, initialAgents]);

  // Update agents when initialAgents prop changes
  useEffect(() => {
    if (initialAgents.length > 0) {
      setAgents(initialAgents);

      // Set first agent as default if current agent not in list
      if (!initialAgents.find(a => a.id === currentAgent.id)) {
        const defaultAgent = initialAgents[0];
        setCurrentAgent(defaultAgent);
        onSelectAgent(defaultAgent);
      }
    }
  }, [initialAgents, currentAgent.id, onSelectAgent]);

  // WebSocket connection with auto-reconnect and heartbeat
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) return;

    let ws: WebSocket | null = null;
    let isCleaningUp = false;
    let reconnectAttempts = 0;
    let reconnectTimer: NodeJS.Timeout | null = null;
    let heartbeatTimer: NodeJS.Timeout | null = null;
    const maxReconnectAttempts = 10;
    const baseReconnectDelay = 1000;
    const heartbeatInterval = 30000; // 30 seconds

    const startHeartbeat = () => {
      if (heartbeatTimer) {
        clearInterval(heartbeatTimer);
      }

      heartbeatTimer = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          try {
            ws.send(JSON.stringify({ type: 'ping', project_id: projectId }));
            console.log('[WS] Heartbeat ping sent');
          } catch (error) {
            console.error('[WS] Heartbeat error:', error);
          }
        }
      }, heartbeatInterval);
    };

    const stopHeartbeat = () => {
      if (heartbeatTimer) {
        clearInterval(heartbeatTimer);
        heartbeatTimer = null;
      }
    };

    const connectWebSocket = () => {
      if (isCleaningUp) return;

      if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
        wsRef.current.close();
      }

      try {
        ws = createWebSocket(token);
        wsRef.current = ws;

        ws.onopen = () => {
          if (isCleaningUp) return;

          console.log('[WS] WebSocket connected');
          reconnectAttempts = 0;
          startHeartbeat();
        };

        ws.onmessage = (event) => {
          if (isCleaningUp) return;

          const data = JSON.parse(event.data);

          // Handle pong response
          if (data.type === 'pong') {
            console.log('[WS] Heartbeat pong received');
            return;
          }

          console.log('[WS] Message:', data.type);

          if (data.type === 'stream') {
            setCurrentStream(prev => prev + data.content);

            // Extract file names from code blocks
            const codeBlockPattern = /```\w+\s*\n\/\/\s*File:\s*([^\n]+)/g;
            let match;
            while ((match = codeBlockPattern.exec(data.content)) !== null) {
              const fileName = match[1].trim();
              setStreamingFiles(prev => new Map(prev).set(fileName, { fileName, isStreaming: true }));
            }
          } else if (data.type === 'complete') {
            // Handle complete event from both StreamAgent and IterativeAgent
            const finalResponse = data.data?.final_response || data.content || currentStream;

            setMessages(prev => [...prev, {
              id: `msg-${Date.now()}`,
              type: 'ai',
              content: finalResponse
            }]);
            setCurrentStream('');
            setIsStreaming(false);
            setStreamingFiles(prev => {
              const newMap = new Map(prev);
              newMap.forEach((file, key) => {
                newMap.set(key, { ...file, isStreaming: false });
              });
              return newMap;
            });
          } else if (data.type === 'file_ready') {
            onFileUpdate(data.file_path, data.content);
            toast.success(`Created ${data.file_path}`, { duration: 2000 });

            const fileName = data.file_path.replace(/^src\//, '');
            setStreamingFiles(prev => {
              const newMap = new Map(prev);
              if (newMap.has(fileName)) {
                newMap.set(fileName, { fileName, isStreaming: false });
              }
              return newMap;
            });
          } else if (data.type === 'error') {
            toast.error(data.content);
            setIsStreaming(false);
            setCurrentStream('');
            setStreamingFiles(prev => {
              const newMap = new Map(prev);
              newMap.forEach((file, key) => {
                newMap.set(key, { ...file, isStreaming: false });
              });
              return newMap;
            });
          } else if (data.type === 'approval_required') {
            // Handle approval request - add approval message to chat
            const approvalMessage: Message = {
              id: `approval-${Date.now()}`,
              type: 'approval_request',
              content: '',
              approvalId: data.data.approval_id,
              toolName: data.data.tool_name,
              toolParameters: data.data.tool_parameters,
              toolDescription: data.data.tool_description,
            };
            setMessages(prev => [...prev, approvalMessage]);
          }
        };

        ws.onerror = (error) => {
          if (!isCleaningUp) {
            console.error('[WS] WebSocket error:', error);
          }
        };

        ws.onclose = () => {
          if (isCleaningUp) return;

          console.log('[WS] WebSocket disconnected');
          stopHeartbeat();

          // Attempt to reconnect with exponential backoff
          if (reconnectAttempts < maxReconnectAttempts) {
            const delay = Math.min(baseReconnectDelay * Math.pow(2, reconnectAttempts), 30000);
            reconnectAttempts++;

            console.log(`[WS] Reconnecting in ${delay}ms (attempt ${reconnectAttempts}/${maxReconnectAttempts})`);

            reconnectTimer = setTimeout(() => {
              connectWebSocket();
            }, delay);
          } else {
            console.error('[WS] Max reconnect attempts reached');
            toast.error('Connection lost. Please refresh the page.', { duration: 5000 });
          }
        };
      } catch (error) {
        console.error('[WS] Failed to create WebSocket:', error);
      }
    };

    connectWebSocket();

    return () => {
      isCleaningUp = true;
      stopHeartbeat();

      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }

      if (ws && ws.readyState !== WebSocket.CLOSED) {
        ws.close();
      }
    };
    // Only reconnect when projectId changes, not when onFileUpdate changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Track desktop/mobile state
  useEffect(() => {
    const handleResize = () => {
      setIsDesktop(window.innerWidth >= 768);
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Track user scroll behavior
  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;

      // User is scrolling up if not near bottom
      isUserScrollingRef.current = !isNearBottom;
    };

    container.addEventListener('scroll', handleScroll);
    return () => container.removeEventListener('scroll', handleScroll);
  }, []);

  // Smart auto-scroll: only scroll if user hasn't manually scrolled up
  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!isExpanded || !container || !messagesEndRef.current) return;

    const { scrollTop, scrollHeight, clientHeight } = container;
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;

    // Only auto-scroll if:
    // 1. User hasn't manually scrolled up (isUserScrollingRef is false)
    // 2. OR user is already near the bottom
    // 3. OR this is a new user message (messages array grew and last message is user type)
    const lastMessage = messages[messages.length - 1];
    const isNewUserMessage = lastMessage?.type === 'user';

    if (isNewUserMessage || !isUserScrollingRef.current || isNearBottom) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
      isUserScrollingRef.current = false; // Reset after scrolling
    }
  }, [messages, currentStream, isExpanded]);

  // Collapse chat when clicking outside (including clicks on iframe/preview) - desktop only
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      // Only auto-close on desktop (md breakpoint is 768px)
      if (window.innerWidth >= 768 && containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsExpanded(false);
      }
    };

    const handleWindowBlur = () => {
      // Close chat when clicking on iframe (preview window) - desktop only
      if (window.innerWidth >= 768) {
        setTimeout(() => {
          if (document.activeElement?.tagName === 'IFRAME' && isExpanded) {
            setIsExpanded(false);
          }
        }, 0);
      }
    };

    if (isExpanded) {
      document.addEventListener('mousedown', handleClickOutside);
      window.addEventListener('blur', handleWindowBlur);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
        window.removeEventListener('blur', handleWindowBlur);
      };
    }
  }, [isExpanded]);

  const handleInputFocus = () => {
    setIsExpanded(true);
  };

  const handleAgentSelect = (agent: Agent) => {
    setCurrentAgent(agent);
    onSelectAgent(agent);
  };

  const sendStreamMessage = (message: string) => {
    if (!message.trim() || !wsRef.current || isStreaming) return;

    const userMessage: Message = {
      id: `msg-${Date.now()}`,
      type: 'user',
      content: message
    };
    setMessages(prev => [...prev, userMessage]);
    setIsStreaming(true);
    setStreamingFiles(new Map());

    wsRef.current.send(JSON.stringify({
      message,
      project_id: projectId,
      container_id: containerId,  // Container ID for scoped file access
      agent_id: currentAgent.backendId,  // Include agent_id
      edit_mode: editMode  // Include edit mode
    }));
  };

  const [abortController, setAbortController] = useState<AbortController | null>(null);
  const escPressCountRef = useRef(0);
  const escTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const stopAgentExecution = useCallback(() => {
    if (abortController) {
      abortController.abort();
      setAbortController(null);
      setAgentExecuting(false);
    }
  }, [abortController]);

  // ESC key handler for stopping execution
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && agentExecuting) {
        escPressCountRef.current += 1;
        const newCount = escPressCountRef.current;

        // Clear previous timeout
        if (escTimeoutRef.current) {
          clearTimeout(escTimeoutRef.current);
        }

        // Reset count after 500ms
        escTimeoutRef.current = setTimeout(() => {
          escPressCountRef.current = 0;
        }, 500);

        // Stop execution on double ESC
        if (newCount >= 2) {
          stopAgentExecution();
          escPressCountRef.current = 0;
          toast.success('Agent stopped (ESC pressed twice)');
        } else {
          toast('Press ESC again to stop agent', { duration: 500 });
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      if (escTimeoutRef.current) {
        clearTimeout(escTimeoutRef.current);
      }
    };
  }, [agentExecuting, stopAgentExecution]);


  const sendAgentMessage = async (message: string) => {
    if (!message.trim() || agentExecuting) return;

    const userMessage: Message = {
      id: `msg-${Date.now()}`,
      type: 'user',
      content: message
    };
    setMessages(prev => [...prev, userMessage]);
    setAgentExecuting(true);

    // Create abort controller
    const controller = new AbortController();
    setAbortController(controller);

    // Create initial "thinking" message
    const thinkingMessageId = `msg-${Date.now()}-thinking`;
    const thinkingMessage: Message = {
      id: thinkingMessageId,
      type: 'ai',
      content: '',
      agentData: {
        steps: [],
        iterations: 0,
        tool_calls_made: 0,
        completion_reason: 'in_progress',
      },
      agentIcon: currentAgent.icon,
      agentAvatarUrl: currentAgent.avatar_url,
      agentType: currentAgent.name,
    };
    setMessages(prev => [...prev, thinkingMessage]);

    try {
      await chatApi.sendAgentMessageStreaming(
        {
          project_id: projectId.toString(),
          container_id: containerId,  // Container ID for scoped file access
          message,
          agent_id: currentAgent.backendId?.toString(),
          container_id: containerId,
          max_iterations: 20,
          edit_mode: editMode,
        },
        (event) => {
          if (event.type === 'agent_step') {
            // Transform tool_results array to match HTTP format
            const transformedStep = {
              ...event.data,
              tool_calls: event.data.tool_calls?.map((tc: { name: string; parameters: unknown }, index: number) => ({
                name: tc.name,
                parameters: tc.parameters,
                result: event.data.tool_results?.[index] || {}
              })) || []
            };
            delete transformedStep.tool_results;

            // Create a new message for this step
            const stepMessage: Message = {
              id: `msg-${Date.now()}-step-${event.data.iteration}`,
              type: 'ai',
              content: '',
              agentData: {
                steps: [transformedStep],
                iterations: event.data.iteration || 0,
                tool_calls_made: event.data.tool_calls?.length || 0,
                completion_reason: 'step_complete',
              },
              agentIcon: currentAgent.icon,
              agentAvatarUrl: currentAgent.avatar_url,
              agentType: currentAgent.name,
            };

            // Remove thinking message, add step message, and re-add thinking message in one update
            setMessages(prev => {
              const withoutThinking = prev.filter(msg => msg.id !== thinkingMessageId);
              return [...withoutThinking, stepMessage, { ...thinkingMessage, id: thinkingMessageId }];
            });
          } else if (event.type === 'complete') {
            // Remove thinking message
            setMessages(prev => prev.filter(msg => msg.id !== thinkingMessageId));

            // Add final response as part of AgentMessage (not a separate message)
            const finalContent = event.data.final_response;
            if (finalContent && finalContent.trim()) {
              // Update the last agent message to include the final response
              setMessages(prev => {
                const lastMsg = prev[prev.length - 1];
                if (lastMsg && lastMsg.agentData) {
                  return [
                    ...prev.slice(0, -1),
                    {
                      ...lastMsg,
                      content: finalContent,
                    }
                  ];
                }
                // Fallback: if no agent message exists, create one
                return [...prev, {
                  id: `msg-${Date.now()}-result`,
                  type: 'ai',
                  content: finalContent,
                  agentData: {
                    steps: [],
                    iterations: 0,
                    tool_calls_made: 0,
                    completion_reason: 'complete',
                  },
                  agentIcon: currentAgent.icon,
                  agentAvatarUrl: currentAgent.avatar_url,
                  agentType: currentAgent.name,
                }];
              });
            }

            toast.success('Task completed successfully');
          } else if (event.type === 'error') {
            const errorMsg = (event as any).content || event.data?.message || 'Agent execution failed';
            throw new Error(errorMsg);
          } else if (event.type === 'approval_required') {
            // Handle approval request - add approval message to chat
            const approvalMessage: Message = {
              id: `approval-${Date.now()}`,
              type: 'approval_request',
              content: '',
              approvalId: event.data.approval_id,
              toolName: event.data.tool_name,
              toolParameters: event.data.tool_parameters,
              toolDescription: event.data.tool_description,
            };
            setMessages(prev => [...prev, approvalMessage]);
          }
        },
        controller.signal
      );
    } catch (error: unknown) {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('[AGENT] Execution aborted by user');

        // Remove thinking message and add stopped message
        setMessages(prev => {
          const withoutThinking = prev.filter(msg => msg.id !== thinkingMessageId);
          return [...withoutThinking, {
            id: `msg-${Date.now()}-stopped`,
            type: 'ai',
            content: '_[Execution stopped by user]_',
          }];
        });

        return;
      }

      console.error('[AGENT] Streaming execution error:', error);

      // Remove thinking message and add error message
      setMessages(prev => {
        const withoutThinking = prev.filter(msg => msg.id !== thinkingMessageId);
        return [...withoutThinking, {
          id: `msg-${Date.now()}-error`,
          type: 'ai',
          content: "I apologize, but I encountered an error while working on your request. The task could not be completed. Please try again or contact support if the issue persists.",
        }];
      });

      const errorDetail = error instanceof Error ? error.message : 'Failed to execute agent';
      toast.error(errorDetail, {
        duration: 5000,
      });
    } finally {
      setAgentExecuting(false);
      setAbortController(null);
    }
  };

  const handleSendMessage = (message: string) => {
    // Use agent's mode to determine stream vs agent execution
    if (currentAgent.mode === 'agent') {
      sendAgentMessage(message);
    } else {
      sendStreamMessage(message);
    }
  };

  const handleClearHistory = async () => {
    try {
      const result = await chatApi.clearProjectMessages(projectId.toString());
      setMessages([]);
      animatedMessagesRef.current.clear();
      toast.success(`Cleared ${result.deleted_count} messages`, { icon: '🗑️' });
    } catch (error) {
      console.error('[CHAT] Failed to clear history:', error);
      toast.error('Failed to clear chat history');
    }
  };

  const handleApprovalResponse = async (approvalId: string, response: 'allow_once' | 'allow_all' | 'stop', toolName: string) => {
    // Define write tools that should switch mode
    const WRITE_TOOLS = new Set(['write_file', 'patch_file', 'multi_edit']);

    // Send approval response via WebSocket (for stream mode)
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'approval_response',
        approval_id: approvalId,
        response: response
      }));
    } else if (agentExecuting) {
      // Send approval response via HTTP API (for SSE agent mode)
      try {
        await chatApi.sendApprovalResponse(approvalId, response);
        console.log('[APPROVAL] Response sent via HTTP API');
      } catch (error) {
        console.error('[APPROVAL] Failed to send response:', error);
        toast.error('Failed to send approval response');
        return;
      }
    }

    // Remove approval message from chat
    setMessages(prev => prev.filter(msg =>
      !(msg.type === 'approval_request' && msg.approvalId === approvalId)
    ));

    // Handle mode switching for write tools
    if (response === 'allow_all' && WRITE_TOOLS.has(toolName)) {
      // Switch to "Allow All Edits" mode
      setEditMode('allow');
      toast.success('Switched to "Allow All Edits" mode');
    } else if (response === 'allow_once') {
      toast.success('Approved this operation');
    } else if (response === 'allow_all') {
      toast.success('Approved all operations of this type for this session');
    } else {
      toast.error('Operation cancelled');
    }
  };

  const renderMessageContent = (content: string, isCurrentlyStreaming: boolean = false) => {
    // Safety check: handle undefined/null content
    if (!content) {
      return <span className="text-gray-400 italic">No content available</span>;
    }

    let processedContent = content;

    if (isCurrentlyStreaming) {
      processedContent = processedContent.replace(/```\w+\s*\n\/\/\s*File:\s*([^\n]+)[\s\S]*?```/g, (match, fileName) => {
        return `[FILE: ${fileName.trim()}]`;
      });
      processedContent = processedContent.replace(/```\w+\s*\n\/\/\s*File:\s*([^\n]+)[\s\S]*$/g, (match, fileName) => {
        return `[FILE: ${fileName.trim()}]`;
      });
    } else {
      processedContent = processedContent.replace(/```[\s\S]*?```/g, (match) => {
        const fileMatch = match.match(/```\w+\s*\n\/\/\s*File:\s*([^\n]+)/);
        if (fileMatch) {
          return `[FILE: ${fileMatch[1].trim()}]`;
        }
        return '';
      });
    }

    const parts = processedContent.split(/\[FILE: ([^\]]+)\]/g);

    return parts.map((part, index) => {
      if (index % 2 === 0) {
        return <span key={index}>{part}</span>;
      } else {
        const fileName = part;
        const fileInfo = streamingFiles.get(fileName);
        const isFileStreaming = isCurrentlyStreaming && (!fileInfo || fileInfo.isStreaming !== false);

        return (
          <div key={index} className="my-2">
            <div className="flex items-center gap-2 p-3 bg-[var(--surface)]/50 rounded-lg border border-[var(--border-color)]">
              <FileCode size={18} className="text-[var(--primary)]" />
              <span className="text-sm font-medium flex-1">{fileName}</span>
              {isFileStreaming && (
                <Loader2 className="animate-spin text-[var(--primary)]" size={16} />
              )}
              {!isFileStreaming && (
                <div className="w-4 h-4 rounded-full bg-green-500 flex items-center justify-center">
                  <div className="w-2 h-2 bg-white rounded-full" />
                </div>
              )}
            </div>
          </div>
        );
      }
    });
  };

  return (
    <>
      {/* Mobile: Floating chat button - only show when collapsed */}
      <div className="md:hidden fixed bottom-20 right-4 z-30 group">
        <button
          onClick={() => setIsExpanded(true)}
          className={`
            w-12 h-12 md:w-16 md:h-16 rounded-full
            bg-[var(--primary)] hover:bg-[var(--primary-hover)] active:bg-[var(--primary-hover)]
            shadow-lg hover:shadow-xl
            flex items-center justify-center
            transition-all duration-300
            hover:scale-110
            ${isExpanded ? 'opacity-0 pointer-events-none scale-0' : 'opacity-100 scale-100'}
          `}
          aria-label="Open chat"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="16" viewBox="0 0 161.9 126.66" className="text-white md:w-6 md:h-6" fill="currentColor">
            <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z"/>
            <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z"/>
            <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z"/>
          </svg>

          {/* Hover tooltip */}
          <div className="
            absolute bottom-full mb-2 right-0
            bg-gray-900 text-white text-sm
            px-3 py-2 rounded-lg
            whitespace-nowrap
            opacity-0 group-hover:opacity-100
            transition-opacity duration-200
            pointer-events-none
          ">
            Open chat
          </div>
        </button>
      </div>

      {/* Chat container - 60-30-10: 60% bg-dark (dominant), 30% surface/borders (secondary), 10% orange accents */}
      <div
        ref={containerRef}
        className={`
          chat-container
          fixed
          z-40
          flex flex-col
          bg-[var(--bg-dark)]
          backdrop-blur-xl saturate-180
          border-2 border-[var(--surface)]
          shadow-2xl
          transition-all duration-400 ease-[var(--ease)]
          rounded-3xl
          max-md:bottom-0 max-md:left-0 max-md:right-0 max-md:rounded-b-none max-md:w-full
          md:bottom-6 md:-translate-x-1/2
          ${isExpanded
            ? 'md:w-[min(800px,calc(100vw-48px))] md:max-h-[calc(100vh-48px)] max-md:max-h-[90vh] max-md:translate-y-0'
            : 'md:w-[min(600px,calc(100vw-48px))] max-md:translate-y-full max-md:opacity-0 max-md:pointer-events-none'
          }
          ${!isExpanded && isHovered ? 'md:w-[min(650px,calc(100vw-48px))]' : ''}
          ${className}
        `}
        style={isDesktop ? {
          left: sidebarExpanded ? 'calc(96px + 50vw)' : 'calc(24px + 50vw)',
          transition: 'left 0.4s cubic-bezier(0.34, 1.56, 0.64, 1), width 0.4s var(--ease), max-height 0.4s var(--ease)'
        } : {
          transition: 'width 0.4s var(--ease), max-height 0.4s var(--ease), transform 0.4s var(--ease)'
        }}
        onMouseEnter={() => !isExpanded && setIsHovered(true)}
        onMouseLeave={() => !isExpanded && setIsHovered(false)}
      >
      {/* Glow effects */}
      <div
        className={`
          chat-glow glow-top
          absolute -top-0.5 -right-0.5
          w-3/5 h-3/5
          bg-[radial-gradient(circle_at_top_right,hsl(var(--hue1)_80%_60%_/_0.3)_0%,transparent_70%)]
          blur-xl
          pointer-events-none
          rounded-inherit
          transition-opacity duration-400
          ${isExpanded || isHovered ? 'opacity-100' : 'opacity-0'}
        `}
        style={{ zIndex: -1 }}
      />
      <div
        className={`
          chat-glow glow-bottom
          absolute -bottom-0.5 -left-0.5
          w-3/5 h-3/5
          bg-[radial-gradient(circle_at_bottom_left,hsl(var(--hue2)_80%_60%_/_0.3)_0%,transparent_70%)]
          blur-xl
          pointer-events-none
          rounded-inherit
          transition-opacity duration-400
          ${isExpanded || isHovered ? 'opacity-100' : 'opacity-0'}
        `}
        style={{ zIndex: -1 }}
      />

      {/* Mobile header with close button - 30% secondary surface */}
      <div className="md:hidden flex items-center justify-between px-4 py-3 border-b-2 border-[var(--surface)] bg-[var(--surface)]/30">
        <h3 className="text-sm font-semibold text-[var(--text)]">Chat</h3>
        <button
          onClick={() => setIsExpanded(false)}
          className="p-2 hover:bg-[var(--primary)]/10 rounded-lg transition-colors -mr-2"
          aria-label="Close chat"
        >
          <X size={20} className="text-[var(--text)]/60 hover:text-[var(--primary)]" />
        </button>
      </div>

      {/* Chat messages - only shown when expanded */}
      <div
        ref={messagesContainerRef}
        className={`
          chat-messages
          flex-1 overflow-y-auto px-3
          transition-all duration-300
          ${isExpanded ? 'pointer-events-auto' : 'pointer-events-none'}
          ${isExpanded
            ? 'opacity-100 max-h-[calc(100vh-400px)] py-3'
            : 'opacity-0 max-h-0 py-0'
          }
        `}
      >
        {isLoadingHistory && (
          <div className="text-center text-[var(--text)]/60 mt-8 space-y-4">
            <div className="w-16 h-16 bg-[var(--surface)] rounded-2xl flex items-center justify-center mx-auto border-2 border-[var(--primary)]/20">
              <Loader2 className="animate-spin text-[var(--primary)]" size={32} />
            </div>
            <div className="space-y-2">
              <p className="text-sm max-w-xs mx-auto leading-relaxed">
                Loading chat history...
              </p>
            </div>
          </div>
        )}

        {!isLoadingHistory && messages.length === 0 && !isStreaming && (
          <div className="text-center text-[var(--text)]/60 mt-8 space-y-6 max-w-md mx-auto px-4">
            <div className="w-16 h-16 bg-[var(--surface)] rounded-2xl flex items-center justify-center mx-auto border-2 border-[var(--primary)]/20">
              <svg xmlns="http://www.w3.org/2000/svg" width="32" height="25" viewBox="0 0 161.9 126.66" className="text-[var(--primary)]">
                <g>
                  <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor" strokeWidth="0"/>
                  <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor" strokeWidth="0"/>
                  <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor" strokeWidth="0"/>
                </g>
              </svg>
            </div>
            <div className="space-y-2">
              <p className="text-lg font-semibold text-[var(--text)]">Let's start building</p>
              <p className="text-sm leading-relaxed">
                Describe what you'd like to create and I'll help you build it step by step
              </p>
            </div>

            {/* Discovery Cards - 30% secondary background with 10% accent borders */}
            <div className="space-y-3 text-left">
              <div className="bg-[var(--surface)] rounded-lg p-3 border-2 border-[var(--border-color)]">
                <div className="flex items-center gap-2 mb-2">
                  <PencilSimple size={16} weight="bold" className="text-[var(--text)]/80" />
                  <span className="font-semibold text-sm text-[var(--text)]">Customize Your Agent</span>
                </div>
                <p className="text-xs text-[var(--text)]/70 mb-3">
                  Edit system prompts, behaviors, and settings to tailor {currentAgent.name} to your needs.
                </p>
                <button
                  onClick={() => {
                    navigate('/library', { state: { selectedAgentId: currentAgent.backendId } });
                  }}
                  className="w-full py-2 bg-[var(--text)]/5 hover:bg-[var(--text)]/10 border-2 border-[var(--border-color)] hover:border-[var(--text)]/20 rounded-lg text-[var(--text)] text-xs font-semibold transition-all"
                >
                  Open in Library
                </button>
              </div>

              <div className="bg-[var(--surface)] rounded-lg p-3 border-2 border-[var(--primary)]/30">
                <div className="flex items-center gap-2 mb-2">
                  <Storefront size={16} weight="fill" className="text-[var(--primary)]" />
                  <span className="font-semibold text-sm text-[var(--text)]">Discover More Agents</span>
                </div>
                <p className="text-xs text-[var(--text)]/70 mb-3">
                  Browse specialized agents for React, Vue, Python, DevOps, and more!
                </p>
                <button
                  onClick={() => {
                    navigate('/marketplace');
                  }}
                  className="w-full py-2 bg-[var(--primary)]/10 hover:bg-[var(--primary)]/20 rounded-lg text-[var(--primary)] text-xs font-semibold transition-all border-2 border-[var(--primary)]/40 hover:border-[var(--primary)]/60"
                >
                  Browse Marketplace
                </button>
              </div>
            </div>
          </div>
        )}

        {messages.map((message) => {
          // Check if this is a new message that should animate
          const isNewMessage = !animatedMessagesRef.current.has(message.id);
          if (isNewMessage && !isLoadingHistory) {
            animatedMessagesRef.current.add(message.id);
          }
          const shouldAnimate = isNewMessage && !isLoadingHistory;

          // Render approval request message
          if (message.type === 'approval_request' && message.approvalId) {
            return (
              <div
                key={message.id}
                className={`mb-4 ${shouldAnimate ? 'animate-[slideIn_0.2s_ease-out]' : ''}`}
              >
                <ApprovalRequestCard
                  approvalId={message.approvalId}
                  toolName={message.toolName || 'unknown'}
                  toolParameters={message.toolParameters}
                  toolDescription={message.toolDescription || 'No description provided'}
                  onRespond={handleApprovalResponse}
                />
              </div>
            );
          }

          // Render agent message with special component
          if (message.type === 'ai' && message.agentData) {
            return (
              <div
                key={message.id}
                className={`mb-4 ${shouldAnimate ? 'animate-[slideIn_0.2s_ease-out]' : ''}`}
              >
                <AgentMessage
                  agentData={message.agentData}
                  finalResponse={message.content}
                  agentIcon={message.agentIcon}
                  agentAvatarUrl={message.agentAvatarUrl}
                />
              </div>
            );
          }

          // Render regular messages
          return (
            <div
              key={message.id}
              className={shouldAnimate ? 'animate-[slideIn_0.2s_ease-out]' : ''}
            >
              <ChatMessage
                type={message.type as 'user' | 'ai'}
                content={message.content || ''}
                agentIcon={message.agentIcon}
                agentAvatarUrl={message.agentAvatarUrl}
                toolCalls={message.toolCalls}
                actions={message.actions}
              />
            </div>
          );
        })}

        {/* Streaming message */}
        {isStreaming && currentStream && (
          <div className="mb-4 animate-[slideIn_0.3s_ease-out]">
            <ChatMessage
              type="ai"
              content={renderMessageContent(currentStream, true)}
            />
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Chat input */}
      <div onFocus={handleInputFocus} className="pointer-events-auto">
        <ChatInput
          agents={agents}
          currentAgent={currentAgent}
          onSelectAgent={handleAgentSelect}
          onSendMessage={handleSendMessage}
          projectFiles={projectFiles}
          projectName={projectName}
          disabled={isStreaming || agentExecuting}
          isExecuting={agentExecuting}
          onStop={stopAgentExecution}
          onClearHistory={handleClearHistory}
          isExpanded={isExpanded}
          editMode={editMode}
          onModeChange={setEditMode}
          onPlanMode={() => setEditMode('plan')}
        />
      </div>
    </div>
    </>
  );
}
