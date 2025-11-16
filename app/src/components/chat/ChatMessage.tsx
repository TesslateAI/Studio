import { type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface ChatMessageProps {
  type: 'user' | 'ai';
  content: ReactNode;
  avatar?: ReactNode;
  agentIcon?: string;
  agentAvatarUrl?: string;
  actions?: Array<{
    label: string;
    onClick: () => void;
  }>;
  toolCalls?: Array<{
    name: string;
    description: string;
  }>;
}

export function ChatMessage({ type, content, avatar, agentIcon, agentAvatarUrl, actions, toolCalls }: ChatMessageProps) {
  const isUser = type === 'user';

  // 60-30-10: User avatar (10% accent), AI avatar (30% secondary surface)
  const defaultAvatar = isUser ? (
    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[var(--primary)] to-[#ff8533] flex items-center justify-center shadow-lg shadow-[var(--primary)]/20">
      <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 256 256">
        <path d="M230.92,212c-15.23-26.33-38.7-45.21-66.09-54.16a72,72,0,1,0-73.66,0C63.78,166.78,40.31,185.66,25.08,212a8,8,0,1,0,13.85,8c18.84-32.56,52.14-52,89.07-52s70.23,19.44,89.07,52a8,8,0,1,0,13.85-8ZM72,96a56,56,0,1,1,56,56A56.06,56.06,0,0,1,72,96Z" />
      </svg>
    </div>
  ) : agentAvatarUrl ? (
    <img
      src={agentAvatarUrl}
      alt="Agent"
      className="w-8 h-8 rounded-full object-cover border-2 border-[var(--border-color)]"
    />
  ) : (
    <div className="w-8 h-8 rounded-full bg-[var(--surface)] border-2 border-[var(--border-color)] flex items-center justify-center p-1.5">
      <img src="/favicon.svg" alt="Tesslate" className="w-full h-full" />
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
          {typeof content === 'string' ? (
            <div>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  // Style paragraphs
                  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                  // Style lists
                  ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
                  li: ({ children }) => <li className="ml-2">{children}</li>,
                  // Style code
                  code: ({ children, ...props }) => {
                    const inline = !String(children).includes('\n');
                    return inline ? (
                      <code className="bg-black/20 px-1.5 py-0.5 rounded text-xs font-mono">{children}</code>
                    ) : (
                      <code className="block bg-black/20 px-3 py-2 rounded my-2 text-xs font-mono overflow-x-auto">{children}</code>
                    );
                  },
                  // Style links
                  a: ({ href, children }) => (
                    <a href={href} className="underline hover:opacity-80" target="_blank" rel="noopener noreferrer">
                      {children}
                    </a>
                  ),
                  // Style headings
                  h1: ({ children }) => <h1 className="text-xl font-bold mb-2 mt-3">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-lg font-bold mb-2 mt-3">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-base font-bold mb-2 mt-2">{children}</h3>,
                }}
              >
                {content}
              </ReactMarkdown>
            </div>
          ) : (
            content
          )}
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
