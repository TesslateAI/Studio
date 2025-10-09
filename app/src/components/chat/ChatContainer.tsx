import { useState, useRef, useEffect, type ReactNode } from 'react';
import { UsageRibbon } from './UsageRibbon';
import { ChatMessage } from './ChatMessage';
import { ChatInput } from './ChatInput';
import { TypingIndicator } from './TypingIndicator';

interface Agent {
  id: string;
  name: string;
  icon: ReactNode;
  active?: boolean;
}

interface Message {
  id: string;
  type: 'user' | 'ai';
  content: string;
  toolCalls?: Array<{
    name: string;
    description: string;
  }>;
  actions?: Array<{
    label: string;
    onClick: () => void;
  }>;
}

interface ChatContainerProps {
  agents: Agent[];
  messages: Message[];
  currentAgent: Agent;
  onSelectAgent: (agent: Agent) => void;
  onSendMessage: (message: string) => void;
  onUpload?: (type: 'image' | 'file' | 'folder') => void;
  onAction?: (action: string) => void;
  onGetMoreCredits: () => void;
  creditsLeft: number;
  isTyping?: boolean;
  className?: string;
}

export function ChatContainer({
  agents,
  messages,
  currentAgent,
  onSelectAgent,
  onSendMessage,
  onUpload,
  onAction,
  onGetMoreCredits,
  creditsLeft,
  isTyping = false,
  className = ''
}: ChatContainerProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to latest message
  useEffect(() => {
    if (isExpanded && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isExpanded]);

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
          ${isExpanded
            ? 'opacity-100 max-h-[calc(100vh-400px)] py-5'
            : 'opacity-0 max-h-0 py-0'
          }
        `}
      >
        {messages.map((message) => (
          <ChatMessage
            key={message.id}
            type={message.type}
            content={message.content}
            toolCalls={message.toolCalls}
            actions={message.actions}
          />
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Typing indicator */}
      <TypingIndicator visible={isTyping && isExpanded} />

      {/* Chat input */}
      <div onFocus={handleInputFocus}>
        <ChatInput
          agents={agents}
          currentAgent={currentAgent}
          onSelectAgent={onSelectAgent}
          onSendMessage={onSendMessage}
          onUpload={onUpload}
          onAction={onAction}
        />
      </div>
    </div>
  );
}
