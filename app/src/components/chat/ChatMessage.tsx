import { type ReactNode } from 'react';

interface ChatMessageProps {
  type: 'user' | 'ai';
  content: ReactNode;
  avatar?: ReactNode;
  agentIcon?: string;
  actions?: Array<{
    label: string;
    onClick: () => void;
  }>;
  toolCalls?: Array<{
    name: string;
    description: string;
  }>;
}

export function ChatMessage({ type, content, avatar, agentIcon, actions, toolCalls }: ChatMessageProps) {
  const isUser = type === 'user';

  // 60-30-10: User avatar (10% accent), AI avatar (30% secondary surface)
  const defaultAvatar = isUser ? (
    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[var(--primary)] to-[#ff8533] flex items-center justify-center shadow-lg shadow-[var(--primary)]/20">
      <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 256 256">
        <path d="M230.92,212c-15.23-26.33-38.7-45.21-66.09-54.16a72,72,0,1,0-73.66,0C63.78,166.78,40.31,185.66,25.08,212a8,8,0,1,0,13.85,8c18.84-32.56,52.14-52,89.07-52s70.23,19.44,89.07,52a8,8,0,1,0,13.85-8ZM72,96a56,56,0,1,1,56,56A56.06,56.06,0,0,1,72,96Z" />
      </svg>
    </div>
  ) : agentIcon ? (
    <div className="w-8 h-8 rounded-full bg-[var(--surface)] border-2 border-[var(--border-color)] flex items-center justify-center">
      <span className="text-base leading-none">{agentIcon}</span>
    </div>
  ) : (
    <div className="w-8 h-8 rounded-full bg-[var(--surface)] border-2 border-[var(--border-color)] flex items-center justify-center">
      <svg className="w-4 h-4 text-[var(--text)]" fill="currentColor" viewBox="0 0 256 256">
        <path d="M197.58,129.06,146,110l-19.06-51.58a15.92,15.92,0,0,0-29.88,0L78,110,26.42,129.06a15.92,15.92,0,0,0,0,29.88L78,178l19.06,51.58a15.92,15.92,0,0,0,29.88,0L146,178l51.58-19.06a15.92,15.92,0,0,0,0-29.88ZM137.75,142.25a16,16,0,0,0-9.5,9.5L112,193.58,95.75,151.75a16,16,0,0,0-9.5-9.5L44.42,128l41.83-14.25a16,16,0,0,0,9.5-9.5L112,62.42l16.25,41.83a16,16,0,0,0,9.5,9.5L179.58,128ZM248,80a8,8,0,0,1-8,8h-8v8a8,8,0,0,1-16,0V88h-8a8,8,0,0,1,0-16h8V64a8,8,0,0,1,16,0v8h8A8,8,0,0,1,248,80ZM152,40a8,8,0,0,1,8-8h8V24a8,8,0,0,1,16,0v8h8a8,8,0,0,1,0,16h-8v8a8,8,0,0,1-16,0V48h-8A8,8,0,0,1,152,40Z" />
      </svg>
    </div>
  );

  return (
    <div className={`message my-2 flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div className="message-avatar flex-shrink-0">
        {avatar || defaultAvatar}
      </div>

      {/* Content - 60-30-10: User message (10% accent orange), AI message (30% secondary surface) */}
      <div className="flex-1 max-w-[75%]">
        <div
          className={`
            message-bubble px-4 py-3 rounded-2xl text-sm leading-relaxed
            ${isUser
              ? 'bg-gradient-to-br from-[var(--primary)] to-[#ff8533] text-white border-2 border-[var(--primary)]/40 shadow-lg shadow-[var(--primary)]/20'
              : 'bg-[var(--surface)] text-[var(--text)] border-2 border-[var(--border-color)]'
            }
          `}
        >
          {content}
        </div>

        {/* Tool Calls - 30% secondary surface */}
        {toolCalls && toolCalls.length > 0 && (
          <div className="mt-2 space-y-2">
            {toolCalls.map((tool, idx) => (
              <div
                key={idx}
                className="tool-call bg-[var(--surface)] border-2 border-[var(--border-color)] rounded-lg px-3 py-2 text-xs text-[var(--text)]/80 font-mono"
              >
                <strong>{tool.name}</strong>
                {tool.description && <span className="ml-2 text-[var(--text)]/60">{tool.description}</span>}
              </div>
            ))}
          </div>
        )}

        {/* Actions - 10% accent orange */}
        {actions && actions.length > 0 && (
          <div className="message-actions flex gap-2 mt-2">
            {actions.map((action, idx) => (
              <button
                key={idx}
                onClick={action.onClick}
                className="message-action-btn px-3 py-1.5 bg-[var(--primary)]/10 border-2 border-[var(--primary)]/40 rounded-lg text-[var(--primary)] text-xs hover:bg-[var(--primary)]/20 hover:border-[var(--primary)]/60 transition-all"
              >
                {action.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
