import { useContext } from 'react';
import { AgentRunsContext, type AgentRunsContextValue } from './agentRunsContext';

export function useAgentRuns(): AgentRunsContextValue {
  const ctx = useContext(AgentRunsContext);
  if (!ctx) {
    // Graceful no-op when the provider isn't mounted (e.g. standalone chat
    // pages that don't need cross-chat visibility).
    return {
      runs: new Map(),
      isRunning: () => false,
      focus: () => {},
      unfocus: () => {},
      register: () => {},
      markTerminal: () => {},
      refresh: async () => {},
    };
  }
  return ctx;
}
