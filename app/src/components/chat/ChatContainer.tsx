import { useState, useRef, useEffect, type ReactNode } from 'react';
import { Code, Loader2, FileCode } from 'lucide-react';
import { UsageRibbon } from './UsageRibbon';
import { ChatMessage } from './ChatMessage';
import { ChatInput } from './ChatInput';
import { TypingIndicator } from './TypingIndicator';
import { createWebSocket, chatApi, agentsApi } from '../../lib/api';
import toast from 'react-hot-toast';
import AgentMessage from '../AgentMessage';
import { type AgentMessageData, type Agent as BackendAgent } from '../../types/agent';

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

interface ChatContainerProps {
  projectId: number;
  agents: Agent[];
  currentAgent: Agent;
  onSelectAgent: (agent: Agent) => void;
  onFileUpdate: (filePath: string, content: string) => void;
  onUpload?: (type: 'image' | 'file' | 'folder') => void;
  onAction?: (action: string) => void;
  onGetMoreCredits: () => void;
  creditsLeft: number;
  className?: string;
}

export function ChatContainer({
  projectId,
  agents: initialAgents,
  currentAgent: initialCurrentAgent,
  onSelectAgent,
  onFileUpdate,
  onUpload,
  onAction,
  onGetMoreCredits,
  creditsLeft,
  className = ''
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
        console.log('[CHAT] Loading chat history from database for project:', projectId);
        const dbMessages = await chatApi.getProjectMessages(projectId);
        console.log('[CHAT] Loaded', dbMessages.length, 'messages from database');
        setMessages(dbMessages.map((msg, idx) => {
          const message: Message = {
            id: `msg-${idx}`,
            type: msg.role as 'user' | 'ai',
            content: msg.content
          };

          // Restore agent data from metadata if available
          if (msg.metadata && msg.metadata.agent_mode) {
            message.agentData = {
              steps: msg.metadata.steps,
              iterations: msg.metadata.iterations,
              tool_calls_made: msg.metadata.tool_calls_made,
              completion_reason: msg.metadata.completion_reason
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

  // Load agents from backend
  useEffect(() => {
    const loadAgents = async () => {
      try {
        const fetchedAgents = await agentsApi.getAll();
        setBackendAgents(fetchedAgents);

        // Convert backend agents to UI agents
        const uiAgents = fetchedAgents.map(agent => ({
          id: agent.slug,
          name: agent.name,
          icon: agent.icon,
          backendId: agent.id,
          mode: agent.mode
        }));

        setAgents(uiAgents);

        // Set first agent as default if no current agent
        if (uiAgents.length > 0 && !currentAgent) {
          const defaultAgent = uiAgents[0];
          setCurrentAgent(defaultAgent);
          onSelectAgent(defaultAgent);
        }
      } catch (error) {
        console.error('Failed to load agents:', error);
        toast.error('Failed to load AI agents');
      }
    };

    loadAgents();
  }, []);

  // WebSocket connection
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) return;

    let ws: WebSocket | null = null;
    let isCleaningUp = false;

    const connectWebSocket = () => {
      if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
        wsRef.current.close();
      }

      ws = createWebSocket(token);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isCleaningUp) {
          console.log('[WS] WebSocket connected');
        }
      };

      ws.onmessage = (event) => {
        if (isCleaningUp) return;

        const data = JSON.parse(event.data);
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
          setMessages(prev => [...prev, {
            id: `msg-${Date.now()}`,
            type: 'ai',
            content: data.content
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
        if (!isCleaningUp) {
          console.log('[WS] WebSocket disconnected');
        }
      };
    };

    connectWebSocket();

    return () => {
      isCleaningUp = true;
      if (ws && ws.readyState !== WebSocket.CLOSED) {
        ws.close();
      }
    };
  }, [projectId, onFileUpdate]);

  // Auto-scroll to latest message
  useEffect(() => {
    if (isExpanded && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, currentStream, isExpanded]);

  // Collapse chat when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsExpanded(false);
      }
    };

    if (isExpanded) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
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
      const errorDetail = error?.response?.data?.detail || error?.message || 'Failed to execute agent';
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

      {/* Usage ribbon */}
      <UsageRibbon
        creditsLeft={creditsLeft}
        onGetMore={onGetMoreCredits}
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
              <Code size={24} className="text-orange-500" />
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
      <div onFocus={handleInputFocus} className="px-5 py-3 border-t border-[var(--border-color)] pointer-events-auto">
        <ChatInput
          agents={agents}
          currentAgent={currentAgent}
          onSelectAgent={handleAgentSelect}
          onSendMessage={handleSendMessage}
          onUpload={onUpload}
          onAction={onAction}
          disabled={isStreaming || agentExecuting}
        />
      </div>
    </div>
  );
}
