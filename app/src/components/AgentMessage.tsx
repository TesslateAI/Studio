import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Sparkles } from 'lucide-react';
import AgentStep from './AgentStep';
import { type AgentMessageData } from '../types/agent';

interface AgentMessageProps {
  agentData: AgentMessageData;
  finalResponse: string;
}

export default function AgentMessage({ agentData, finalResponse }: AgentMessageProps) {
  const [showDetails, setShowDetails] = useState(false);

  return (
    <div className="message my-4 flex gap-3">
      {/* Avatar - matching streaming mode AI avatar */}
      <div className="message-avatar flex-shrink-0">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[hsl(var(--hue2)_60%_50%)] to-[hsl(var(--hue2)_60%_70%)] flex items-center justify-center">
          <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 256 256">
            <path d="M197.58,129.06,146,110l-19.06-51.58a15.92,15.92,0,0,0-29.88,0L78,110,26.42,129.06a15.92,15.92,0,0,0,0,29.88L78,178l19.06,51.58a15.92,15.92,0,0,0,29.88,0L146,178l51.58-19.06a15.92,15.92,0,0,0,0-29.88ZM137.75,142.25a16,16,0,0,0-9.5,9.5L112,193.58,95.75,151.75a16,16,0,0,0-9.5-9.5L44.42,128l41.83-14.25a16,16,0,0,0,9.5-9.5L112,62.42l16.25,41.83a16,16,0,0,0,9.5,9.5L179.58,128ZM248,80a8,8,0,0,1-8,8h-8v8a8,8,0,0,1-16,0V88h-8a8,8,0,0,1,0-16h8V64a8,8,0,0,1,16,0v8h8A8,8,0,0,1,248,80ZM152,40a8,8,0,0,1,8-8h8V24a8,8,0,0,1,16,0v8h8a8,8,0,0,1,0,16h-8v8a8,8,0,0,1-16,0V48h-8A8,8,0,0,1,152,40Z" />
          </svg>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 max-w-[75%]">
        {/* Main message bubble */}
        <div className="message-bubble px-4 py-3 rounded-2xl text-sm leading-relaxed bg-[var(--text)]/5 text-[var(--text)] border border-[var(--border-color)]">
          {/* Agent mode indicator */}
          <div className="flex items-center gap-2 mb-3 pb-2 border-b border-[var(--border-color)]">
            <Sparkles size={14} className="text-[hsl(var(--hue2)_60%_50%)]" />
            <span className="text-xs font-medium text-[var(--text)]/70">
              Agent Mode • {agentData.iterations} iterations • {agentData.tool_calls_made} tool calls
            </span>
          </div>

          {/* Final response */}
          <div className="whitespace-pre-wrap">
            {finalResponse}
          </div>

          {/* Execution details toggle */}
          {agentData.steps && agentData.steps.length > 0 && (
            <div className="mt-3 pt-3 border-t border-[var(--border-color)]">
              <button
                onClick={() => setShowDetails(!showDetails)}
                className="flex items-center gap-2 text-xs font-medium text-[var(--text)]/60 hover:text-[var(--text)] transition-colors"
              >
                {showDetails ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                {showDetails ? 'Hide' : 'Show'} execution steps
              </button>

              {showDetails && (
                <div className="mt-3 space-y-2">
                  {agentData.steps.map((step, index) => (
                    <AgentStep
                      key={index}
                      step={step}
                      totalSteps={agentData.iterations}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
