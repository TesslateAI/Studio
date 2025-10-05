import React from 'react';
import { Brain } from 'lucide-react';
import ToolBadge from './ToolBadge';
import { AgentStep as AgentStepType } from '../types/agent';

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
    <div className="agent-step bg-white rounded-lg p-4 mb-3 border border-purple-100 hover:shadow-md transition-shadow duration-200">
      <div className="flex justify-between items-center mb-2">
        <span className="text-sm font-semibold text-purple-600">
          Step {step.iteration}/{totalSteps}
        </span>
        <span className="text-xs text-gray-500">
          {formatTime(step.timestamp)}
        </span>
      </div>

      {step.thought && (
        <div className="flex items-start gap-2 p-3 bg-purple-50 rounded-lg mb-3 border border-purple-100">
          <Brain size={16} className="text-purple-600 mt-0.5 flex-shrink-0" />
          <span className="text-sm text-purple-900 italic">{step.thought}</span>
        </div>
      )}

      {step.tool_calls && step.tool_calls.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {step.tool_calls.map((tool, idx) => (
            <ToolBadge key={idx} tool={tool} />
          ))}
        </div>
      )}

      {step.response_text && (
        <div className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
          {step.response_text}
        </div>
      )}
    </div>
  );
}
