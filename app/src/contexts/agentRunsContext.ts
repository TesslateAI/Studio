import { createContext } from 'react';

export type AgentRunStatus = 'running' | 'completed' | 'error' | 'superseded' | 'unknown';

export interface AgentRunState {
  taskId: string;
  chatId: string;
  status: AgentRunStatus;
  latestEvent?: unknown;
  startedAt: number;
  /** Opaque last-event id for SSE reconnect/replay. */
  lastEventId?: string;
}

export interface AgentRunsContextValue {
  /** Live state for every known running or recently-running chat. */
  runs: Map<string, AgentRunState>;
  /** True if this chat has an agent currently running. */
  isRunning: (chatId: string) => boolean;
  /** Bring a chat into the "focused" set so it's always subscribed. */
  focus: (chatId: string) => void;
  /** Remove focus from a chat (LRU may evict its stream). */
  unfocus: (chatId: string) => void;
  /** Manually register a task (e.g. immediately after sending a new message). */
  register: (chatId: string, taskId: string) => void;
  /** Mark a run terminal without waiting for the stream (e.g. on user stop). */
  markTerminal: (chatId: string, status: AgentRunStatus) => void;
  /** Force a cold-start sync with the server. */
  refresh: () => Promise<void>;
}

export const AgentRunsContext = createContext<AgentRunsContextValue | null>(null);
