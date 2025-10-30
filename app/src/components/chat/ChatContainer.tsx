import { useState, useRef, useEffect, type ReactNode } from 'react';
import { Loader2, FileCode } from 'lucide-react';
import { ChatMessage } from './ChatMessage';
import { ChatInput } from './ChatInput';
import { TypingIndicator } from './TypingIndicator';
import { createWebSocket, chatApi, agentsApi } from '../../lib/api';
import toast from 'react-hot-toast';
import AgentMessage from '../AgentMessage';
import { type AgentMessageData, type Agent as BackendAgent, type DBMessage } from '../../types/agent';

interface Agent {
  id: string;
  name: string;
  icon: ReactNode;
  active?: boolean;
  backendId?: number;  // Link to backend agent ID
  mode?: 'stream' | 'agent';
}

interface Message {
  id: string;
  type: 'user' | 'ai';
  content: string;
  agentData?: AgentMessageData;
  toolCalls?: Array<{
    name: string;
    description: string;
  }>;
  actions?: Array<{
    label: string;
    onClick: () => void;
  }>;
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
  agents: Agent[];
  currentAgent: Agent;
  onSelectAgent: (agent: Agent) => void;
  onFileUpdate: (filePath: string, content: string) => void;
  projectFiles?: ProjectFile[];
  projectName?: string;
  className?: string;
  initialMessage?: string;
}

