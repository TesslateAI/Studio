import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

interface Agent {
  id: string;
  name: string;
  icon: string;  // Emoji string from backend
  active?: boolean;
  backendId?: number;  // Link to backend agent ID
  mode?: 'stream' | 'agent';
}

interface AgentSelectorProps {
  agents: Agent[];
  currentAgent: Agent;
  onSelectAgent: (agent: Agent) => void;
}

export function AgentSelector({ agents, currentAgent, onSelectAgent }: AgentSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSelect = (agent: Agent) => {
    onSelectAgent(agent);
    setIsOpen(false);
  };

  // Show placeholder if no agent selected
  if (!currentAgent || !currentAgent.name) {
    return (
      <div className="relative" ref={dropdownRef}>
        <button
          disabled
          className="
            agent-pill
            bg-[var(--primary)]/50 text-white/50
            px-3.5 py-2.5
            flex items-center gap-1.5
            transition-all
            text-xs font-medium
            flex-shrink-0
            rounded-l-2xl
            -ml-px -my-px
            relative z-[10000]
            cursor-wait
          "
        >
          <span className="text-xs">Loading agents...</span>
        </button>
      </div>
    );
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={(e) => {
          e.stopPropagation();
          setIsOpen(!isOpen);
        }}
        className="
          agent-pill
          bg-[var(--text)]/10 text-[var(--text)]
          flex items-center gap-1.5
          transition-all
          text-xs font-medium
          flex-shrink-0
          hover:bg-[var(--text)]/20
          active:bg-[var(--text)]/30
          relative z-[10000]
          h-8
          md:px-3.5 md:rounded-xl
          px-2.5 rounded-xl
          border-2 border-[var(--border-color)]
        "
        title={currentAgent.name}
      >
        <span className="text-sm">{currentAgent.icon}</span>
        <span className="hidden md:inline">{currentAgent.name}</span>
        <svg className="w-3 h-3 ml-0.5 hidden md:block" fill="currentColor" viewBox="0 0 256 256">
          <path d="M213.66,101.66l-80,80a8,8,0,0,1-11.32,0l-80-80A8,8,0,0,1,53.66,90.34L128,164.69l74.34-74.35a8,8,0,0,1,11.32,11.32Z" />
        </svg>
      </button>

      {isOpen && (
        <div
          className="
            agent-dropdown absolute bottom-full left-0 mb-2
            bg-[rgba(20,20,20,0.98)] backdrop-blur-xl
            border border-white/10 rounded-xl
            min-w-[300px] z-[10000]
            shadow-lg overflow-hidden
          "
        >
          <div className="px-4 py-2 text-xs text-gray-400 border-b border-white/5">
            PURCHASED AGENTS
          </div>

          {agents.map((agent) => (
            <button
              key={agent.id}
              onClick={() => handleSelect(agent)}
              className={`
                w-full px-4 py-3 flex items-center gap-3
                text-sm text-white transition-colors
                hover:bg-white/8
                ${agent.id === currentAgent.id && 'bg-[rgba(255,107,0,0.2)]'}
              `}
            >
              <span className="text-base">{agent.icon}</span>
              <span className="flex-1 text-left">{agent.name}</span>
              {agent.id === currentAgent.id && (
                <span className="text-xs text-green-400">Active</span>
              )}
            </button>
          ))}

          <div className="border-t border-white/10 p-3">
            <div className="bg-gradient-to-r from-orange-500/20 to-orange-600/20 rounded-lg p-3 border border-orange-500/30">
              <div className="flex items-center gap-2 mb-2">
                <svg className="w-4 h-4 text-yellow-400" fill="currentColor" viewBox="0 0 256 256">
                  <path d="M239.75,90.81c0,.11,0,.21-.05.32a15.94,15.94,0,0,1-8.32,12l-70.74,38.12,34.81,94a16.42,16.42,0,0,1-.93,13.38,15.94,15.94,0,0,1-12.21,7.73,16.86,16.86,0,0,1-5.18-.05,15.93,15.93,0,0,1-10.93-8.17L128,173.26,89.8,248.15a15.93,15.93,0,0,1-10.93,8.17,16.86,16.86,0,0,1-5.18.05,15.94,15.94,0,0,1-12.21-7.73,16.42,16.42,0,0,1-.93-13.38l34.81-94L24.62,103.13a15.94,15.94,0,0,1-8.32-12c0-.11,0-.21-.05-.32A16,16,0,0,1,26.71,75.68L109.18,64,147.24,8.12a16.1,16.1,0,0,1,28.52,0L213.82,64l82.47,11.68A16,16,0,0,1,239.75,90.81Z" />
                </svg>
                <span className="font-semibold text-sm text-white">Unlock More AI Agents</span>
              </div>
              <p className="text-xs text-gray-300 mb-3">
                Get specialized agents for React, Vue, Python, DevOps, and more!
              </p>
              <button
                onClick={() => {
                  setIsOpen(false);
                  navigate('/marketplace');
                }}
                className="w-full py-2 bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 rounded-lg text-white text-sm font-semibold transition-all"
              >
                Browse Marketplace
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
