import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { MagnifyingGlass, Plus, ChatCircleDots, PencilSimple, Trash } from '@phosphor-icons/react';
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
  api: 'bg-purple-500/20 text-purple-300',
  slack: 'bg-green-500/20 text-green-300',
  cli: 'bg-orange-500/20 text-orange-300',
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
          initial={{ opacity: 0, y: -8, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -8, scale: 0.97 }}
          transition={{ type: 'spring', damping: 25, stiffness: 350 }}
          className="absolute z-50 mt-2 w-[340px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-2xl bg-[var(--surface)]/95 backdrop-blur-xl shadow-2xl shadow-black/40 ring-1 ring-white/10"
          style={{ top: '100%', right: 0 }}
        >
          {/* Search bar */}
          {showSearch && (
            <div className="px-3 pt-3 pb-1">
              <div className="flex items-center gap-2 rounded-lg bg-white/[0.06] px-2.5 py-2">
                <MagnifyingGlass size={16} className="shrink-0 text-white/40" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search chats..."
                  className="w-full bg-transparent text-sm text-white/90 placeholder-white/30 outline-none"
                />
              </div>
            </div>
          )}

          {/* Session list */}
          <div className="max-h-[320px] overflow-y-auto py-1.5">
            {filteredSessions.length === 0 && sessions.length === 0 ? (
              /* Empty state */
              <div className="flex flex-col items-center gap-3 px-4 py-8">
                <ChatCircleDots size={40} className="text-white/20" />
                <p className="text-sm text-white/40">Start your first conversation</p>
                <button
                  onClick={() => {
                    onNewSession();
                    onClose();
                  }}
                  className="mt-1 flex items-center gap-2 rounded-lg bg-[var(--primary)]/20 px-4 py-2 text-sm font-medium text-[var(--primary)] transition-colors hover:bg-[var(--primary)]/30"
                >
                  <Plus size={16} weight="bold" />
                  New Chat
                </button>
              </div>
            ) : filteredSessions.length === 0 ? (
              <div className="px-4 py-6 text-center text-sm text-white/30">
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
                    className={`group relative flex cursor-pointer items-start gap-2.5 px-3 py-2.5 transition-all duration-150 ${
                      isSelected
                        ? 'border-l-[3px] border-l-[var(--primary)] bg-[var(--primary)]/[0.06]'
                        : 'border-l-[3px] border-l-transparent hover:bg-white/[0.06]'
                    }`}
                  >
                    {/* Status dot */}
                    {session.status === 'running' && (
                      <div className="mt-1.5 w-2 h-2 shrink-0 rounded-full bg-green-400 animate-pulse shadow-[0_0_8px_rgba(74,222,128,0.6)]" />
                    )}
                    {session.status === 'waiting_approval' && (
                      <div className="mt-1.5 w-2 h-2 shrink-0 rounded-full bg-orange-400 shadow-[0_0_8px_rgba(251,146,60,0.5)]" />
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
                            className="w-full border-b-2 border-[var(--primary)] bg-transparent text-sm text-white/90 outline-none"
                          />
                        ) : (
                          <span className="truncate text-sm font-medium text-white/90">
                            {session.title || 'Untitled'}
                          </span>
                        )}

                        {/* Origin badge */}
                        {session.origin !== 'browser' && originBadgeStyles[session.origin] && (
                          <span
                            className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded-full font-medium ${originBadgeStyles[session.origin]}`}
                          >
                            {session.origin}
                          </span>
                        )}
                      </div>

                      <div className="mt-0.5 flex items-center gap-2 text-[11px] text-white/30">
                        <span>
                          {session.message_count} message{session.message_count !== 1 ? 's' : ''}
                        </span>
                        <span>·</span>
                        <span>{formatRelativeTime(session.updated_at || session.created_at)}</span>
                      </div>
                    </div>

                    {/* Actions: rename + delete */}
                    {!isRenaming && (
                      <div className="flex items-center gap-0.5 shrink-0 opacity-0 transition-opacity duration-150 group-hover:opacity-100">
                        <button
                          onClick={(e) => startRename(e, session)}
                          className="mt-0.5 rounded p-1 hover:bg-white/10"
                        >
                          <PencilSimple size={14} className="text-white/50" />
                        </button>
                        {onDeleteSession && (sessionCount ?? sessions.length) > 1 && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onDeleteSession(session.id);
                            }}
                            className="mt-0.5 rounded p-1 hover:bg-red-500/20"
                          >
                            <Trash size={14} className="text-white/30 hover:text-red-400" />
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
            <div className="border-t border-white/[0.06] p-2">
              <button
                onClick={() => {
                  onNewSession();
                  onClose();
                }}
                className="flex w-full items-center gap-2.5 rounded-xl bg-gradient-to-r from-[var(--primary)]/10 to-transparent px-3 py-2.5 text-sm font-medium text-white/70 transition-all duration-150 hover:-translate-y-[1px] hover:text-white/90"
              >
                <Plus size={18} weight="bold" className="text-[var(--primary)]" />
                New Chat
              </button>
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
