import React from 'react';
import { Zap } from 'lucide-react';
import AgentStep from './AgentStep';
import { type AgentMessageData } from '../types/agent';

interface AgentMessageProps {
  agentData: AgentMessageData;
  finalResponse: string;
  agentIcon?: string;
}

export default function AgentMessage({ agentData, finalResponse, agentIcon }: AgentMessageProps) {
  // In development, show all steps (to display debug panels)
  // In production, only show steps with meaningful content
  const isDevelopment = import.meta.env.DEV;

  const stepsToDisplay = agentData.steps.filter(step => {
    if (step.is_complete) return false;

    // In dev mode, show steps that have debug data even if no tool calls/thoughts
    if (isDevelopment && step._debug) return true;

    // Always show steps with tool calls or thoughts
    return (step.tool_calls && step.tool_calls.length > 0) || (step.thought && step.thought.trim());
  });

  return (
    <div className="message my-4 flex gap-3">
      {/* Avatar - use agent icon or default */}
      <div className="message-avatar flex-shrink-0">
        <div className="w-8 h-8 rounded-full bg-[var(--surface)] border border-[var(--border-color)] flex items-center justify-center">
          {agentIcon ? (
            <span className="text-base leading-none">{agentIcon}</span>
          ) : (
            <Zap className="w-4 h-4 text-[var(--text)]" fill="currentColor" />
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 max-w-[75%]">
        {/* Execution Steps */}
        {stepsToDisplay && stepsToDisplay.length > 0 && (
          <div className="space-y-2">
            {stepsToDisplay.map((step, index) => (
              <AgentStep
                key={index}
                step={step}
                totalSteps={agentData.iterations}
              />
            ))}
          </div>
        )}

        {/* In Progress Indicator - Just animated dots */}
        {agentData.completion_reason === 'in_progress' && stepsToDisplay.length === 0 && (
          <div className="inline-flex gap-1 px-3 py-2 bg-white/5 rounded-2xl">
            <div className="w-2 h-2 rounded-full bg-gray-500 animate-typing"></div>
            <div className="w-2 h-2 rounded-full bg-gray-500 animate-typing animation-delay-200"></div>
            <div className="w-2 h-2 rounded-full bg-gray-500 animate-typing animation-delay-400"></div>
          </div>
        )}

        {/* Final Response - Only shown when task is complete */}
        {finalResponse && finalResponse.trim() && (
          <div className="mt-2">
            <div className="message-bubble px-4 py-3 rounded-2xl text-sm leading-relaxed bg-[var(--text)]/5 text-[var(--text)] border border-[var(--border-color)]">
              {finalResponse}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
