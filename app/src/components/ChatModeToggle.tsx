import React from 'react';
import { MessageSquare, Bot } from 'lucide-react';

interface ChatModeToggleProps {
  mode: 'stream' | 'agent';
  onChange: (mode: 'stream' | 'agent') => void;
  disabled?: boolean;
}

export default function ChatModeToggle({
  mode,
  onChange,
  disabled = false,
}: ChatModeToggleProps) {
  return (
    <div className="flex gap-2 mb-2">
      <button
        onClick={() => onChange('stream')}
        disabled={disabled}
        className={`flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
          mode === 'stream'
            ? 'bg-blue-500 text-white shadow-lg ring-2 ring-blue-300'
            : 'bg-white/50 text-gray-600 hover:bg-white/70'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
        title="Fast, real-time code generation"
      >
        <MessageSquare size={16} />
        Stream Mode
      </button>
      <button
        onClick={() => onChange('agent')}
        disabled={disabled}
        className={`flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
          mode === 'agent'
            ? 'bg-purple-500 text-white shadow-lg ring-2 ring-purple-300'
            : 'bg-white/50 text-gray-600 hover:bg-white/70'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
        title="Autonomous, multi-step execution"
      >
        <Bot size={16} />
        Agent Mode
      </button>
    </div>
  );
}
