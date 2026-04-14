import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { MagnifyingGlass, Plus, ChatCircleDots, PencilSimple, Trash, X } from '@phosphor-icons/react';
import { AnimatePresence, motion } from 'framer-motion';

interface ChatSession {
  id: string;
  title: string | null;
  origin: string;
  status: string;
  created_at: string;
  updated_at: string | null;
  message_count: number;
}

interface ChatSessionPopoverProps {
  isOpen: boolean;
  onClose: () => void;
  sessions: ChatSession[];
  currentSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
  onRenameSession: (sessionId: string, newTitle: string) => void;
  onDeleteSession?: (sessionId: string) => void;
  sessionCount?: number;
  anchorRef: React.RefObject<HTMLButtonElement | null>;
}

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
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

const originBadgeStyles: Record<string, string> = {
  api: 'bg-[var(--surface-hover)] text-[var(--text-muted)]',
  slack: 'bg-[var(--surface-hover)] text-[var(--text-muted)]',
  cli: 'bg-[var(--surface-hover)] text-[var(--text-muted)]',
};

export function ChatSessionPopover({
  isOpen,
  onClose,
  sessions,
  currentSessionId,
  onSelectSession,
  onNewSession,
  onRenameSession,
  onDeleteSession,
  sessionCount,
  anchorRef,
}: ChatSessionPopoverProps) {
  const [search, setSearch] = useState('');
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const popoverRef = useRef<HTMLDivElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  const filteredSessions = useMemo(() => {
    if (!search.trim()) return sessions;
    const q = search.toLowerCase();
    return sessions.filter((s) => (s.title || 'Untitled').toLowerCase().includes(q));
  }, [sessions, search]);

  const showSearch = sessions.length >= 4;

  const handleClickOutside = useCallback(
    (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node) &&
        anchorRef.current &&
        !anchorRef.current.contains(e.target as Node)
      ) {
        onClose();
      }
    },
    [onClose, anchorRef]
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen, handleClickOutside]);

  useEffect(() => {
    if (!isOpen) {
      setSearch('');
      setRenamingId(null);
    }
  }, [isOpen]);

  useEffect(() => {
    if (renamingId && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [renamingId]);

  const startRename = useCallback((e: React.MouseEvent, session: ChatSession) => {
    e.stopPropagation();
    setRenamingId(session.id);
    setRenameValue(session.title || '');
  }, []);

  const commitRename = useCallback(() => {
    if (renamingId && renameValue.trim()) {
      onRenameSession(renamingId, renameValue.trim());
    }
    setRenamingId(null);
  }, [renamingId, renameValue, onRenameSession]);

  const cancelRename = useCallback(() => {
    setRenamingId(null);
  }, []);

  const handleRenameKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        commitRename();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        cancelRename();
      }
    },
    [commitRename, cancelRename]
  );

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          ref={popoverRef}
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.15, ease: 'easeOut' }}
          className="absolute z-50 mt-1 w-[320px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-[var(--radius-medium)] bg-[var(--surface)] border flex flex-col"
          style={{ top: '100%', right: 0, borderWidth: 'var(--border-width)', borderColor: 'var(--border-hover)', maxHeight: '420px' }}
        >
          {/* Search bar */}
          {showSearch && (
            <div className="px-3 pt-3 pb-1 flex-shrink-0">
              <div className="relative">
                <MagnifyingGlass size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-subtle)]" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search sessions..."
                  className="w-full pl-8 pr-8 py-1.5 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)] placeholder-[var(--text-subtle)] focus:outline-none focus:border-[var(--border-hover)] transition-colors"
                />
                {search && (
                  <button
                    type="button"
                    onClick={() => setSearch('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-subtle)] hover:text-[var(--text-muted)] transition-colors"
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Session list */}
          <div className="flex-1 overflow-y-auto py-1">
            {filteredSessions.length === 0 && sessions.length === 0 ? (
              /* Empty state */
              <div className="flex flex-col items-center gap-2 px-4 py-8">
                <ChatCircleDots size={28} className="text-[var(--text-subtle)]" />
                <p className="text-xs text-[var(--text-muted)]">Start your first conversation</p>
                <button
                  onClick={() => {
                    onNewSession();
                    onClose();
                  }}
                  className="btn btn-filled mt-1"
                >
                  <Plus size={14} weight="bold" />
                  New Chat
                </button>
              </div>
            ) : filteredSessions.length === 0 ? (
              <div className="px-4 py-6 text-center text-xs text-[var(--text-subtle)]">
                No chats matching "{search}"
              </div>
            ) : (
              filteredSessions.map((session) => {
                const isSelected = session.id === currentSessionId;
                const isRenaming = session.id === renamingId;

                return (
                  <div
                    key={session.id}
                    onClick={() => {
                      if (!isRenaming) {
                        onSelectSession(session.id);
                        onClose();
                      }
                    }}
                    className={`group relative flex cursor-pointer items-start gap-2 px-3 py-2 mx-1 rounded-[var(--radius-small)] transition-colors ${
                      isSelected
                        ? 'bg-[var(--surface-hover)]'
                        : 'hover:bg-[var(--surface-hover)]'
                    }`}
                  >
                    {/* Status dot */}
                    {session.status === 'running' && (
                      <span className="mt-1.5 w-1.5 h-1.5 shrink-0 rounded-full bg-[var(--status-success)] animate-pulse" />
                    )}
                    {session.status === 'waiting_approval' && (
                      <span className="mt-1.5 w-1.5 h-1.5 shrink-0 rounded-full bg-[var(--status-warning)]" />
                    )}

                    {/* Content */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        {isRenaming ? (
                          <input
                            ref={renameInputRef}
                            type="text"
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            onKeyDown={handleRenameKeyDown}
                            onBlur={commitRename}
                            onClick={(e) => e.stopPropagation()}
                            className="w-full bg-transparent border-b border-[var(--primary)] text-xs text-[var(--text)] outline-none"
                          />
                        ) : (
                          <span className={`truncate text-xs font-medium ${isSelected ? 'text-[var(--text)]' : 'text-[var(--text-muted)]'}`}>
                            {session.title || 'Untitled'}
                          </span>
                        )}

                        {/* Origin badge */}
                        {session.origin !== 'browser' && originBadgeStyles[session.origin] && (
                          <span
                            className={`shrink-0 text-[9px] px-1.5 py-px rounded-full font-medium ${originBadgeStyles[session.origin]}`}
                          >
                            {session.origin}
                          </span>
                        )}
                      </div>

                      <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-[var(--text-subtle)]">
                        <span>
                          {session.message_count} msg{session.message_count !== 1 ? 's' : ''}
                        </span>
                        <span className="opacity-40">·</span>
                        <span>{formatRelativeTime(session.updated_at || session.created_at)}</span>
                      </div>
                    </div>

                    {/* Actions: rename + delete */}
                    {!isRenaming && (
                      <div className="flex items-center gap-0.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100">
                        <button
                          onClick={(e) => startRename(e, session)}
                          className="btn btn-icon btn-sm"
                        >
                          <PencilSimple size={12} />
                        </button>
                        {onDeleteSession && (sessionCount ?? sessions.length) > 1 && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onDeleteSession(session.id);
                            }}
                            className="btn btn-icon btn-sm btn-danger"
                          >
                            <Trash size={12} />
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* New Chat button */}
          {(sessions.length > 0 || filteredSessions.length > 0) && (
            <div className="border-t border-[var(--border)] p-1.5 flex-shrink-0">
              <button
                onClick={() => {
                  onNewSession();
                  onClose();
                }}
                className="btn w-full"
              >
                <Plus size={14} weight="bold" className="text-[var(--primary)]" />
                New Chat
              </button>
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
