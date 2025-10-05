import React, { useState } from 'react';
import { Bot, ChevronDown, ChevronUp, CheckCircle } from 'lucide-react';
import AgentStep from './AgentStep';
import { AgentMessageData } from '../types/agent';

interface AgentMessageProps {
  agentData: AgentMessageData;
  finalResponse: string;
}

export default function AgentMessage({ agentData, finalResponse }: AgentMessageProps) {
  const [showDetails, setShowDetails] = useState(false);

  return (
    <div className="flex justify-start">
      <div className="w-8 h-8 bg-purple-500 rounded-lg flex items-center justify-center shadow-md ring-1 ring-purple-200 mr-3 mt-1 flex-shrink-0">
        <Bot size={14} className="text-white" />
      </div>
      <div className="max-w-[80%] rounded-2xl bg-gradient-to-r from-purple-50 to-white border-l-4 border-purple-500 shadow-lg">
        {/* Header */}
        <div className="px-4 py-3 border-b border-purple-100">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bot size={16} className="text-purple-600" />
              <span className="text-sm font-semibold text-gray-800">AI Agent</span>
              <span className="px-2 py-0.5 bg-purple-500 text-white text-xs rounded-full font-medium">
                Agent Mode
              </span>
            </div>
            <div className="text-xs text-gray-500">
              {agentData.iterations} steps • {agentData.tool_calls_made} tools
            </div>
          </div>
        </div>

        {/* Execution Steps (Collapsible) */}
        {agentData.steps && agentData.steps.length > 0 && (
          <div className="px-4 py-3">
            <button
              onClick={() => setShowDetails(!showDetails)}
              className="flex items-center gap-2 text-sm font-medium text-purple-600 hover:text-purple-700 transition-colors"
            >
              {showDetails ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              {showDetails ? 'Hide' : 'View'} Execution Details
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

        {/* Final Response */}
        <div className="px-4 py-3">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle size={16} className="text-green-600" />
            <span className="text-sm font-semibold text-gray-800">Task Complete</span>
          </div>
          <div className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
            {finalResponse}
          </div>
          <div className="text-xs text-gray-500 mt-2">
            {new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </div>
        </div>

        {/* Completion Reason */}
        {agentData.completion_reason && (
          <div className="px-4 py-2 bg-purple-50 text-xs text-purple-700 border-t border-purple-100">
            Reason: {agentData.completion_reason}
          </div>
        )}
      </div>
    </div>
  );
}
