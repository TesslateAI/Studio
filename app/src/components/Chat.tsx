import React, { useState, useEffect, useRef } from 'react';
import { Send, Code, File, Loader2 } from 'lucide-react';
import { createWebSocket, chatApi } from '../lib/api';
import toast from 'react-hot-toast';

interface Message {
  role: 'user' | 'assistant';
  content: string;
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
        } else if (data.type === 'complete') {
          setMessages(prev => [...prev, { role: 'assistant', content: data.content }]);
          setCurrentStream('');
          setIsStreaming(false);
        } else if (data.type === 'file_ready') {
          onFileUpdate(data.file_path, data.content);
          toast.success(`Created ${data.file_path}`, { duration: 2000 });
        } else if (data.type === 'error') {
          toast.error(data.content);
          setIsStreaming(false);
          setCurrentStream('');
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

  const sendMessage = () => {
    if (!input.trim() || !wsRef.current || isStreaming) return;

    const userMessage = { role: 'user' as const, content: input };
    setMessages(prev => [...prev, userMessage]);
    setIsStreaming(true);
    setInput('');

    wsRef.current.send(JSON.stringify({
      message: input,
      project_id: projectId,
      chat_id: 1, // Simple chat ID - messages are separated by localStorage per project
    }));
  };

  const renderMessage = (content: string) => {
    const parts = content.split(/(```[\s\S]*?```)/g);
    
    return parts.map((part, index) => {
      if (part.startsWith('```')) {
        const match = part.match(/```(?:(\w+))?\s*(?:# )?(?:File: )?([^\n]+\.[\w]+)?\n([\s\S]*?)```/);
        if (match) {
          const [, language, fileName, code] = match;
          return (
            <div key={index} className="my-2">
              {fileName && (
                <div className="flex items-center gap-2 text-sm text-gray-400 mb-1">
                  <File size={14} />
                  <span>{fileName}</span>
                </div>
              )}
              <pre className="bg-gray-800 p-3 rounded-lg overflow-x-auto">
                <code className={`language-${language || 'plaintext'}`}>
                  {code.trim()}
                </code>
              </pre>
            </div>
          );
        }
      }
      return <span key={index}>{part}</span>;
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
        
        {messages.map((message, index) => (
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
                {renderMessage(message.content)}
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
        ))}
        
        {isStreaming && (
          <div className="flex justify-start">
            <div className="w-8 h-8 bg-orange-500/90 backdrop-blur-sm rounded-lg flex items-center justify-center shadow-md ring-1 ring-orange-200/50 mr-3 mt-1 flex-shrink-0">
              <Code size={14} className="text-white" />
            </div>
            <div className="max-w-[80%] rounded-2xl px-4 py-3 bg-white/80 text-gray-800 shadow-lg backdrop-blur-sm ring-1 ring-gray-200/50">
              {currentStream && (
                <div className="text-sm leading-relaxed whitespace-pre-wrap">
                  {renderMessage(currentStream)}
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
        <div className="flex gap-3">
          <div className="flex-1 relative">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
              placeholder="Describe what you'd like to build..."
              className="w-full bg-white/90 backdrop-blur-sm text-gray-800 px-4 py-3 pr-12 rounded-2xl focus:outline-none focus:ring-2 focus:ring-orange-400/50 border border-orange-200/50 placeholder-gray-500 shadow-sm text-sm"
              disabled={isStreaming}
            />
            <div className="absolute right-3 top-1/2 transform -translate-y-1/2 text-xs text-gray-400">
              {input.length > 0 && (
                <span className={`${input.length > 500 ? 'text-orange-500' : 'text-gray-400'}`}>
                  {input.length}/500
                </span>
              )}
            </div>
          </div>
          <button
            onClick={sendMessage}
            disabled={isStreaming || !input.trim()}
            className="bg-orange-500/90 backdrop-blur-sm text-white px-4 py-3 rounded-2xl hover:bg-orange-600/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 shadow-lg ring-1 ring-orange-300/50 hover:shadow-xl hover:scale-105"
          >
            {isStreaming ? (
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