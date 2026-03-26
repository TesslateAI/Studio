import React, { useState, useEffect, useCallback } from 'react';
import {
  ChevronRight,
  ChevronDown,
  AlertTriangle,
  Clock,
  Wrench,
  Brain,
  MessageSquare,
  X,
} from 'lucide-react';
import toast from 'react-hot-toast';
import { getAuthHeaders } from '../../lib/api';
import { LoadingSpinner } from '../PulsingGridSpinner';

interface StepData {
  step_index: number;
  iteration: number | null;
  thought: string | null;
  tool_calls: unknown[];
  tool_results: unknown[];
  response_text: string | null;
  timestamp: string | null;
}

interface AgentRunData {
  message: {
    id: string;
    chat_id: string;
    created_at: string;
    completion_reason: string | null;
    error: string | null;
    iterations: number;
    tool_calls_made: number;
    agent_type: string | null;
    task_id: string | null;
  };
  project: {
    id: string;
    name: string;
    slug: string;
  } | null;
  steps: StepData[];
}

interface AgentRunViewerProps {
  messageId: string;
  onClose: () => void;
}

function formatTimestamp(dateStr: string | null): string {
  if (!dateStr) return 'N/A';
  return new Date(dateStr).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatStepTime(dateStr: string | null): string {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function getCompletionBadge(reason: string | null): { label: string; className: string } {
  switch (reason) {
    case 'task_complete_signal':
      return { label: 'Completed', className: 'bg-green-500/20 text-green-400' };
    case 'error':
      return { label: 'Error', className: 'bg-red-500/20 text-red-400' };
    case 'cancelled':
      return { label: 'Cancelled', className: 'bg-yellow-500/20 text-yellow-400' };
    case 'resource_limit_exceeded':
      return { label: 'Resource Limit', className: 'bg-orange-500/20 text-orange-400' };
    case 'credit_deduction_failed':
      return { label: 'Credit Failed', className: 'bg-orange-500/20 text-orange-400' };
    default:
      return {
        label: reason || 'Unknown',
        className: 'bg-gray-500/20 text-gray-400',
      };
  }
}

function stepHasError(step: StepData): boolean {
  if (!step.tool_results || step.tool_results.length === 0) return false;
  return step.tool_results.some((result) => {
    if (typeof result === 'string') {
      return result.toLowerCase().includes('error');
    }
    if (result && typeof result === 'object') {
      return (
        result.error != null ||
        result.is_error === true ||
        (typeof result.content === 'string' && result.content.toLowerCase().includes('error'))
      );
    }
    return false;
  });
}

function formatResultContent(result: unknown): string {
  if (typeof result === 'string') return result;
  if (result == null) return '';
  return JSON.stringify(result, null, 2);
}

function TruncatedText({ text, limit = 500 }: { text: string; limit?: number }) {
  const [expanded, setExpanded] = useState(false);

  if (text.length <= limit) {
    return <span className="text-gray-300 whitespace-pre-wrap">{text}</span>;
  }

  return (
    <div>
      <span className="text-gray-300 whitespace-pre-wrap">
        {expanded ? text : text.slice(0, limit) + '...'}
      </span>
      <button
        onClick={() => setExpanded(!expanded)}
        className="ml-2 text-blue-400 hover:text-blue-300 text-sm font-medium transition-colors"
      >
        {expanded ? 'Show less' : 'Show more'}
      </button>
    </div>
  );
}

export default function AgentRunViewer({ messageId, onClose }: AgentRunViewerProps) {
  const [data, setData] = useState<AgentRunData | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());

  const fetchSteps = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(`/api/admin/agent-runs/${messageId}/steps`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) {
        const err = await response.json().catch(() => null);
        throw new Error(err?.detail || 'Failed to load agent run steps');
      }

      const result: AgentRunData = await response.json();
      setData(result);
    } catch (error) {
      console.error('Failed to load agent run steps:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to load agent run steps');
    } finally {
      setLoading(false);
    }
  }, [messageId]);

  useEffect(() => {
    fetchSteps();
  }, [fetchSteps]);

  const toggleStep = (index: number) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 rounded-lg border border-[var(--text)]/15 max-w-4xl w-full max-h-[85vh] overflow-y-auto">
        {/* Modal Header */}
        <div className="p-6 border-b border-[var(--text)]/15 flex items-center justify-between sticky top-0 bg-gray-800 z-10">
          <div className="flex items-center space-x-3">
            <Brain className="text-purple-400" size={24} />
            <h3 className="text-xl font-bold text-white">Agent Run Details</h3>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <LoadingSpinner message="Loading agent run..." size={60} />
            </div>
          ) : !data ? (
            <div className="text-center py-12 text-gray-400">Failed to load agent run data.</div>
          ) : (
            <>
              {/* Info Header */}
              <div className="bg-gray-700/50 rounded-lg p-4 space-y-4">
                <div className="flex flex-wrap items-center gap-3">
                  {/* Project name */}
                  <div className="text-white font-medium">
                    {data.project ? (
                      data.project.name
                    ) : (
                      <span className="text-gray-500 italic">No project</span>
                    )}
                  </div>

                  {/* Agent type badge */}
                  {data.message.agent_type && (
                    <span className="px-2 py-1 rounded text-xs bg-purple-500/20 text-purple-400">
                      {data.message.agent_type}
                    </span>
                  )}

                  {/* Completion reason badge */}
                  {(() => {
                    const badge = getCompletionBadge(data.message.completion_reason);
                    return (
                      <span className={`px-2 py-1 rounded text-xs ${badge.className}`}>
                        {badge.label}
                      </span>
                    );
                  })()}
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                  <div>
                    <div className="text-gray-400">Iterations</div>
                    <div className="text-white font-medium">{data.message.iterations}</div>
                  </div>
                  <div>
                    <div className="text-gray-400">Tool Calls</div>
                    <div className="text-white font-medium">{data.message.tool_calls_made}</div>
                  </div>
                  <div>
                    <div className="text-gray-400">Steps</div>
                    <div className="text-white font-medium">{data.steps.length}</div>
                  </div>
                  <div>
                    <div className="text-gray-400">Timestamp</div>
                    <div className="text-white font-medium">
                      {formatTimestamp(data.message.created_at)}
                    </div>
                  </div>
                </div>
              </div>

              {/* Error Banner */}
              {data.message.completion_reason === 'error' && data.message.error && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
                  <div className="flex items-start space-x-3">
                    <AlertTriangle className="text-red-400 mt-0.5 flex-shrink-0" size={18} />
                    <div>
                      <div className="text-red-400 font-medium text-sm mb-1">Error</div>
                      <div className="text-red-300 text-sm whitespace-pre-wrap">
                        {data.message.error}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Steps List */}
              {data.steps.length === 0 ? (
                <div className="text-center py-8 text-gray-400">
                  No steps recorded for this agent run.
                </div>
              ) : (
                <div className="space-y-2">
                  {data.steps.map((step, idx) => {
                    const isExpanded = expandedSteps.has(idx);
                    const hasError = stepHasError(step);

                    return (
                      <div
                        key={idx}
                        className={`bg-gray-700/50 rounded-lg border border-[var(--text)]/15 overflow-hidden ${
                          hasError ? 'border-l-2 border-l-red-500' : ''
                        }`}
                      >
                        {/* Step Header */}
                        <button
                          onClick={() => toggleStep(idx)}
                          className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-700/50 transition-colors text-left"
                        >
                          <div className="flex items-center space-x-3">
                            {isExpanded ? (
                              <ChevronDown size={16} className="text-gray-400 flex-shrink-0" />
                            ) : (
                              <ChevronRight size={16} className="text-gray-400 flex-shrink-0" />
                            )}
                            <span className="text-white font-medium text-sm">
                              Step {step.step_index + 1}
                            </span>
                            {step.tool_calls && step.tool_calls.length > 0 && (
                              <span className="text-gray-500 text-xs flex items-center space-x-1">
                                <Wrench size={12} />
                                <span>
                                  {step.tool_calls.length} tool call
                                  {step.tool_calls.length !== 1 ? 's' : ''}
                                </span>
                              </span>
                            )}
                            {hasError && <AlertTriangle size={14} className="text-red-400" />}
                          </div>
                          <div className="flex items-center space-x-2 text-gray-500 text-xs">
                            <Clock size={12} />
                            <span>{formatStepTime(step.timestamp)}</span>
                          </div>
                        </button>

                        {/* Step Content */}
                        {isExpanded && (
                          <div className="px-4 pb-4 space-y-4 border-t border-[var(--text)]/10">
                            {/* Thought */}
                            {step.thought && (
                              <div className="pt-3">
                                <div className="flex items-center space-x-2 mb-2">
                                  <Brain size={14} className="text-gray-400" />
                                  <span className="text-gray-400 text-sm font-medium">Thought</span>
                                </div>
                                <div className="bg-gray-900 rounded p-3 text-gray-300 text-sm whitespace-pre-wrap">
                                  {step.thought}
                                </div>
                              </div>
                            )}

                            {/* Tool Calls */}
                            {step.tool_calls && step.tool_calls.length > 0 && (
                              <div className="pt-1">
                                <div className="flex items-center space-x-2 mb-2">
                                  <Wrench size={14} className="text-gray-400" />
                                  <span className="text-gray-400 text-sm font-medium">
                                    Tool Calls
                                  </span>
                                </div>
                                <div className="space-y-2">
                                  {step.tool_calls.map(
                                    (call: Record<string, unknown>, callIdx: number) => (
                                      <div
                                        key={callIdx}
                                        className="bg-gray-900 rounded p-3 space-y-2"
                                      >
                                        <div className="text-blue-400 font-mono text-sm">
                                          {call.name ||
                                            call.function?.name ||
                                            call.tool ||
                                            'unknown'}
                                        </div>
                                        <div className="overflow-x-auto">
                                          <pre className="text-sm font-mono text-gray-300 whitespace-pre-wrap">
                                            {JSON.stringify(
                                              call.arguments ||
                                                call.parameters ||
                                                call.input ||
                                                call.function?.arguments ||
                                                {},
                                              null,
                                              2
                                            )}
                                          </pre>
                                        </div>
                                      </div>
                                    )
                                  )}
                                </div>
                              </div>
                            )}

                            {/* Tool Results */}
                            {step.tool_results && step.tool_results.length > 0 && (
                              <div className="pt-1">
                                <div className="flex items-center space-x-2 mb-2">
                                  <MessageSquare size={14} className="text-gray-400" />
                                  <span className="text-gray-400 text-sm font-medium">
                                    Tool Results
                                  </span>
                                </div>
                                <div className="space-y-2">
                                  {step.tool_results.map((result: unknown, resIdx: number) => {
                                    const content = formatResultContent(result);
                                    return (
                                      <div key={resIdx} className="bg-gray-900 rounded p-3">
                                        <TruncatedText text={content} limit={500} />
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                            )}

                            {/* Response */}
                            {step.response_text && (
                              <div className="pt-1">
                                <div className="flex items-center space-x-2 mb-2">
                                  <MessageSquare size={14} className="text-gray-400" />
                                  <span className="text-gray-400 text-sm font-medium">
                                    Response
                                  </span>
                                </div>
                                <div className="bg-gray-900 rounded p-3 text-gray-300 text-sm whitespace-pre-wrap">
                                  {step.response_text}
                                </div>
                              </div>
                            )}

                            {/* Empty step fallback */}
                            {!step.thought &&
                              (!step.tool_calls || step.tool_calls.length === 0) &&
                              (!step.tool_results || step.tool_results.length === 0) &&
                              !step.response_text && (
                                <div className="pt-3 text-gray-500 text-sm italic">
                                  No data recorded for this step.
                                </div>
                              )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-[var(--text)]/15 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
