import { Brain, CheckCircle, XCircle } from 'lucide-react';
import ToolCallDisplay from './ToolCallDisplay';
import { getToolIcon, getToolLabel } from './toolCallHelpers';
import AgentDebugPanel from './AgentDebugPanel';
import { type AgentStep as AgentStepType } from '../types/agent';

interface AgentStepProps {
  step: AgentStepType;
  totalSteps: number;
  toolCallsCollapsed?: boolean;
}

export default function AgentStep({ step, toolCallsCollapsed }: AgentStepProps) {
  // Collapsed view: render compact chip summary
  if (toolCallsCollapsed) {
    const hasToolCalls = step.tool_calls && step.tool_calls.length > 0;
    const hasThought = step.thought && step.thought.trim();

    return (
      <div className="agent-step flex flex-wrap gap-1.5 py-1">
        {hasToolCalls ? (
          step.tool_calls!.map((toolCall, idx) => {
            const success = toolCall.result?.success ?? false;
            const hasResult = toolCall.result !== undefined && toolCall.result !== null;
            return (
              <span
                key={idx}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-[var(--text)]/5 border border-[var(--border-color)] text-xs"
              >
                {getToolIcon(toolCall.name)}
                <span className="text-[var(--text)]/70">{getToolLabel(toolCall.name)}</span>
                {hasResult &&
                  (success ? (
                    <CheckCircle size={12} className="text-green-500" />
                  ) : (
                    <XCircle size={12} className="text-red-500" />
                  ))}
              </span>
            );
          })
        ) : hasThought ? (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-[var(--text)]/5 border border-[var(--border-color)] text-xs">
            <Brain size={12} className="text-[hsl(var(--hue2)_60%_50%)]" />
            <span className="text-[var(--text)]/70">Thinking</span>
          </span>
        ) : null}
      </div>
    );
  }

  // Expanded view: full tool call details
  return (
    <div className="agent-step bg-[var(--surface)]/30 rounded-lg p-3 border border-[var(--border-color)]">
      {/* Thought Process - Only show if there ARE tool calls */}
      {step.thought && step.tool_calls && step.tool_calls.length > 0 && (
        <div className="flex items-start gap-2 p-2.5 bg-[var(--text)]/5 rounded-lg mb-3 border border-[var(--border-color)]">
          <Brain size={14} className="text-[hsl(var(--hue2)_60%_50%)] mt-0.5 flex-shrink-0" />
          <div className="flex-1">
            <div className="text-xs font-medium text-[var(--text)]/60 mb-1">Thinking</div>
            <span className="text-xs text-[var(--text)]/90 leading-relaxed">{step.thought}</span>
          </div>
        </div>
      )}

      {/* Tool Calls */}
      {step.tool_calls && step.tool_calls.length > 0 ? (
        <div className="space-y-2">
          {step.tool_calls.map((toolCall, idx) => (
            <ToolCallDisplay key={idx} toolCall={toolCall} />
          ))}
        </div>
      ) : /* No tool calls - show the thought instead */
      step.thought ? (
        <div className="flex items-start gap-2 p-2.5 bg-[var(--text)]/5 rounded-lg border border-[var(--border-color)]">
          <Brain size={14} className="text-[hsl(var(--hue2)_60%_50%)] mt-0.5 flex-shrink-0" />
          <div className="flex-1">
            <span className="text-xs text-[var(--text)]/90 leading-relaxed">{step.thought}</span>
          </div>
        </div>
      ) : step._debug ? (
        /* No visible content, but has debug data - show minimal placeholder */
        <div className="p-2.5 bg-[var(--text)]/5 rounded-lg border border-[var(--border-color)]">
          <span className="text-xs text-[var(--text)]/60 italic">No visible output</span>
        </div>
      ) : (
        <div className="p-2.5 bg-[var(--text)]/5 rounded-lg border border-[var(--border-color)]">
          <span className="text-xs text-[var(--text)]/60 italic">No output for this iteration</span>
        </div>
      )}

      {/* Debug Panel - Only shown in development mode */}
      {step._debug && (
        <AgentDebugPanel
          iteration={step.iteration}
          debugData={step._debug}
          toolResults={step.tool_results}
        />
      )}
    </div>
  );
}
