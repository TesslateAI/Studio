import React, { useState, useEffect, useRef } from 'react';
import { Send, Code, File, Loader2, FileCode } from 'lucide-react';
import { createWebSocket, chatApi } from '../lib/api';
import toast from 'react-hot-toast';
import ChatModeToggle from './ChatModeToggle';
import AgentMessage from './AgentMessage';
import { type AgentMessageData } from '../types/agent';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  agentData?: AgentMessageData;
}

interface StreamingFile {
  fileName: string;
  isStreaming: boolean;
}

interface ChatProps {
  projectId: number;
  onFileUpdate: (filePath: string, content: string) => void;
}

export default function Chat({ projectId, onFileUpdate }: ChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentStream, setCurrentStream] = useState('');
  const [chatMode, setChatMode] = useState<'stream' | 'agent'>('stream');
  const [agentExecuting, setAgentExecuting] = useState(false);
  const [streamingFiles, setStreamingFiles] = useState<Map<string, StreamingFile>>(new Map());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Get user info from token for unique chat history keys
  const getUserFromToken = () => {
    const token = localStorage.getItem('token');
    if (!token) return null;
    
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      return payload.sub; // User ID from JWT
    } catch (error) {
      console.error('Failed to parse user from token:', error);
      return null;
    }
  };

  // Load chat history from database on component mount
  useEffect(() => {
    const loadChatHistory = async () => {
      try {
        console.log('[CHAT] Loading chat history from database for project:', projectId);
        const messages = await chatApi.getProjectMessages(projectId);
        console.log('[CHAT] Loaded', messages.length, 'messages from database for project', projectId);
        setMessages(messages.map(msg => ({ role: msg.role as 'user' | 'assistant', content: msg.content })));
      } catch (error) {
        console.error('[CHAT] Failed to load chat history from database:', error);
        console.log('[CHAT] Starting fresh for project', projectId);
        setMessages([]);
      }
    };
    
    loadChatHistory();
  }, [projectId]);

  // Note: Messages are automatically saved to database via WebSocket
  // No need for localStorage since database is the source of truth

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) return;

    let ws: WebSocket | null = null;
    let isCleaningUp = false;

    const connectWebSocket = () => {
      // Close existing connection if any
      if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
        wsRef.current.close();
      }

      ws = createWebSocket(token);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isCleaningUp) {
          console.log('WebSocket connected');
        }
      };

      ws.onmessage = (event) => {
        if (isCleaningUp) return;
        
        const data = JSON.parse(event.data);
        console.log('WebSocket message:', data.type);
        
        if (data.type === 'stream') {
          setCurrentStream(prev => prev + data.content);
          
          // Extract file names from code blocks following system prompt format: ```javascript\n// File: path/to/file.js
          const codeBlockPattern = /```\w+\s*\n\/\/\s*File:\s*([^\n]+)/g;
          let match;
          while ((match = codeBlockPattern.exec(data.content)) !== null) {
            const fileName = match[1].trim();
            setStreamingFiles(prev => new Map(prev).set(fileName, { fileName, isStreaming: true }));
          }
        } else if (data.type === 'complete') {
          setMessages(prev => [...prev, { role: 'assistant', content: data.content }]);
          setCurrentStream('');
          setIsStreaming(false);
          // Mark all files as completed
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
          
          // Mark this specific file as completed
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
          // Mark all files as completed on error
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
          console.error('WebSocket error:', error);
        }
      };

      ws.onclose = () => {
        if (!isCleaningUp) {
          console.log('WebSocket disconnected');
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
  }, [projectId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, currentStream]);

  // Load chat mode preference from localStorage
  useEffect(() => {
    const savedMode = localStorage.getItem(`chat_mode_${projectId}`);
    if (savedMode === 'agent' || savedMode === 'stream') {
      setChatMode(savedMode);
    }
  }, [projectId]);

  const handleModeToggle = (mode: 'stream' | 'agent') => {
    setChatMode(mode);
    localStorage.setItem(`chat_mode_${projectId}`, mode);
  };

  const sendAgentMessage = async () => {
    if (!input.trim() || agentExecuting) return;

    const userMessage = { role: 'user' as const, content: input };
    setMessages(prev => [...prev, userMessage]);
    setAgentExecuting(true);
    const messageText = input;
    setInput('');

    try {
      const response = await chatApi.sendAgentMessage({
        project_id: projectId,
        message: messageText,
        agent_id: undefined,  // Note: This component doesn't have agent selection yet
        max_iterations: 20,
      });

      if (response.success) {
        const agentMessage: Message = {
          role: 'assistant',
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
          role: 'assistant',
          content: "I apologize, but I encountered an error while working on your request. The task could not be completed. Please try again or contact support if the issue persists.",
        };
        setMessages(prev => [...prev, errorMessage]);

        // Show technical error in toast
        toast.error(response.error || 'Agent execution failed', {
          duration: 5000,
        });
      }
    } catch (error: any) {
      console.error('Agent execution error:', error);

      // Add error message to chat
      const errorMessage: Message = {
        role: 'assistant',
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

  const sendStreamMessage = () => {
    if (!input.trim() || !wsRef.current || isStreaming) return;

    const userMessage = { role: 'user' as const, content: input };
    setMessages(prev => [...prev, userMessage]);
    setIsStreaming(true);
    setInput('');
    setStreamingFiles(new Map()); // Clear previous streaming files

    wsRef.current.send(JSON.stringify({
      message: input,
      project_id: projectId,
      chat_id: 1,
    }));
  };

  const sendMessage = () => {
    if (chatMode === 'agent') {
      sendAgentMessage();
    } else {
      sendStreamMessage();
    }
  };

  const renderMessage = (content: string, isCurrentlyStreaming: boolean = false) => {
    // Handle incomplete code blocks during streaming
    let processedContent = content;

    // For streaming content, also handle incomplete code blocks
    if (isCurrentlyStreaming) {
      // Replace complete code blocks
      processedContent = processedContent.replace(/```\w+\s*\n\/\/\s*File:\s*([^\n]+)[\s\S]*?```/g, (match, fileName) => {
        return `[FILE: ${fileName.trim()}]`;
      });

      // Handle incomplete code blocks (still streaming)
      processedContent = processedContent.replace(/```\w+\s*\n\/\/\s*File:\s*([^\n]+)[\s\S]*$/g, (match, fileName) => {
        return `[FILE: ${fileName.trim()}]`;
      });
    } else {
      // For complete messages, just replace all code blocks
      processedContent = processedContent.replace(/```[\s\S]*?```/g, (match) => {
        const fileMatch = match.match(/```\w+\s*\n\/\/\s*File:\s*([^\n]+)/);
        if (fileMatch) {
          const fileName = fileMatch[1].trim();
          return `[FILE: ${fileName}]`;
        }
        return ''; // Remove code blocks without file names
      });
    }

    // Split by file placeholders
    const parts = processedContent.split(/\[FILE: ([^\]]+)\]/g);
    
    return parts.map((part, index) => {
      // Even indices are text, odd indices are file names
      if (index % 2 === 0) {
        return <span key={index}>{part}</span>;
      } else {
        const fileName = part;
        const fileInfo = streamingFiles.get(fileName);
        const isFileStreaming = isCurrentlyStreaming && (!fileInfo || fileInfo.isStreaming !== false);
        
        return (
          <div key={index} className="my-2">
            <div className="flex items-center gap-2 p-3 bg-gray-100 rounded-lg border border-gray-200">
              <FileCode size={18} className="text-orange-500" />
              <span className="text-sm font-medium text-gray-700 flex-1">{fileName}</span>
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

  return (
    <div className="flex flex-col h-full bg-white/60 backdrop-blur-xl border-r border-orange-200/30 shadow-xl overflow-hidden">
      {/* Chat Header */}
      <div className="p-4 border-b border-orange-200/30 bg-white/80 backdrop-blur-lg shadow-sm">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-orange-500/90 backdrop-blur-sm rounded-xl flex items-center justify-center shadow-lg ring-1 ring-orange-200/50">
            <Code size={18} className="text-white drop-shadow-sm" />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-gray-800">AI Assistant</h3>
            <p className="text-xs text-gray-600">Ready to help you build</p>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse shadow-sm"></div>
            <span className="text-xs text-gray-500 font-medium">Online</span>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0 scrollbar-thin scrollbar-thumb-orange-200/50 scrollbar-track-transparent">
        {messages.length === 0 && !isStreaming && (
          <div className="text-center text-gray-500 mt-8 space-y-4">
            <div className="w-16 h-16 bg-orange-100/80 backdrop-blur-sm rounded-2xl flex items-center justify-center mx-auto shadow-lg ring-1 ring-orange-200/50">
              <Code size={24} className="text-orange-600" />
            </div>
            <div className="space-y-2">
              <p className="text-lg font-semibold text-gray-800">Let's start building</p>
              <p className="text-sm text-gray-600 max-w-xs mx-auto leading-relaxed">
                Describe what you'd like to create and I'll help you build it step by step
              </p>
            </div>
            <div className="flex flex-wrap gap-2 justify-center mt-4">
              <span className="px-3 py-1 bg-orange-50 text-orange-700 rounded-full text-xs font-medium border border-orange-200/50">React components</span>
              <span className="px-3 py-1 bg-orange-50 text-orange-700 rounded-full text-xs font-medium border border-orange-200/50">Full applications</span>
              <span className="px-3 py-1 bg-orange-50 text-orange-700 rounded-full text-xs font-medium border border-orange-200/50">UI/UX design</span>
            </div>
          </div>
        )}
        
        {messages.map((message, index) => {
          // Render agent message differently
          if (message.role === 'assistant' && message.agentData) {
            return (
              <AgentMessage
                key={index}
                agentData={message.agentData}
                finalResponse={message.content}
              />
            );
          }

          // Regular message rendering
          return (
            <div
              key={index}
              className={`flex ${
                message.role === 'user' ? 'justify-end' : 'justify-start'
              }`}
            >
              {message.role === 'assistant' && (
                <div className="w-8 h-8 bg-orange-500/90 backdrop-blur-sm rounded-lg flex items-center justify-center shadow-md ring-1 ring-orange-200/50 mr-3 mt-1 flex-shrink-0">
                  <Code size={14} className="text-white" />
                </div>
              )}
              <div
                className={`max-w-[80%] rounded-2xl px-4 py-3 shadow-lg backdrop-blur-sm ${
                  message.role === 'user'
                    ? 'bg-orange-500/90 text-white shadow-orange-200/50 ring-1 ring-orange-300/50'
                    : 'bg-white/80 text-gray-800 shadow-gray-200/50 ring-1 ring-gray-200/50'
                }`}
              >
                <div className="text-sm leading-relaxed whitespace-pre-wrap">
                  {renderMessage(message.content, false)}
                </div>
                <div className={`text-xs mt-2 opacity-70 ${
                  message.role === 'user' ? 'text-orange-100' : 'text-gray-500'
                }`}>
                  {new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
              {message.role === 'user' && (
                <div className="w-8 h-8 bg-gray-300/80 backdrop-blur-sm rounded-lg flex items-center justify-center shadow-md ring-1 ring-gray-200/50 ml-3 mt-1 flex-shrink-0">
                  <div className="w-5 h-5 bg-gray-600 rounded-full"></div>
                </div>
              )}
            </div>
          );
        })}
        
        {isStreaming && (
          <div className="flex justify-start">
            <div className="w-8 h-8 bg-orange-500/90 backdrop-blur-sm rounded-lg flex items-center justify-center shadow-md ring-1 ring-orange-200/50 mr-3 mt-1 flex-shrink-0">
              <Code size={14} className="text-white" />
            </div>
            <div className="max-w-[80%] rounded-2xl px-4 py-3 bg-white/80 text-gray-800 shadow-lg backdrop-blur-sm ring-1 ring-gray-200/50">
              {currentStream && (
                <div className="text-sm leading-relaxed whitespace-pre-wrap">
                  {renderMessage(currentStream, true)}
                </div>
              )}
              <div className="flex items-center gap-2 mt-3 text-orange-600">
                <Loader2 className="animate-spin" size={14} />
                <span className="text-xs font-medium">AI is thinking...</span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>
      
      {/* Input Area */}
      <div className="p-4 border-t border-orange-200/30 bg-white/80 backdrop-blur-lg">
        <ChatModeToggle
          mode={chatMode}
          onChange={handleModeToggle}
          disabled={isStreaming || agentExecuting}
        />
        <div className="flex gap-3">
          <div className="flex-1 relative">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
              placeholder="Describe what you'd like to build..."
              className="w-full bg-white/90 backdrop-blur-sm text-gray-800 px-4 py-3 pr-12 rounded-2xl focus:outline-none focus:ring-2 focus:ring-orange-400/50 border border-orange-200/50 placeholder-gray-500 shadow-sm text-sm"
              disabled={isStreaming || agentExecuting}
            />
            <div className="absolute right-3 top-1/2 transform -translate-y-1/2 text-xs text-gray-400">
              {input.length > 0 && (
                <span className="text-gray-400">
                  {input.length}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={sendMessage}
            disabled={isStreaming || agentExecuting || !input.trim()}
            className={`backdrop-blur-sm text-white px-4 py-3 rounded-2xl disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 shadow-lg hover:shadow-xl hover:scale-105 ${
              chatMode === 'agent'
                ? 'bg-purple-500/90 hover:bg-purple-600/90 ring-1 ring-purple-300/50'
                : 'bg-orange-500/90 hover:bg-orange-600/90 ring-1 ring-orange-300/50'
            }`}
          >
            {isStreaming || agentExecuting ? (
              <Loader2 className="animate-spin" size={18} />
            ) : (
              <Send size={18} />
            )}
          </button>
        </div>
        <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
          <span>Press Enter to send</span>
          <span className="flex items-center gap-1">
            <div className="w-1.5 h-1.5 bg-emerald-400 rounded-full"></div>
            Connected
          </span>
        </div>
      </div>
    </div>
  );
}