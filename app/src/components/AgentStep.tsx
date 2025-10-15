import React from 'react';
import { Brain } from 'lucide-react';
import ToolBadge from './ToolBadge';
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
    <div className="agent-step bg-[var(--surface)]/30 rounded-lg p-3 border border-[var(--border-color)] hover:bg-[var(--surface)]/50 transition-colors">
      <div className="flex justify-between items-center mb-2">
        <span className="text-xs font-medium text-[var(--text)]/70">
          Step {step.iteration}/{totalSteps}
        </span>
        <span className="text-xs text-[var(--text)]/50">
          {formatTime(step.timestamp)}
        </span>
      </div>

      {step.thought && (
        <div className="flex items-start gap-2 p-2 bg-[var(--text)]/5 rounded-lg mb-2 border border-[var(--border-color)]">
          <Brain size={14} className="text-[hsl(var(--hue2)_60%_50%)] mt-0.5 flex-shrink-0" />
          <span className="text-xs text-[var(--text)]/80 italic leading-relaxed">{step.thought}</span>
        </div>
      )}

      {step.tool_calls && step.tool_calls.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {step.tool_calls.map((tool, idx) => (
            <ToolBadge key={idx} tool={tool} />
          ))}
        </div>
      )}

      {step.response_text && (
        <div className="text-xs text-[var(--text)]/70 leading-relaxed whitespace-pre-wrap">
          {step.response_text}
        </div>
      )}
    </div>
  );
}
