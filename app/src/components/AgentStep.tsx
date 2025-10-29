import React from 'react';
import { Brain } from 'lucide-react';
import ToolCallDisplay from './ToolCallDisplay';
import { type AgentStep as AgentStepType } from '../types/agent';

interface AgentStepProps {
  step: AgentStepType;
  totalSteps: number;
}

const formatTime = (timestamp: string) => {
  try {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '';
  }
};

export default function AgentStep({ step, totalSteps }: AgentStepProps) {
  return (
    <div className="agent-step bg-[var(--surface)]/30 rounded-lg p-3 border border-[var(--border-color)]">
      {/* Step Header */}
      <div className="flex justify-end items-center mb-3">
        <span className="text-xs text-[var(--text)]/50">
          {formatTime(step.timestamp)}
        </span>
      </div>

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
      ) : (
        /* No tool calls - show the thought instead */
        step.thought ? (
          <div className="flex items-start gap-2 p-2.5 bg-[var(--text)]/5 rounded-lg border border-[var(--border-color)]">
            <Brain size={14} className="text-[hsl(var(--hue2)_60%_50%)] mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <span className="text-xs text-[var(--text)]/90 leading-relaxed">{step.thought}</span>
            </div>
          </div>
        ) : (
          <div className="p-2.5 bg-[var(--text)]/5 rounded-lg border border-[var(--border-color)]">
            <span className="text-xs text-[var(--text)]/60 italic">
              No output for this iteration
            </span>
          </div>
        )
      )}
    </div>
  );
}
