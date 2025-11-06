import { useState, useEffect, type FormEvent, type KeyboardEvent } from 'react';
import { AgentSelector } from './AgentSelector';
import { ToolDropdown } from './ToolDropdown';
import { Gear } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import JSZip from 'jszip';

interface Agent {
  id: string;
  name: string;
  icon: string;  // Emoji string from backend
  active?: boolean;
  backendId?: number;  // Link to backend agent ID
  mode?: 'stream' | 'agent';
}

interface ProjectFile {
  file_path: string;
  content: string;
}

interface ChatInputProps {
  agents: Agent[];
  currentAgent: Agent;
  onSelectAgent: (agent: Agent) => void;
  onSendMessage: (message: string) => void;
  projectFiles?: ProjectFile[];
  projectName?: string;
  placeholder?: string;
  disabled?: boolean;
  isExecuting?: boolean;
  onStop?: () => void;
  onClearHistory?: () => void;
}

export function ChatInput({
  agents,
  currentAgent,
  onSelectAgent,
  onSendMessage,
  projectFiles = [],
  projectName = 'project',
  placeholder = 'Ask AI to build something...',
  disabled = false,
  isExecuting = false,
  onStop,
  onClearHistory
}: ChatInputProps) {
  const [message, setMessage] = useState('');

  // Check for landing page prompt on component mount
  useEffect(() => {
    const landingPrompt = localStorage.getItem('landingPrompt');
    if (landingPrompt) {
      setMessage(landingPrompt);
      // Clear the prompt after using it
      localStorage.removeItem('landingPrompt');
    }
  }, []);

  const sendMessage = () => {
    if (message.trim() && !disabled) {
      onSendMessage(message.trim());
      setMessage('');
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    sendMessage();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const downloadProject = async () => {
    try {
      toast.loading('Preparing download...', { id: 'download' });

      const zip = new JSZip();

      // Add all project files to zip
      projectFiles.forEach(file => {
        zip.file(file.file_path, file.content);
      });

      // Generate zip file
      const blob = await zip.generateAsync({ type: 'blob' });

      // Create download link
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${projectName}.zip`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      toast.success('Project downloaded!', { id: 'download', icon: '📦' });
    } catch (error) {
      console.error('Failed to download project:', error);
      toast.error('Failed to download project', { id: 'download' });
    }
  };

  const clearChatHistory = () => {
    if (onClearHistory) {
      const confirmed = window.confirm(
        'Are you sure you want to clear all chat history? This action cannot be undone.'
      );
      if (confirmed) {
        onClearHistory();
      }
    }
  };

  const tools = [
    {
      icon: (
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
          <path d="M224,152v56a16,16,0,0,1-16,16H48a16,16,0,0,1-16-16V152a8,8,0,0,1,16,0v56H208V152a8,8,0,0,1,16,0Zm-101.66,5.66a8,8,0,0,0,11.32,0l40-40a8,8,0,0,0-11.32-11.32L136,132.69V40a8,8,0,0,0-16,0v92.69L93.66,106.34a8,8,0,0,0-11.32,11.32Z" />
        </svg>
      ),
      label: 'Download Project',
      onClick: downloadProject,
      category: 'tools' as const
    },
    ...(onClearHistory ? [{
      icon: (
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
          <path d="M216,48H176V40a24,24,0,0,0-24-24H104A24,24,0,0,0,80,40v8H40a8,8,0,0,0,0,16h8V208a16,16,0,0,0,16,16H192a16,16,0,0,0,16-16V64h8a8,8,0,0,0,0-16ZM96,40a8,8,0,0,1,8-8h48a8,8,0,0,1,8,8v8H96Zm96,168H64V64H192ZM112,104v64a8,8,0,0,1-16,0V104a8,8,0,0,1,16,0Zm48,0v64a8,8,0,0,1-16,0V104a8,8,0,0,1,16,0Z" />
        </svg>
      ),
      label: 'Clear Chat History',
      onClick: clearChatHistory,
      category: 'tools' as const
    }] : [])
  ];

  return (
    <form className="chat-input-wrapper px-2 sm:px-5 py-2 sm:py-4 flex-shrink-0" onSubmit={handleSubmit}>
      {/* Mobile: Single row with compact agent selector */}
      <div className="md:hidden flex items-end gap-2">
        {/* Compact agent selector */}
        <div className="flex-shrink-0 mb-1">
          <AgentSelector
            agents={agents}
            currentAgent={currentAgent}
            onSelectAgent={onSelectAgent}
          />
        </div>

        {/* Growing textarea */}
        <div className="chat-input-container relative flex-1 flex items-center bg-[var(--text)]/5 border border-[var(--border-color)] rounded-xl overflow-visible transition-all focus-within:border-orange-500/50 focus-within:shadow-[0_0_0_3px_rgba(255,107,0,0.1)] focus-within:!outline-none">
          <textarea
            value={message}
            onChange={(e) => {
              setMessage(e.target.value);
              // Auto-resize
              e.target.style.height = 'auto';
              e.target.style.height = e.target.scrollHeight + 'px';
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            placeholder={placeholder}
            rows={1}
            className="chat-input bg-transparent border-none px-3 py-2.5 text-[var(--text)] flex-1 text-sm !outline-none focus:!outline-none placeholder:text-[var(--text)]/40 resize-none max-h-32 overflow-y-auto"
          />
        </div>
        <button
          type={isExecuting ? "button" : "submit"}
          onClick={isExecuting ? onStop : undefined}
          disabled={!isExecuting && (!message.trim() || disabled)}
          className="send-btn w-10 h-10 bg-gradient-to-br from-[var(--primary)] to-orange-400 rounded-xl border-none text-white flex items-center justify-center flex-shrink-0 transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed mb-1"
        >
          {isExecuting ? (
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
              <rect x="64" y="64" width="128" height="128" rx="8"/>
            </svg>
          ) : (
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
              <path d="M231.87,114l-168-95.89A16,16,0,0,0,40.92,37.34L71.55,128,40.92,218.67A16,16,0,0,0,56,240a16.15,16.15,0,0,0,7.93-2.1l167.92-96.05a16,16,0,0,0,.05-27.89ZM56,224a.56.56,0,0,0,0-.12L85.74,136H144a8,8,0,0,0,0-16H85.74L56.06,32.16A.46.46,0,0,0,56,32l168,95.83Z" />
            </svg>
          )}
        </button>
      </div>

      {/* Desktop: Single-level layout */}
      <div className="hidden md:flex items-center gap-2" data-tour="chat-input">
        {/* Tools dropdown */}
        <ToolDropdown
          icon={<Gear size={16} weight="bold" />}
          tools={tools}
        />

        {/* Chat input container with agent pill */}
        <div className="chat-input-container relative flex-1 flex items-center bg-[var(--text)]/5 border border-[var(--border-color)] rounded-2xl overflow-visible transition-all focus-within:border-orange-500/50 focus-within:shadow-[0_0_0_3px_rgba(255,107,0,0.1)] focus-within:!outline-none">
          <AgentSelector
            agents={agents}
            currentAgent={currentAgent}
            onSelectAgent={onSelectAgent}
          />

          <input
            type="text"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            className="chat-input bg-transparent border-none px-4 py-2.5 text-[var(--text)] flex-1 text-sm !outline-none focus:!outline-none placeholder:text-[var(--text)]/40"
          />
        </div>

        {/* Send button / Stop button */}
        <button
          type={isExecuting ? "button" : "submit"}
          onClick={isExecuting ? onStop : undefined}
          disabled={!isExecuting && (!message.trim() || disabled)}
          className="send-btn w-9 h-9 bg-gradient-to-br from-[var(--primary)] to-orange-400 rounded-xl border-none text-white flex items-center justify-center flex-shrink-0 transition-all hover:scale-105 hover:shadow-[0_4px_12px_rgba(255,107,0,0.4)] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
        >
          {isExecuting ? (
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
              <rect x="64" y="64" width="128" height="128" rx="8"/>
            </svg>
          ) : (
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
              <path d="M231.87,114l-168-95.89A16,16,0,0,0,40.92,37.34L71.55,128,40.92,218.67A16,16,0,0,0,56,240a16.15,16.15,0,0,0,7.93-2.1l167.92-96.05a16,16,0,0,0,.05-27.89ZM56,224a.56.56,0,0,0,0-.12L85.74,136H144a8,8,0,0,0,0-16H85.74L56.06,32.16A.46.46,0,0,0,56,32l168,95.83Z" />
            </svg>
          )}
        </button>
      </div>
    </form>
  );
}
