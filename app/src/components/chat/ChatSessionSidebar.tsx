import { useState, useRef, useEffect } from 'react';
import { SquarePen, MessageSquare, Trash2, Pencil, PanelLeftClose } from 'lucide-react';
import type { ChatSession } from '../../hooks/useChatSessions';

interface ChatSessionSidebarProps {
  sessions: ChatSession[];
  currentSessionId: string | null;
  isOpen: boolean;
  onToggle: () => void;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onRenameSession: (id: string, title: string) => void;
  onDeleteSession: (id: string) => void;
}

function groupByDate(sessions: ChatSession[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);

  const groups: { label: string; sessions: ChatSession[] }[] = [
    { label: 'Today', sessions: [] },
    { label: 'Yesterday', sessions: [] },
    { label: 'Previous 7 Days', sessions: [] },
    { label: 'Older', sessions: [] },
  ];

  for (const session of sessions) {
    const date = new Date(session.updated_at || session.created_at || '');
    if (date >= today) groups[0].sessions.push(session);
    else if (date >= yesterday) groups[1].sessions.push(session);
    else if (date >= weekAgo) groups[2].sessions.push(session);
    else groups[3].sessions.push(session);
  }

  return groups.filter((g) => g.sessions.length > 0);
}

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return 'now';
  if (diffMins < 60) return `${diffMins}m`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function ChatSessionSidebar({
  sessions,
  currentSessionId,
  onToggle,
  onSelectSession,
  onNewSession,
  onRenameSession,
  onDeleteSession,
}: ChatSessionSidebarProps) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const renameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (renamingId && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [renamingId]);

  const startRename = (session: ChatSession) => {
    setRenamingId(session.id);
    setRenameValue(session.title);
  };

  const commitRename = () => {
    if (renamingId && renameValue.trim()) {
      onRenameSession(renamingId, renameValue.trim());
    }
    setRenamingId(null);
    setRenameValue('');
  };

  const groups = groupByDate(sessions);

  return (
    <div className="flex-shrink-0 w-[260px] h-full flex flex-col border-r border-[var(--border)] bg-[var(--bg)]">
      {/* Header — height + padding mirrored on ChatTopBar so toggle/new
          buttons sit in the same place whether the sidebar is open or
          closed (no visual jump on toggle). */}
      <div
        className="flex items-center gap-1 h-10 border-b border-[var(--border)]"
        style={{ paddingLeft: 7, paddingRight: 10 }}
      >
        <button
          onClick={onToggle}
          className="flex items-center justify-center w-7 h-7 rounded-[var(--radius-small)] text-[var(--text-subtle)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
          aria-label="Close session sidebar"
        >
          <PanelLeftClose size={14} />
        </button>
        <button
          onClick={onNewSession}
          className="flex items-center justify-center w-7 h-7 rounded-[var(--radius-small)] text-[var(--text-subtle)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
          aria-label="New session"
        >
          <SquarePen size={14} />
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-1.5">
        {groups.length === 0 && (
          <div className="px-3 py-8 text-center">
            <MessageSquare size={20} className="mx-auto mb-2 text-[var(--text-subtle)]" />
            <p className="text-[11px] text-[var(--text-muted)]">No conversations yet</p>
          </div>
        )}

        {groups.map((group) => (
          <div key={group.label} className="mb-1">
            <div className="px-2 py-1.5">
              <span className="text-[10px] font-medium text-[var(--text-subtle)] uppercase tracking-wider">
                {group.label}
              </span>
            </div>
            {group.sessions.map((session) => (
              <div
                key={session.id}
                className={`group relative flex items-center gap-2 px-2 py-1.5 rounded-[var(--radius-small)] cursor-pointer transition-colors ${
                  session.id === currentSessionId
                    ? 'bg-[var(--surface-hover)]'
                    : 'hover:bg-[var(--surface-hover)]'
                }`}
                onClick={() => onSelectSession(session.id)}
              >
                {renamingId === session.id ? (
                  <input
                    ref={renameInputRef}
                    type="text"
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') commitRename();
                      if (e.key === 'Escape') {
                        setRenamingId(null);
                        setRenameValue('');
                      }
                    }}
                    onBlur={commitRename}
                    onClick={(e) => e.stopPropagation()}
                    className="flex-1 h-5 px-1 text-[11px] bg-[var(--surface)] border border-[var(--border-hover)] rounded text-[var(--text)] focus:outline-none"
                  />
                ) : (
                  <>
                    <span className="flex-1 text-[11px] text-[var(--text)] truncate">
                      {session.title}
                    </span>
                    {session.platform && (
                      <span className="ml-1 inline-flex items-center px-1.5 py-0.5 text-[9px] font-medium rounded-full bg-[var(--primary)]/10 text-[var(--primary)] flex-shrink-0">
                        {session.platform}
                      </span>
                    )}
                    <span className="text-[10px] text-[var(--text-subtle)] tabular-nums flex-shrink-0 hidden md:inline md:group-hover:hidden">
                      {formatRelativeTime(session.updated_at || session.created_at)}
                    </span>
                    {/* Hover actions */}
                    <div className="flex md:opacity-0 md:group-hover:opacity-100 items-center gap-0.5 flex-shrink-0 transition-opacity">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          startRename(session);
                        }}
                        className="p-0.5 rounded text-[var(--text-subtle)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-colors"
                        aria-label="Rename"
                      >
                        <Pencil size={11} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteSession(session.id);
                        }}
                        className="p-0.5 rounded text-[var(--text-subtle)] hover:text-[var(--status-error)] hover:bg-[var(--surface)] transition-colors"
                        aria-label="Delete"
                      >
                        <Trash2 size={11} />
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
