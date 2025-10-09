import { type ReactNode } from 'react';

interface ChatMessageProps {
  type: 'user' | 'ai';
  content: ReactNode;
  avatar?: ReactNode;
  actions?: Array<{
    label: string;
    onClick: () => void;
  }>;
  toolCalls?: Array<{
    name: string;
    description: string;
  }>;
}

export function ChatMessage({ type, content, avatar, actions, toolCalls }: ChatMessageProps) {
  const isUser = type === 'user';

  const defaultAvatar = isUser ? (
    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[var(--primary)] to-orange-400 flex items-center justify-center">
      <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 256 256">
        <path d="M230.92,212c-15.23-26.33-38.7-45.21-66.09-54.16a72,72,0,1,0-73.66,0C63.78,166.78,40.31,185.66,25.08,212a8,8,0,1,0,13.85,8c18.84-32.56,52.14-52,89.07-52s70.23,19.44,89.07,52a8,8,0,1,0,13.85-8ZM72,96a56,56,0,1,1,56,56A56.06,56.06,0,0,1,72,96Z" />
      </svg>
    </div>
  ) : (
    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[hsl(var(--hue2)_60%_50%)] to-[hsl(var(--hue2)_60%_70%)] flex items-center justify-center">
      <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 256 256">
        <path d="M197.58,129.06,146,110l-19.06-51.58a15.92,15.92,0,0,0-29.88,0L78,110,26.42,129.06a15.92,15.92,0,0,0,0,29.88L78,178l19.06,51.58a15.92,15.92,0,0,0,29.88,0L146,178l51.58-19.06a15.92,15.92,0,0,0,0-29.88ZM137.75,142.25a16,16,0,0,0-9.5,9.5L112,193.58,95.75,151.75a16,16,0,0,0-9.5-9.5L44.42,128l41.83-14.25a16,16,0,0,0,9.5-9.5L112,62.42l16.25,41.83a16,16,0,0,0,9.5,9.5L179.58,128ZM248,80a8,8,0,0,1-8,8h-8v8a8,8,0,0,1-16,0V88h-8a8,8,0,0,1,0-16h8V64a8,8,0,0,1,16,0v8h8A8,8,0,0,1,248,80ZM152,40a8,8,0,0,1,8-8h8V24a8,8,0,0,1,16,0v8h8a8,8,0,0,1,0,16h-8v8a8,8,0,0,1-16,0V48h-8A8,8,0,0,1,152,40Z" />
      </svg>
    </div>
  );

  return (
    <div className={`message my-4 flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div className="message-avatar flex-shrink-0">
        {avatar || defaultAvatar}
      </div>

      {/* Content */}
      <div className="flex-1 max-w-[75%]">
        <div
          className={`
            message-bubble px-4 py-3 rounded-2xl text-sm leading-relaxed
            ${isUser
              ? 'bg-gradient-to-br from-[rgba(255,107,0,0.9)] to-[rgba(255,140,58,0.9)] text-white border border-white/20'
              : 'bg-[var(--text)]/5 text-[var(--text)] border border-[var(--border-color)]'
            }
          `}
        >
          {content}
        </div>

        {/* Tool Calls */}
        {toolCalls && toolCalls.length > 0 && (
          <div className="mt-2 space-y-2">
            {toolCalls.map((tool, idx) => (
              <div
                key={idx}
                className="tool-call bg-[rgba(0,217,255,0.1)] border border-[rgba(0,217,255,0.2)] rounded-lg px-3 py-2 text-xs text-[var(--accent)] font-mono"
              >
                <strong>{tool.name}</strong>
                {tool.description && <span className="ml-2 text-[var(--text)]/60">{tool.description}</span>}
              </div>
            ))}
          </div>
        )}

        {/* Actions */}
        {actions && actions.length > 0 && (
          <div className="message-actions flex gap-2 mt-2">
            {actions.map((action, idx) => (
              <button
                key={idx}
                onClick={action.onClick}
                className="message-action-btn px-3 py-1.5 bg-[rgba(255,107,0,0.2)] border border-[rgba(255,107,0,0.3)] rounded-lg text-[var(--primary)] text-xs hover:bg-[rgba(255,107,0,0.3)] transition-colors"
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
