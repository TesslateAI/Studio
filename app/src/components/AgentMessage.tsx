import React, { useState, useEffect } from 'react';
import { ChevronDown, ChevronUp, Sparkles, Zap } from 'lucide-react';
import AgentStep from './AgentStep';
import { type AgentMessageData } from '../types/agent';

interface AgentMessageProps {
  agentData: AgentMessageData;
  finalResponse: string;
}

export default function AgentMessage({ agentData, finalResponse }: AgentMessageProps) {
  const [visibleSteps, setVisibleSteps] = useState(0);
  const [showAllSteps, setShowAllSteps] = useState(false);
  const [isExpanded, setIsExpanded] = useState(true);

  // Filter out steps with no meaningful content AND completion steps (shown in Result section)
  const meaningfulSteps = agentData.steps.filter(step =>
    !step.is_complete &&
    ((step.tool_calls && step.tool_calls.length > 0) || (step.thought && step.thought.trim().length > 0))
  );

  // Progressive display: show steps one by one with animation
  useEffect(() => {
    if (meaningfulSteps.length === 0) return;

    // Reset when agentData changes
    setVisibleSteps(0);
    setShowAllSteps(false);
    setIsExpanded(true);

    // Show steps progressively with a slight delay
    const showNextStep = (index: number) => {
      if (index < meaningfulSteps.length) {
        setTimeout(() => {
          setVisibleSteps(index + 1);
          showNextStep(index + 1);
        }, 150); // 150ms delay between each step for smooth appearance
      }
    };

    showNextStep(0);
  }, [meaningfulSteps.length]);

  const stepsToShow = showAllSteps ? meaningfulSteps : meaningfulSteps.slice(0, visibleSteps);

  return (
    <div className="message my-4 flex gap-3">
      {/* Avatar - matching streaming mode AI avatar */}
      <div className="message-avatar flex-shrink-0">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[hsl(var(--hue2)_60%_50%)] to-[hsl(var(--hue2)_60%_70%)] flex items-center justify-center shadow-lg">
          <Zap className="w-4 h-4 text-white" fill="currentColor" />
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 max-w-[75%]">
        {/* Agent mode indicator banner */}
        <div className="flex items-center gap-2 mb-2 px-3 py-2 rounded-lg bg-gradient-to-r from-[hsl(var(--hue2)_60%_50%)]/10 to-[hsl(var(--hue2)_60%_70%)]/10 border border-[hsl(var(--hue2)_60%_50%)]/20">
          <Sparkles size={14} className="text-[hsl(var(--hue2)_60%_50%)]" />
          <span className="text-xs font-semibold text-[var(--text)]">
            Agent Mode
          </span>
          <span className="text-xs text-[var(--text)]/60">•</span>
          <span className="text-xs text-[var(--text)]/70">
            {agentData.iterations} iteration{agentData.iterations !== 1 ? 's' : ''}
          </span>
          <span className="text-xs text-[var(--text)]/60">•</span>
          <span className="text-xs text-[var(--text)]/70">
            {agentData.tool_calls_made} tool call{agentData.tool_calls_made !== 1 ? 's' : ''}
          </span>
        </div>

        {/* Execution Steps - Progressive Display */}
        {meaningfulSteps && meaningfulSteps.length > 0 && (
          <div className="mb-3">
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="flex items-center gap-2 text-xs font-semibold text-[var(--text)]/70 hover:text-[var(--text)] transition-colors mb-2 px-2 py-1 rounded hover:bg-[var(--text)]/5"
            >
              {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              {isExpanded ? 'Hide' : 'Show'} execution details
            </button>

            {isExpanded && (
              <div className="space-y-2 animate-in fade-in duration-200">
                {stepsToShow.map((step, index) => (
                  <div
                    key={index}
                    className="animate-in slide-in-from-top-2 fade-in duration-300"
                    style={{ animationDelay: `${index * 50}ms` }}
                  >
                    <AgentStep
                      step={step}
                      totalSteps={agentData.iterations}
                    />
                  </div>
                ))}

                {/* Show More button if there are hidden steps */}
                {!showAllSteps && visibleSteps < meaningfulSteps.length && (
                  <button
                    onClick={() => setShowAllSteps(true)}
                    className="w-full text-xs font-medium text-[var(--text)]/60 hover:text-[var(--text)] transition-colors py-2 border border-dashed border-[var(--border-color)] rounded-lg hover:bg-[var(--text)]/5"
                  >
                    Show all {meaningfulSteps.length} steps
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        {/* Final Response */}
        <div className="message-bubble px-4 py-3 rounded-2xl text-sm leading-relaxed bg-[var(--text)]/5 text-[var(--text)] border border-[var(--border-color)]">
          <div className="text-xs font-semibold text-[var(--text)]/60 mb-2 uppercase tracking-wide">
            Result
          </div>
          <div className="whitespace-pre-wrap">
            {finalResponse}
          </div>
        </div>
      </div>
    </div>
  );
}
