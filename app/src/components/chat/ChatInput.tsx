import { useState, type FormEvent, type KeyboardEvent } from 'react';
import { AgentSelector } from './AgentSelector';
import { ToolDropdown } from './ToolDropdown';
import toast from 'react-hot-toast';
import JSZip from 'jszip';

interface Agent {
  id: string;
  name: string;
  icon: React.ReactNode;
  active?: boolean;
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
}

export function ChatInput({
  agents,
  currentAgent,
  onSelectAgent,
  onSendMessage,
  projectFiles = [],
  projectName = 'project',
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
    }
  ];

  return (
    <form className="chat-input-wrapper px-2 sm:px-5 py-2 sm:py-4 flex-shrink-0" onSubmit={handleSubmit}>
      <div className="input-container flex items-center gap-1.5 sm:gap-2" data-tour="chat-input">
        {/* Tools dropdown - hidden on mobile for more space */}
        <div className="hidden sm:block">
          <ToolDropdown
            icon={
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                <path d="M224,152v56a16,16,0,0,1-16,16H48a16,16,0,0,1-16-16V152a8,8,0,0,1,16,0v56H208V152a8,8,0,0,1,16,0Zm-101.66,5.66a8,8,0,0,0,11.32,0l40-40a8,8,0,0,0-11.32-11.32L136,132.69V40a8,8,0,0,0-16,0v92.69L93.66,106.34a8,8,0,0,0-11.32,11.32Z" />
              </svg>
            }
            tools={tools}
          />
        </div>

        {/* Chat input container with agent pill */}
        <div className="chat-input-container relative flex-1 flex items-center bg-[var(--text)]/5 border border-[var(--border-color)] rounded-xl sm:rounded-2xl overflow-visible transition-all focus-within:border-orange-500/50 focus-within:shadow-[0_0_0_3px_rgba(255,107,0,0.1)] focus-within:!outline-none">
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
            className="chat-input bg-transparent border-none px-2 sm:px-4 py-2 sm:py-2.5 text-[var(--text)] flex-1 text-xs sm:text-sm !outline-none focus:!outline-none placeholder:text-[var(--text)]/40"
          />
        </div>

        {/* Send button */}
        <button
          type="submit"
          disabled={!message.trim() || disabled}
          className="send-btn w-8 h-8 sm:w-9 sm:h-9 bg-gradient-to-br from-[var(--primary)] to-orange-400 rounded-lg sm:rounded-xl border-none text-white flex items-center justify-center flex-shrink-0 transition-all hover:scale-105 hover:shadow-[0_4px_12px_rgba(255,107,0,0.4)] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
        >
          <svg className="w-3.5 h-3.5 sm:w-4 sm:h-4" fill="currentColor" viewBox="0 0 256 256">
            <path d="M231.87,114l-168-95.89A16,16,0,0,0,40.92,37.34L71.55,128,40.92,218.67A16,16,0,0,0,56,240a16.15,16.15,0,0,0,7.93-2.1l167.92-96.05a16,16,0,0,0,.05-27.89ZM56,224a.56.56,0,0,0,0-.12L85.74,136H144a8,8,0,0,0,0-16H85.74L56.06,32.16A.46.46,0,0,0,56,32l168,95.83Z" />
          </svg>
        </button>
      </div>
    </form>
  );
}
