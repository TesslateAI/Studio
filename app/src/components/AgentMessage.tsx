import React from 'react';
import { Zap } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import AgentStep from './AgentStep';
import { type AgentMessageData } from '../types/agent';

interface AgentMessageProps {
  agentData: AgentMessageData;
  finalResponse: string;
  agentIcon?: string;
  agentAvatarUrl?: string;
}

export default function AgentMessage({ agentData, finalResponse, agentIcon, agentAvatarUrl }: AgentMessageProps) {
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
      {/* Avatar - use agent logo, icon, or default */}
      <div className="message-avatar flex-shrink-0">
        {agentAvatarUrl ? (
          <img
            src={agentAvatarUrl}
            alt="Agent"
            className="w-8 h-8 rounded-full object-cover border border-[var(--border-color)]"
          />
        ) : (
          <div className="w-8 h-8 rounded-full bg-[var(--surface)] border border-[var(--border-color)] flex items-center justify-center p-1.5">
            <img src="/favicon.svg" alt="Tesslate" className="w-full h-full" />
          </div>
        )}
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
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  // Style paragraphs
                  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                  // Style lists
                  ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
                  li: ({ children }) => <li className="ml-2">{children}</li>,
                  // Style code
                  code: ({ children, ...props }) => {
                    const inline = !String(children).includes('\n');
                    return inline ? (
                      <code className="bg-black/20 px-1.5 py-0.5 rounded text-xs font-mono">{children}</code>
                    ) : (
                      <code className="block bg-black/20 px-3 py-2 rounded my-2 text-xs font-mono overflow-x-auto">{children}</code>
                    );
                  },
                  // Style links
                  a: ({ href, children }) => (
                    <a href={href} className="underline hover:opacity-80" target="_blank" rel="noopener noreferrer">
                      {children}
                    </a>
                  ),
                  // Style headings
                  h1: ({ children }) => <h1 className="text-xl font-bold mb-2 mt-3">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-lg font-bold mb-2 mt-3">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-base font-bold mb-2 mt-2">{children}</h3>,
                }}
              >
                {finalResponse}
              </ReactMarkdown>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
