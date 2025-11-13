import React, { useState } from 'react';
import { ChevronDown, ChevronRight, Bug, Copy, Check } from 'lucide-react';

interface DebugData {
  full_response?: string;
  context_messages_count?: number;
  context_messages?: Array<{ role: string; content: string }>;
  raw_tool_calls?: Array<{ name: string; params: any }>;
  raw_thought?: string;
  is_complete?: boolean;
  conversational_text?: string;
  display_text?: string;
}

interface ToolResult {
  success: boolean;
  tool: string;
  result?: any;
  error?: string;
}

interface AgentDebugPanelProps {
  iteration: number;
  debugData: DebugData;
  toolResults?: ToolResult[];
}

function ContextMessageItem({ index, message }: { index: number; message: { role: string; content: string } }) {
  const [isExpanded, setIsExpanded] = useState(false);

  const roleColors = {
    system: 'text-purple-400',
    user: 'text-green-400',
    assistant: 'text-blue-400',
  };

  const roleColor = roleColors[message.role as keyof typeof roleColors] || 'text-gray-400';

  // Truncate content for preview
  const preview = message.content.length > 150
    ? message.content.substring(0, 150) + '...'
    : message.content;

  return (
    <div className="bg-[var(--surface)] rounded border border-[var(--border-color)]">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-start gap-2 p-2 text-left hover:bg-[var(--hover)] transition-colors"
      >
        {isExpanded ? (
          <ChevronDown size={14} className="mt-0.5 flex-shrink-0" />
        ) : (
          <ChevronRight size={14} className="mt-0.5 flex-shrink-0" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[var(--text)]/50">#{index}</span>
            <span className={`font-semibold ${roleColor}`}>{message.role}</span>
            <span className="text-[var(--text)]/30 text-[10px]">
              ({message.content.length} chars)
            </span>
          </div>
          {!isExpanded && (
            <div className="text-[var(--text)]/50 text-[10px] truncate">
              {preview}
            </div>
          )}
        </div>
      </button>
      {isExpanded && (
        <div className="p-2 pt-0 border-t border-[var(--border-color)]">
          <div className="text-[var(--text)]/70 whitespace-pre-wrap text-[10px] max-h-96 overflow-y-auto">
            {message.content}
          </div>
        </div>
      )}
    </div>
  );
}

function formatDebugInfo(iteration: number, debugData: DebugData, toolResults?: ToolResult[]): string {
  const sections: string[] = [];

  sections.push('='.repeat(80));
  sections.push(`DEBUG INFO - ITERATION ${iteration}`);
  sections.push('='.repeat(80));
  sections.push('');

  // Is Complete
  sections.push(`Is Complete: ${debugData.is_complete ? 'Yes' : 'No'}`);
  sections.push('');

  // Context Messages
  if (debugData.context_messages && debugData.context_messages.length > 0) {
    sections.push('-'.repeat(80));
    sections.push(`CONTEXT MESSAGES (${debugData.context_messages_count || 0} total)`);
    sections.push('-'.repeat(80));
    debugData.context_messages.forEach((msg, idx) => {
      sections.push('');
      sections.push(`Message #${idx} [${msg.role.toUpperCase()}] (${msg.content.length} chars):`);
      sections.push('-'.repeat(40));
      sections.push(msg.content);
      sections.push('-'.repeat(40));
    });
    sections.push('');
  }

  // Raw Thought
  if (debugData.raw_thought) {
    sections.push('-'.repeat(80));
    sections.push('RAW THOUGHT');
    sections.push('-'.repeat(80));
    sections.push(debugData.raw_thought);
    sections.push('');
  }

  // Conversational Text
  if (debugData.conversational_text) {
    sections.push('-'.repeat(80));
    sections.push('CONVERSATIONAL TEXT (Extracted)');
    sections.push('-'.repeat(80));
    sections.push(debugData.conversational_text);
    sections.push('');
  }

  // Display Text
  if (debugData.display_text) {
    sections.push('-'.repeat(80));
    sections.push('DISPLAY TEXT (Shown to User)');
    sections.push('-'.repeat(80));
    sections.push(debugData.display_text);
    sections.push('');
  }

  // Raw Tool Calls
  if (debugData.raw_tool_calls && debugData.raw_tool_calls.length > 0) {
    sections.push('-'.repeat(80));
    sections.push(`RAW TOOL CALLS (${debugData.raw_tool_calls.length})`);
    sections.push('-'.repeat(80));
    debugData.raw_tool_calls.forEach((tc, idx) => {
      sections.push('');
      sections.push(`Tool Call #${idx + 1}: ${tc.name}`);
      sections.push('Parameters:');
      sections.push(JSON.stringify(tc.params, null, 2));
    });
    sections.push('');
  }

  // Tool Results
  if (toolResults && toolResults.length > 0) {
    sections.push('-'.repeat(80));
    sections.push(`TOOL RESULTS (${toolResults.length})`);
    sections.push('-'.repeat(80));
    toolResults.forEach((result, idx) => {
      sections.push('');
      sections.push(`Tool Result #${idx + 1}: ${result.tool} - ${result.success ? 'SUCCESS' : 'FAILED'}`);
      if (result.error) {
        sections.push(`Error: ${result.error}`);
      }
      if (result.result) {
        sections.push('Result:');
        sections.push(typeof result.result === 'string' ? result.result : JSON.stringify(result.result, null, 2));
      }
      sections.push('-'.repeat(40));
    });
    sections.push('');
  }

  // Full LLM Response
  if (debugData.full_response) {
    sections.push('-'.repeat(80));
    sections.push('FULL LLM RESPONSE');
    sections.push('-'.repeat(80));
    sections.push(debugData.full_response);
    sections.push('');
  }

  sections.push('='.repeat(80));
  sections.push('END DEBUG INFO');
  sections.push('='.repeat(80));

  return sections.join('\n');
}

export default function AgentDebugPanel({ iteration, debugData, toolResults }: AgentDebugPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isCopied, setIsCopied] = useState(false);

  // Only render in development mode
  const isDevelopment = import.meta.env.DEV;
  if (!isDevelopment) return null;

  const copyDebugInfo = async () => {
    const debugInfo = formatDebugInfo(iteration, debugData, toolResults);
    try {
      await navigator.clipboard.writeText(debugInfo);
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy debug info:', err);
    }
  };

  return (
    <div className="mt-2 border border-yellow-500/30 rounded-lg bg-yellow-500/5">
      {/* Header - Clickable to expand/collapse */}
      <div className="flex items-center gap-1 p-2">
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex-1 flex items-center gap-2 text-left hover:bg-yellow-500/10 transition-colors rounded px-1 py-0.5"
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
        <button
          onClick={copyDebugInfo}
          className="flex items-center gap-1.5 px-2 py-1 text-xs font-mono rounded bg-yellow-500/10 hover:bg-yellow-500/20 transition-colors border border-yellow-500/30"
          title="Copy all debug info"
        >
          {isCopied ? (
            <>
              <Check size={12} className="text-green-400" />
              <span className="text-green-400">Copied!</span>
            </>
          ) : (
            <>
              <Copy size={12} className="text-yellow-500" />
              <span className="text-yellow-500">Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Debug Data - Only shown when expanded */}
      {isExpanded && (
        <div className="p-3 space-y-3 text-xs font-mono border-t border-yellow-500/30">
          {/* Completion Status */}
          <div>
            <div className="text-yellow-500/70 font-semibold mb-1">Is Complete:</div>
            <div className="text-[var(--text)]/70">{debugData.is_complete ? 'Yes' : 'No'}</div>
          </div>

          {/* Context Messages */}
          <div>
            <div className="text-yellow-500/70 font-semibold mb-1">
              Context Messages ({debugData.context_messages_count || 0} total):
            </div>
            {debugData.context_messages && debugData.context_messages.length > 0 ? (
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {debugData.context_messages.map((msg, idx) => (
                  <ContextMessageItem key={idx} index={idx} message={msg} />
                ))}
              </div>
            ) : (
              <div className="text-[var(--text)]/50 italic">No context messages available</div>
            )}
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

          {/* Conversational Text */}
          {debugData.conversational_text && (
            <div>
              <div className="text-yellow-500/70 font-semibold mb-1">Conversational Text (Extracted):</div>
              <div className="text-[var(--text)]/70 bg-[var(--surface)] p-2 rounded border border-[var(--border-color)] whitespace-pre-wrap max-h-32 overflow-y-auto">
                {debugData.conversational_text}
              </div>
            </div>
          )}

          {/* Display Text */}
          {debugData.display_text && (
            <div>
              <div className="text-yellow-500/70 font-semibold mb-1">Display Text (Shown to User):</div>
              <div className="text-[var(--text)]/70 bg-[var(--surface)] p-2 rounded border border-[var(--border-color)] whitespace-pre-wrap max-h-32 overflow-y-auto">
                {debugData.display_text}
              </div>
            </div>
          )}

          {/* Raw Tool Calls */}
          {debugData.raw_tool_calls && debugData.raw_tool_calls.length > 0 && (
            <div>
              <div className="text-yellow-500/70 font-semibold mb-1">Raw Tool Calls ({debugData.raw_tool_calls.length}):</div>
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

          {/* Tool Results */}
          {toolResults && toolResults.length > 0 && (
            <div>
              <div className="text-yellow-500/70 font-semibold mb-1">Tool Results ({toolResults.length}):</div>
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {toolResults.map((result, idx) => (
                  <div
                    key={idx}
                    className={`bg-[var(--surface)] p-2 rounded border ${
                      result.success ? 'border-green-500/30' : 'border-red-500/30'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className={result.success ? 'text-green-400' : 'text-red-400'}>
                        {result.success ? '✓' : '✗'}
                      </span>
                      <span className="text-blue-400">{result.tool}</span>
                    </div>
                    {result.error && (
                      <div className="text-red-400/70 text-[10px] mb-1">
                        Error: {result.error}
                      </div>
                    )}
                    {result.result && (
                      <pre className="text-[var(--text)]/70 text-[10px] overflow-x-auto whitespace-pre-wrap">
                        {typeof result.result === 'string'
                          ? result.result
                          : JSON.stringify(result.result, null, 2)}
                      </pre>
                    )}
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
