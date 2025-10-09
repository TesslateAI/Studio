import { useState, type FormEvent, type KeyboardEvent } from 'react';
import { AgentSelector } from './AgentSelector';
import { ToolDropdown } from './ToolDropdown';

interface Agent {
  id: string;
  name: string;
  icon: React.ReactNode;
  active?: boolean;
}

interface ChatInputProps {
  agents: Agent[];
  currentAgent: Agent;
  onSelectAgent: (agent: Agent) => void;
  onSendMessage: (message: string) => void;
  onUpload?: (type: 'image' | 'file' | 'folder') => void;
  onAction?: (action: string) => void;
  placeholder?: string;
  disabled?: boolean;
}

export function ChatInput({
  agents,
  currentAgent,
  onSelectAgent,
  onSendMessage,
  onUpload,
  onAction,
  placeholder = 'Ask AI to build something...',
  disabled = false
}: ChatInputProps) {
  const [message, setMessage] = useState('');

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (message.trim() && !disabled) {
      onSendMessage(message.trim());
      setMessage('');
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as any);
    }
  };

  const uploadTools = [
    {
      icon: (
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
          <path d="M216,40H40A16,16,0,0,0,24,56V200a16,16,0,0,0,16,16H216a16,16,0,0,0,16-16V56A16,16,0,0,0,216,40Zm0,16V158.75l-26.07-26.06a16,16,0,0,0-22.63,0l-20,20-44-44a16,16,0,0,0-22.62,0L40,149.37V56ZM40,172l52-52,80,80H40Zm176,28H194.63l-36-36,20-20L216,181.38V200ZM144,100a12,12,0,1,1,12,12A12,12,0,0,1,144,100Z" />
        </svg>
      ),
      label: 'Upload Image',
      onClick: () => onUpload?.('image'),
      category: 'tools' as const
    },
    {
      icon: (
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
          <path d="M213.66,82.34l-56-56A8,8,0,0,0,152,24H56A16,16,0,0,0,40,40V216a16,16,0,0,0,16,16H200a16,16,0,0,0,16-16V88A8,8,0,0,0,213.66,82.34ZM160,51.31,188.69,80H160ZM200,216H56V40h88V88a8,8,0,0,0,8,8h48V216Z" />
        </svg>
      ),
      label: 'Upload File',
      onClick: () => onUpload?.('file'),
      category: 'tools' as const
    },
    {
      icon: (
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
          <path d="M216,72H131.31L104,44.69A15.86,15.86,0,0,0,92.69,40H40A16,16,0,0,0,24,56V200.62A15.4,15.4,0,0,0,39.38,216H216.89A15.13,15.13,0,0,0,232,200.89V88A16,16,0,0,0,216,72ZM40,56H92.69l16,16H40ZM216,200H40V88H216Z" />
        </svg>
      ),
      label: 'Upload Folder',
      onClick: () => onUpload?.('folder'),
      category: 'tools' as const
    }
  ];

  const actionTools = [
    {
      icon: (
        <svg className="w-4 h-4 text-green-400" fill="currentColor" viewBox="0 0 256 256">
          <path d="M208,56H48A32,32,0,0,0,16,88v80a32,32,0,0,0,32,32H208a32,32,0,0,0,32-32V88A32,32,0,0,0,208,56Zm16,112a16,16,0,0,1-16,16H48a16,16,0,0,1-16-16V88A16,16,0,0,1,48,72H208a16,16,0,0,1,16,16Zm-48-96a8,8,0,0,1-8,8H136a8,8,0,0,1,0-16h32A8,8,0,0,1,176,72Zm32,0a8,8,0,0,1-8,8h-8a8,8,0,0,1,0-16h8A8,8,0,0,1,208,72ZM80,96a8,8,0,0,1,8-8h80a8,8,0,0,1,0,16H88A8,8,0,0,1,80,96Zm0,24a8,8,0,0,1,8-8h80a8,8,0,0,1,0,16H88A8,8,0,0,1,80,120Zm0,24a8,8,0,0,1,8-8h80a8,8,0,0,1,0,16H88A8,8,0,0,1,80,144Z" />
        </svg>
      ),
      label: 'Security Scan',
      onClick: () => onAction?.('security-scan'),
      category: 'actions' as const
    },
    {
      icon: (
        <svg className="w-4 h-4 text-blue-400" fill="currentColor" viewBox="0 0 256 256">
          <path d="M229.66,58.34l-32-32a8,8,0,0,0-11.32,11.32L204.69,56H128a88.1,88.1,0,0,0-88,88,8,8,0,0,0,16,0,72.08,72.08,0,0,1,72-72h76.69l-18.35,18.34a8,8,0,0,0,11.32,11.32l32-32A8,8,0,0,0,229.66,58.34ZM216,144a8,8,0,0,0-8,8,72.08,72.08,0,0,1-72,72H59.31l18.35-18.34a8,8,0,0,0-11.32-11.32l-32,32a8,8,0,0,0,0,11.32l32,32a8,8,0,0,0,11.32-11.32L59.31,240H136a88.1,88.1,0,0,0,88-88A8,8,0,0,0,216,144Z" />
        </svg>
      ),
      label: 'Code Review',
      onClick: () => onAction?.('code-review'),
      category: 'actions' as const
    },
    {
      icon: (
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
          <path d="M208,56H180.28L166.65,35.56A8,8,0,0,0,160,32H96a8,8,0,0,0-6.65,3.56L75.71,56H48A24,24,0,0,0,24,80V192a24,24,0,0,0,24,24H208a24,24,0,0,0,24-24V80A24,24,0,0,0,208,56Zm8,136a8,8,0,0,1-8,8H48a8,8,0,0,1-8-8V80a8,8,0,0,1,8-8H80a8,8,0,0,0,6.66-3.56L100.28,48h55.43l13.63,20.44A8,8,0,0,0,176,72h32a8,8,0,0,1,8,8ZM128,88a44,44,0,1,0,44,44A44.05,44.05,0,0,0,128,88Zm0,72a28,28,0,1,1,28-28A28,28,0,0,1,128,160Z" />
        </svg>
      ),
      label: 'Database Query',
      onClick: () => onAction?.('database'),
      category: 'tools' as const
    },
    {
      icon: (
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
          <path d="M232,112a24,24,0,1,0-24,24A24,24,0,0,0,232,112ZM152,64A24,24,0,1,0,128,40,24,24,0,0,0,152,64ZM48,136a24,24,0,1,0-24-24A24,24,0,0,0,48,136Zm0,16a24,24,0,1,0,24,24A24,24,0,0,0,48,152Zm80,0a24,24,0,1,0,24,24A24,24,0,0,0,128,152Zm80,0a24,24,0,1,0,24,24A24,24,0,0,0,208,152Z" />
        </svg>
      ),
      label: 'API Call',
      onClick: () => onAction?.('api'),
      category: 'tools' as const
    },
    {
      icon: (
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
          <path d="M216,40H40A16,16,0,0,0,24,56V200a16,16,0,0,0,16,16H216a16,16,0,0,0,16-16V56A16,16,0,0,0,216,40ZM40,56H216V88H40ZM216,200H40V104H216v96ZM128,136a8,8,0,0,1-8,8H96a8,8,0,0,1,0-16h24A8,8,0,0,1,128,136Zm48,0a8,8,0,0,1-8,8H144a8,8,0,0,1,0-16h24A8,8,0,0,1,176,136Zm0,32a8,8,0,0,1-8,8H96a8,8,0,0,1,0-16h72A8,8,0,0,1,176,168Z" />
        </svg>
      ),
      label: 'Run Command',
      onClick: () => onAction?.('terminal'),
      category: 'tools' as const
    },
    {
      icon: (
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
          <path d="M200,112a8,8,0,0,1-8,8H152v40a8,8,0,0,1-16,0V120H96a8,8,0,0,1,0-16h40V64a8,8,0,0,1,16,0v40h40A8,8,0,0,1,200,112ZM24,72H232a8,8,0,0,0,0-16H24a8,8,0,0,0,0,16Zm208,112H24a8,8,0,0,0,0,16H232a8,8,0,0,0,0-16Z" />
        </svg>
      ),
      label: 'Import from Figma',
      onClick: () => onAction?.('figma'),
      category: 'tools' as const
    }
  ];

  return (
    <form className="chat-input-wrapper px-5 py-4 border-t border-[var(--border-color)] flex-shrink-0" onSubmit={handleSubmit}>
      <div className="input-container flex items-center gap-2">
        {/* Upload dropdown */}
        <ToolDropdown
          icon={
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
              <path d="M209.66,122.34a8,8,0,0,1,0,11.32l-82.05,82a56,56,0,0,1-79.2-79.21L147.67,35.73a40,40,0,1,1,56.61,56.55L105,193A24,24,0,1,1,71,159L154.3,74.38A8,8,0,1,1,165.7,85.6L82.39,170.31a8,8,0,1,0,11.27,11.36L192.93,81A24,24,0,1,0,159,47L59.76,147.68a40,40,0,1,0,56.53,56.62l82.06-82A8,8,0,0,1,209.66,122.34Z" />
            </svg>
          }
          tools={uploadTools}
        />

        {/* Chat input container with agent pill */}
        <div className="chat-input-container relative flex-1 flex items-center bg-[var(--text)]/5 border border-[var(--border-color)] rounded-2xl overflow-visible transition-all focus-within:border-orange-500/50 focus-within:shadow-[0_0_0_3px_rgba(255,107,0,0.1)]">
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
            disabled={disabled}
            className="chat-input bg-transparent border-none px-4 py-2.5 text-[var(--text)] flex-1 text-sm outline-none placeholder:text-[var(--text)]/40"
          />
        </div>

        {/* Actions dropdown */}
        <ToolDropdown
          icon={
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
              <path d="M224,64a32,32,0,1,0-40,31v17a8,8,0,0,1-8,8H80a8,8,0,0,1-8-8V95a32,32,0,1,0-16,0v17a24,24,0,0,0,24,24h40v17a32,32,0,1,0,16,0V136h40a24,24,0,0,0,24-24V95A32.06,32.06,0,0,0,224,64ZM56,64A16,16,0,1,1,72,80,16,16,0,0,1,56,64ZM144,192a16,16,0,1,1-16-16A16,16,0,0,1,144,192ZM192,80a16,16,0,1,1,16-16A16,16,0,0,1,192,80Z" />
            </svg>
          }
          tools={actionTools}
        />

        {/* Send button */}
        <button
          type="submit"
          disabled={!message.trim() || disabled}
          className="send-btn w-9 h-9 bg-gradient-to-br from-[var(--primary)] to-orange-400 rounded-xl border-none text-white flex items-center justify-center flex-shrink-0 transition-all hover:scale-105 hover:shadow-[0_4px_12px_rgba(255,107,0,0.4)] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
        >
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
            <path d="M231.87,114l-168-95.89A16,16,0,0,0,40.92,37.34L71.55,128,40.92,218.67A16,16,0,0,0,56,240a16.15,16.15,0,0,0,7.93-2.1l167.92-96.05a16,16,0,0,0,.05-27.89ZM56,224a.56.56,0,0,0,0-.12L85.74,136H144a8,8,0,0,0,0-16H85.74L56.06,32.16A.46.46,0,0,0,56,32l168,95.83Z" />
          </svg>
        </button>
      </div>
    </form>
  );
}