export function ChatContainer({
  projectId,
  agents: initialAgents,
  currentAgent: initialCurrentAgent,
  onSelectAgent,
  onFileUpdate,
  projectFiles = [],
  projectName = 'project',
  className = '',
  initialMessage = ''
}: ChatContainerProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [backendAgents, setBackendAgents] = useState<BackendAgent[]>([]);
  const [agents, setAgents] = useState<Agent[]>(initialAgents);
  const [currentAgent, setCurrentAgent] = useState<Agent>(initialCurrentAgent);
  const [isStreaming, setIsStreaming] = useState(false);
  const [agentExecuting, setAgentExecuting] = useState(false);
  const [currentStream, setCurrentStream] = useState('');
  const [streamingFiles, setStreamingFiles] = useState<Map<string, StreamingFile>>(new Map());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Load chat history from database
  useEffect(() => {
    const loadChatHistory = async () => {
      try {
        const dbMessages: DBMessage[] = await chatApi.getProjectMessages(projectId);

        setMessages(dbMessages.map((msg, idx) => {
          // Map 'assistant' role to 'ai' type for frontend
          const messageType = msg.role === 'assistant' ? 'ai' : 'user';

          const message: Message = {
            id: `msg-${idx}`,
            type: messageType,
            content: msg.content
          };

          // Restore agent data from metadata if available
          if (msg.message_metadata?.agent_mode) {
            message.agentData = {
              steps: msg.message_metadata.steps || [],
              iterations: msg.message_metadata.iterations || 0,
              tool_calls_made: msg.message_metadata.tool_calls_made || 0,
              completion_reason: msg.message_metadata.completion_reason || 'unknown'
            };
          }

          return message;
        }));
      } catch (error) {
        console.error('[CHAT] Failed to load chat history:', error);
        setMessages([]);
      }
    };

    loadChatHistory();
  }, [projectId]);

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
  }, [initialAgents]);

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

  // Auto-scroll to latest message
  useEffect(() => {
    if (isExpanded && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, currentStream, isExpanded]);

  // Collapse chat when clicking outside (including clicks on iframe/preview)
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsExpanded(false);
      }
    };

    const handleWindowBlur = () => {
      // Close chat when clicking on iframe (preview window)
      // Small delay to ensure we're clicking on iframe, not just tabbing away
      setTimeout(() => {
        if (document.activeElement?.tagName === 'IFRAME' && isExpanded) {
          setIsExpanded(false);
        }
      }, 0);
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
      agent_id: currentAgent.backendId  // Include agent_id
    }));
  };

  const sendAgentMessage = async (message: string) => {
    if (!message.trim() || agentExecuting) return;

    const userMessage: Message = {
      id: `msg-${Date.now()}`,
      type: 'user',
      content: message
    };
    setMessages(prev => [...prev, userMessage]);
    setAgentExecuting(true);

    try {
      const response = await chatApi.sendAgentMessage({
        project_id: projectId,
        message,
        agent_id: currentAgent.backendId,  // Include agent_id for proper agent selection
        max_iterations: 20,
      });

      if (response.success) {
        const agentMessage: Message = {
          id: `msg-${Date.now()}`,
          type: 'ai',
          content: response.final_response,
          agentData: {
            steps: response.steps,
            iterations: response.iterations,
            tool_calls_made: response.tool_calls_made,
            completion_reason: response.completion_reason,
          },
        };
        setMessages(prev => [...prev, agentMessage]);
        toast.success('Task completed successfully');
      } else {
        // Agent execution failed - add error message to chat
        const errorMessage: Message = {
          id: `msg-${Date.now()}`,
          type: 'ai',
          content: "I apologize, but I encountered an error while working on your request. The task could not be completed. Please try again or contact support if the issue persists.",
        };
        setMessages(prev => [...prev, errorMessage]);

        // Show technical error in toast
        toast.error(response.error || 'Agent execution failed', {
          duration: 5000,
        });
      }
    } catch (error: any) {
      console.error('[AGENT] Execution error:', error);

      // Add error message to chat
      const errorMessage: Message = {
        id: `msg-${Date.now()}`,
        type: 'ai',
        content: "I apologize, but I encountered an error while working on your request. The task could not be completed. Please try again or contact support if the issue persists.",
      };
      setMessages(prev => [...prev, errorMessage]);

      // Show technical error in toast
      const detail = error?.response?.data?.detail;
      const errorDetail = typeof detail === 'string' ? detail : (error?.message || 'Failed to execute agent');
      toast.error(errorDetail, {
        duration: 5000,
      });
    } finally {
      setAgentExecuting(false);
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
              <FileCode size={18} className="text-orange-500" />
              <span className="text-sm font-medium flex-1">{fileName}</span>
              {isFileStreaming && (
                <Loader2 className="animate-spin text-orange-500" size={16} />
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

  const isTyping = isStreaming || agentExecuting;

  return (
    <div
      ref={containerRef}
      className={`
        chat-container
        fixed bottom-6 left-1/2 -translate-x-1/2
        z-[150]
        flex flex-col
        bg-[var(--surface)]/95
        backdrop-blur-xl saturate-180
        rounded-3xl
        border border-[var(--border-color)]
        shadow-2xl
        transition-all duration-400 ease-[var(--ease)]
        max-h-[calc(100vh-48px)]
        ${isExpanded
          ? 'w-[min(800px,calc(100vw-48px))]'
          : isHovered
          ? 'w-[min(650px,calc(100vw-48px))]'
          : 'w-[min(600px,calc(100vw-48px))]'
        }
        ${className}
      `}
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

      {/* Chat messages - only shown when expanded */}
      <div
        className={`
          chat-messages
          flex-1 overflow-y-auto px-5
          transition-all duration-300
          ${isExpanded ? 'pointer-events-auto' : 'pointer-events-none'}
          ${isExpanded
            ? 'opacity-100 max-h-[calc(100vh-400px)] py-5'
            : 'opacity-0 max-h-0 py-0'
          }
        `}
      >
        {messages.length === 0 && !isStreaming && (
          <div className="text-center text-[var(--text)]/60 mt-8 space-y-4">
            <div className="w-16 h-16 bg-gradient-to-br from-orange-500/20 to-orange-400/10 rounded-2xl flex items-center justify-center mx-auto">
              <svg xmlns="http://www.w3.org/2000/svg" width="32" height="25" viewBox="0 0 161.9 126.66" className="text-orange-500">
                <g>
                  <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor" strokeWidth="0"/>
                  <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor" strokeWidth="0"/>
                  <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor" strokeWidth="0"/>
                </g>
              </svg>
            </div>
            <div className="space-y-2">
              <p className="text-lg font-semibold">Let's start building</p>
              <p className="text-sm max-w-xs mx-auto leading-relaxed">
                Describe what you'd like to create and I'll help you build it step by step
              </p>
            </div>
          </div>
        )}

        {messages.map((message) => {
          // Render agent message with special component
          if (message.type === 'ai' && message.agentData) {
            return (
              <div key={message.id} className="mb-4">
                <AgentMessage
                  agentData={message.agentData}
                  finalResponse={message.content}
                />
              </div>
            );
          }

          // Render regular messages
          return (
            <ChatMessage
              key={message.id}
              type={message.type}
              content={renderMessageContent(message.content, false)}
              toolCalls={message.toolCalls}
              actions={message.actions}
            />
          );
        })}

        {/* Streaming message */}
        {isStreaming && currentStream && (
          <div className="mb-4">
            <ChatMessage
              type="ai"
              content={renderMessageContent(currentStream, true)}
            />
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Typing indicator */}
      <TypingIndicator visible={isTyping && isExpanded} />

      {/* Chat input */}
      <div onFocus={handleInputFocus} className="px-5 py-3 pointer-events-auto">
        <ChatInput
          agents={agents}
          currentAgent={currentAgent}
          onSelectAgent={handleAgentSelect}
          onSendMessage={handleSendMessage}
          projectFiles={projectFiles}
          projectName={projectName}
          disabled={isStreaming || agentExecuting}
          initialMessage={initialMessage}
        />
      </div>
    </div>
  );
}
