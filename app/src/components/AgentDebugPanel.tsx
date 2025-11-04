import React, { useState } from 'react';
import { ChevronDown, ChevronRight, Bug } from 'lucide-react';

interface DebugData {
  full_response?: string;
  context_messages_count?: number;
  raw_tool_calls?: Array<{ name: string; params: any }>;
  raw_thought?: string;
  is_complete?: boolean;
}

interface AgentDebugPanelProps {
  iteration: number;
  debugData: DebugData;
}

export default function AgentDebugPanel({ iteration, debugData }: AgentDebugPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Only render in development mode
  const isDevelopment = import.meta.env.DEV;
  if (!isDevelopment) return null;

  return (
    <div className="mt-2 border border-yellow-500/30 rounded-lg bg-yellow-500/5">
      {/* Header - Clickable to expand/collapse */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2 p-2 text-left hover:bg-yellow-500/10 transition-colors rounded-t-lg"
      >
        {isExpanded ? (
          <ChevronDown size={16} className="text-yellow-500" />
        ) : (
          <ChevronRight size={16} className="text-yellow-500" />
        )}
        <Bug size={14} className="text-yellow-500" />
        <span className="text-xs font-mono text-yellow-500">
          DEBUG: Iteration {iteration}
        </span>
      </button>

      {/* Debug Data - Only shown when expanded */}
      {isExpanded && (
        <div className="p-3 space-y-3 text-xs font-mono border-t border-yellow-500/30">
          {/* Context Messages Count */}
          <div>
            <div className="text-yellow-500/70 font-semibold mb-1">Context Messages:</div>
            <div className="text-[var(--text)]/70">{debugData.context_messages_count || 0} messages</div>
          </div>

          {/* Completion Status */}
          <div>
            <div className="text-yellow-500/70 font-semibold mb-1">Is Complete:</div>
            <div className="text-[var(--text)]/70">{debugData.is_complete ? 'Yes' : 'No'}</div>
          </div>

          {/* Raw Thought */}
          {debugData.raw_thought && (
            <div>
              <div className="text-yellow-500/70 font-semibold mb-1">Raw Thought:</div>
              <div className="text-[var(--text)]/70 bg-[var(--surface)] p-2 rounded border border-[var(--border-color)] whitespace-pre-wrap max-h-32 overflow-y-auto">
                {debugData.raw_thought}
              </div>
            </div>
          )}

          {/* Raw Tool Calls */}
          {debugData.raw_tool_calls && debugData.raw_tool_calls.length > 0 && (
            <div>
              <div className="text-yellow-500/70 font-semibold mb-1">Raw Tool Calls:</div>
              <div className="space-y-2">
                {debugData.raw_tool_calls.map((tc, idx) => (
                  <div key={idx} className="bg-[var(--surface)] p-2 rounded border border-[var(--border-color)]">
                    <div className="text-blue-400 mb-1">{tc.name}</div>
                    <pre className="text-[var(--text)]/70 text-[10px] overflow-x-auto">
                      {JSON.stringify(tc.params, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Full Response */}
          {debugData.full_response && (
            <div>
              <div className="text-yellow-500/70 font-semibold mb-1">Full LLM Response:</div>
              <div className="text-[var(--text)]/70 bg-[var(--surface)] p-2 rounded border border-[var(--border-color)] whitespace-pre-wrap max-h-64 overflow-y-auto text-[10px]">
                {debugData.full_response}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
