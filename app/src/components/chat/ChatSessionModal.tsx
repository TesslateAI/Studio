import { useState, useMemo, useCallback, useEffect } from 'react';
import { X, MagnifyingGlass, Plus, ChatCircleDots } from '@phosphor-icons/react';

interface ChatSession {
  id: string;
  title: string | null;
  origin: string;
  status: string;
  created_at: string;
  updated_at: string | null;
  message_count: number;
}

interface ChatSessionModalProps {
  isOpen: boolean;
  onClose: () => void;
  sessions: ChatSession[];
  currentSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
}

const ORIGIN_LABELS: Record<string, string> = {
  browser: 'Browser',
  api: 'API',
  slack: 'Slack',
  cli: 'CLI',
};

const ORIGIN_COLORS: Record<string, string> = {
  browser: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
  api: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
  slack: 'bg-green-500/15 text-green-400 border-green-500/25',
  cli: 'bg-orange-500/15 text-orange-400 border-orange-500/25',
};

function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

/**
 * ChatSessionModal - Multi-session chat selector
 *
 * Shows a searchable list of chat sessions for the current project.
 * Each session displays: title, origin badge, status dot, message count.
 */
export function ChatSessionModal({
  isOpen,
  onClose,
  sessions,
  currentSessionId,
  onSelectSession,
  onNewSession,
}: ChatSessionModalProps) {
  const [searchQuery, setSearchQuery] = useState('');

  // Reset search when modal opens
  useEffect(() => {
    if (isOpen) {
      setSearchQuery('');
    }
  }, [isOpen]);

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  const filteredSessions = useMemo(() => {
    if (!searchQuery.trim()) return sessions;

    const query = searchQuery.toLowerCase();
    return sessions.filter((session) => {
      const title = (session.title || 'Untitled Chat').toLowerCase();
      return title.includes(query);
    });
  }, [sessions, searchQuery]);

  const handleSessionClick = useCallback(
    (sessionId: string) => {
      onSelectSession(sessionId);
      onClose();
    },
    [onSelectSession, onClose],
  );

  const handleNewSession = useCallback(() => {
    onNewSession();
    onClose();
  }, [onNewSession, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-[300]"
      onClick={onClose}
    >
      <div
        className="bg-[var(--surface)] rounded-3xl w-full max-w-lg shadow-2xl border border-[var(--border)] max-h-[80vh] flex flex-col animate-in fade-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-6 pb-4 border-b border-[var(--border)]">
          <h2 className="font-heading text-xl font-bold text-[var(--text)]">
            Chat Sessions
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors p-1.5 rounded-lg hover:bg-white/10"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Search + New Chat */}
        <div className="px-6 pt-4 pb-3 space-y-3">
          <div className="relative">
            <MagnifyingGlass className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text)]/40" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search sessions..."
              className="w-full bg-white/5 border border-[var(--border)] text-[var(--text)] pl-10 pr-4 py-2.5 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent transition-all placeholder:text-[var(--text)]/40"
              autoFocus
            />
          </div>

          <button
            onClick={handleNewSession}
            className="w-full flex items-center justify-center gap-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white py-2.5 rounded-xl font-semibold transition-all text-sm"
          >
            <Plus size={16} weight="bold" />
            New Chat
          </button>
        </div>

        {/* Session List */}
        <div className="flex-1 overflow-y-auto px-6 pb-6">
          {filteredSessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <ChatCircleDots className="w-10 h-10 text-[var(--text)]/20 mb-3" />
              <p className="text-sm text-[var(--text)]/40">
                {searchQuery.trim()
                  ? 'No sessions match your search.'
                  : 'No chat sessions yet.'}
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {filteredSessions.map((session) => {
                const isSelected = session.id === currentSessionId;
                const originKey = session.origin.toLowerCase();
                const originLabel =
                  ORIGIN_LABELS[originKey] || session.origin;
                const originColor =
                  ORIGIN_COLORS[originKey] ||
                  'bg-gray-500/15 text-gray-400 border-gray-500/25';
                const displayTime = formatRelativeTime(
                  session.updated_at || session.created_at,
                );

                return (
                  <button
                    key={session.id}
                    onClick={() => handleSessionClick(session.id)}
                    className={`
                      w-full text-left px-4 py-3 rounded-xl border transition-all
                      ${
                        isSelected
                          ? 'bg-[var(--primary)]/10 border-[var(--primary)]/30'
                          : 'bg-white/[0.02] border-[var(--border)] hover:bg-white/5 hover:border-[var(--border-hover)]'
                      }
                    `}
                  >
                    <div className="flex items-start gap-3">
                      {/* Status dot */}
                      <div className="mt-1.5 flex-shrink-0">
                        {session.status === 'running' && (
                          <span className="block w-2.5 h-2.5 rounded-full bg-green-400 shadow-[0_0_6px_rgba(74,222,128,0.5)]" />
                        )}
                        {session.status === 'waiting_approval' && (
                          <span className="block w-2.5 h-2.5 rounded-full bg-orange-400 shadow-[0_0_6px_rgba(251,146,60,0.5)]" />
                        )}
                        {session.status !== 'running' &&
                          session.status !== 'waiting_approval' && (
                            <span className="block w-2.5 h-2.5 rounded-full bg-transparent" />
                          )}
                      </div>

                      {/* Content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span
                            className={`text-sm font-medium truncate ${
                              isSelected
                                ? 'text-[var(--primary)]'
                                : 'text-[var(--text)]'
                            }`}
                          >
                            {session.title || 'Untitled Chat'}
                          </span>
                          <span
                            className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border flex-shrink-0 ${originColor}`}
                          >
                            {originLabel}
                          </span>
                        </div>

                        <div className="flex items-center gap-3 text-xs text-[var(--text)]/40">
                          <span>
                            {session.message_count}{' '}
                            {session.message_count === 1
                              ? 'message'
                              : 'messages'}
                          </span>
                          <span className="text-[var(--text)]/20">|</span>
                          <span>{displayTime}</span>
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
