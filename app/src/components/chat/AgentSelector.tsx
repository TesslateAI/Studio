import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { GearSix, CaretLeft, Check, MagnifyingGlass, Lightning } from '@phosphor-icons/react';
import { marketplaceApi } from '../../lib/api';
import { type ChatAgent } from '../../types/chat';

interface ModelInfo {
  id: string;
  name?: string;
  source?: string;
  provider?: string;
  provider_name?: string;
  pricing: { input: number; output: number } | null;
  health?: 'healthy' | 'unhealthy' | 'timeout' | null;
  disabled?: boolean;
  supports_vision?: boolean;
}

interface AgentSelectorProps {
  agents: ChatAgent[];
  currentAgent: ChatAgent;
  onSelectAgent: (agent: ChatAgent) => void;
  onModelChange?: (model: string) => void;
  /** When true, only shows the agent icon without name */
  compact?: boolean;
}

function AgentAvatar({ agent, size = 'sm' }: { agent: ChatAgent; size?: 'sm' | 'md' }) {
  const px = size === 'sm' ? 'w-5 h-5' : 'w-6 h-6';
  if (agent.avatar_url) {
    return (
      <img
        src={agent.avatar_url}
        alt=""
        className={`${px} rounded-full object-cover flex-shrink-0`}
      />
    );
  }
  return (
    <div
      className={`${px} rounded-full bg-[var(--surface)] border border-[var(--border-color)] flex items-center justify-center flex-shrink-0`}
    >
      <img src="/favicon.svg" alt="" className="w-3/4 h-3/4" />
    </div>
  );
}

/** Extract the raw model name from a full ID (e.g. "openai/gpt-4o" → "gpt-4o") */
function rawModelName(id: string): string {
  return id.split('/').pop() || id;
}

/** Convert USD per 1M tokens to credits (1 credit = $0.01) */
function formatCredits(usdPer1M: number): string {
  const credits = usdPer1M * 100;
  if (credits === 0) return '0';
  if (Number.isInteger(credits)) return credits.toLocaleString();
  return credits.toFixed(1);
}

function AgentConfigPanel({
  agent,
  onModelChange,
  onBack,
}: {
  agent: ChatAgent;
  onModelChange: (model: string) => void;
  onBack: () => void;
}) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [search, setSearch] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);

  const activeModel = agent.selectedModel || agent.model || '';

  useEffect(() => {
    let cancelled = false;
    const fetchModels = async () => {
      try {
        const data = await marketplaceApi.getAvailableModels();
        if (cancelled) return;
        const raw: unknown[] = Array.isArray(data) ? data : data.models || [];
        const modelList: ModelInfo[] = raw
          .map((m) => {
            if (typeof m === 'string') return { id: m, pricing: null };
            const obj = m as Record<string, unknown>;
            const id = obj.id as string;
            return id
              ? {
                  id,
                  name: (obj.name as string) ?? undefined,
                  provider: (obj.provider as string) ?? undefined,
                  provider_name: (obj.provider_name as string) ?? undefined,
                  pricing: (obj.pricing as { input: number; output: number }) || null,
                  health: (obj.health as ModelInfo['health']) ?? undefined,
                  disabled: (obj.disabled as boolean) ?? false,
                  supports_vision: (obj.supports_vision as boolean) ?? undefined,
                }
              : null;
          })
          .filter((m): m is ModelInfo => m !== null && !m.disabled);
        setModels(modelList);
      } catch (err) {
        console.error('Failed to fetch models:', err);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    fetchModels();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!isLoading && searchRef.current) {
      searchRef.current.focus();
    }
  }, [isLoading]);

  const filtered = search.trim()
    ? models.filter(
        (m) =>
          m.id.toLowerCase().includes(search.toLowerCase()) ||
          (m.name && m.name.toLowerCase().includes(search.toLowerCase())) ||
          (m.provider_name && m.provider_name.toLowerCase().includes(search.toLowerCase()))
      )
    : models;

  return (
    <>
      {/* Header */}
      <div className="px-3 py-2.5 flex items-center gap-2 border-b border-white/[0.06]">
        <button
          type="button"
          onClick={onBack}
          className="w-6 h-6 flex items-center justify-center rounded-md text-white/50 hover:text-white hover:bg-white/[0.08] transition-colors"
        >
          <CaretLeft size={14} weight="bold" />
        </button>
        <AgentAvatar agent={agent} size="sm" />
        <span className="text-xs text-white font-medium truncate flex-1">{agent.name}</span>
        <span className="text-[10px] text-white/30 uppercase tracking-wider">Model</span>
      </div>

      {/* Search */}
      <div className="px-3 py-2">
        <div className="relative">
          <MagnifyingGlass
            size={13}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/30"
          />
          <input
            ref={searchRef}
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search models..."
            className="w-full pl-8 pr-3 py-1.5 bg-white/[0.06] border border-white/[0.08] rounded-lg text-xs text-white placeholder-white/30 focus:outline-none focus:border-[var(--primary)]/40 transition-colors"
            onKeyDown={(e) => {
              if (e.key === 'Escape') onBack();
            }}
          />
        </div>
      </div>

      {/* Model list */}
      <div className="overflow-y-auto flex-1 min-h-0 py-1">
        {isLoading ? (
          <div className="px-4 py-8 text-center">
            <div className="inline-block w-4 h-4 border-2 border-white/20 border-t-[var(--primary)] rounded-full animate-spin mb-2" />
            <div className="text-xs text-white/40">Loading models...</div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <MagnifyingGlass size={20} className="mx-auto mb-2 text-white/20" />
            <div className="text-xs text-white/40">
              {search.trim() ? 'No models match your search' : 'No models available'}
            </div>
          </div>
        ) : (
          filtered.map((model) => {
            const isActive = model.id === activeModel;
            const name = model.name ? rawModelName(model.name) : rawModelName(model.id);
            const isFree =
              model.pricing != null && model.pricing.input === 0 && model.pricing.output === 0;

            return (
              <button
                key={model.id}
                type="button"
                onClick={() => onModelChange(model.id)}
                className={`w-full px-3 py-2 flex items-center gap-2.5 text-sm transition-colors group/model ${
                  isActive
                    ? 'bg-[var(--primary)]/10 text-white'
                    : 'text-white/70 hover:bg-white/[0.06]'
                }`}
              >
                <div
                  className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                    model.health === 'unhealthy' || model.health === 'timeout'
                      ? 'bg-red-400/70'
                      : model.health === 'healthy'
                        ? 'bg-emerald-400/70'
                        : isActive
                          ? 'bg-[var(--primary)]'
                          : 'bg-white/15 group-hover/model:bg-white/25'
                  }`}
                />
                <div className="flex-1 text-left min-w-0">
                  <div className="truncate text-[13px] leading-tight">{name}</div>
                  {model.pricing != null && (
                    <div className="text-[10px] mt-0.5 leading-tight">
                      {isFree ? (
                        <span className="text-green-400/70 inline-flex items-center gap-0.5">
                          <Lightning size={9} weight="fill" />
                          Free
                        </span>
                      ) : (
                        <span className="text-white/30">
                          {formatCredits(model.pricing.input)} /{' '}
                          {formatCredits(model.pricing.output)} credits per 1M
                        </span>
                      )}
                    </div>
                  )}
                </div>
                {isActive && (
                  <Check size={14} weight="bold" className="text-[var(--primary)] flex-shrink-0" />
                )}
              </button>
            );
          })
        )}
      </div>
    </>
  );
}

export function AgentSelector({
  agents,
  currentAgent,
  onSelectAgent,
  onModelChange,
  compact = false,
}: AgentSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [configAgent, setConfigAgent] = useState<ChatAgent | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  // Close dropdown on click outside or window losing focus (e.g. iframe click)
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
        setConfigAgent(null);
      }
    };
    const handleBlur = () => {
      setIsOpen(false);
      setConfigAgent(null);
    };

    document.addEventListener('mousedown', handleClickOutside);
    window.addEventListener('blur', handleBlur);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      window.removeEventListener('blur', handleBlur);
    };
  }, [isOpen]);

  const handleSelect = (agent: ChatAgent) => {
    onSelectAgent(agent);
    setIsOpen(false);
    setConfigAgent(null);
  };

  const handleConfigClick = (e: React.MouseEvent, agent: ChatAgent) => {
    e.stopPropagation();
    // Use currentAgent if clicking config for the already-active agent,
    // since it has the updated selectedModel
    const agentWithModel = agent.id === currentAgent.id ? currentAgent : agent;
    onSelectAgent(agentWithModel);
    setConfigAgent(agentWithModel);
  };

  const handleModelSelect = (model: string) => {
    onModelChange?.(model);
    setIsOpen(false);
    setConfigAgent(null);
  };

  // Show placeholder if no agent selected
  if (!currentAgent || !currentAgent.name) {
    return (
      <div className="relative" ref={dropdownRef} onFocus={(e) => e.stopPropagation()}>
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
    <div className="relative" ref={dropdownRef} onFocus={(e) => e.stopPropagation()}>
      <button
        onClick={(e) => {
          e.stopPropagation();
          setIsOpen(!isOpen);
          setConfigAgent(null);
        }}
        className={`
          agent-pill
          bg-[var(--surface)] text-[var(--text)]
          flex items-center gap-1.5
          transition-all
          text-xs font-medium
          flex-shrink-0
          hover:bg-[var(--surface-hover)]
          active:bg-[var(--border)]
          relative z-[10000]
          h-7
          rounded-full
          border border-[var(--border)]
          ${compact ? 'px-2' : 'px-3'}
        `}
        title={currentAgent.name}
      >
        <AgentAvatar agent={currentAgent} size="sm" />
        {!compact && <span className="truncate max-w-[100px]">{currentAgent.name}</span>}
        {!compact && (
          <svg className="w-3 h-3 ml-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 256 256">
            <path d="M213.66,101.66l-80,80a8,8,0,0,1-11.32,0l-80-80A8,8,0,0,1,53.66,90.34L128,164.69l74.34-74.35a8,8,0,0,1,11.32,11.32Z" />
          </svg>
        )}
      </button>

      {isOpen && (
        <div
          className="
            agent-dropdown absolute bottom-full left-0 mb-2
            bg-[var(--surface)]
            border border-[var(--border-hover)] rounded-[var(--radius-medium)]
            min-w-[300px] z-[10000]
            shadow-lg overflow-hidden
            flex flex-col
            max-h-[420px]
          "
        >
          {configAgent && onModelChange ? (
            <AgentConfigPanel
              agent={configAgent}
              onModelChange={handleModelSelect}
              onBack={() => setConfigAgent(null)}
            />
          ) : (
            <>
              <div className="px-4 py-2 text-xs text-gray-400 border-b border-white/5">
                PURCHASED AGENTS
              </div>

              <div className="overflow-y-auto flex-1 min-h-0">
                {agents.map((agent) => (
                  <button
                    key={agent.id}
                    onClick={() => handleSelect(agent)}
                    className={`
                      w-full px-3 py-2.5 flex items-center gap-3
                      text-xs text-[var(--text)] transition-colors
                      hover:bg-[var(--surface-hover)]
                      group/agent
                      ${agent.id === currentAgent.id && 'bg-[var(--surface-hover)]'}
                    `}
                  >
                    <AgentAvatar agent={agent} size="md" />
                    <span className="flex-1 text-left">{agent.name}</span>
                    {agent.id === currentAgent.id && (
                      <span className="text-xs text-green-400 group-hover/agent:hidden">
                        Active
                      </span>
                    )}
                    {onModelChange && (
                      <div
                        onClick={(e) => handleConfigClick(e, agent)}
                        role="button"
                        tabIndex={-1}
                        className={`
                          w-7 h-7 flex items-center justify-center rounded-lg
                          transition-all
                          text-white/30 hover:text-white hover:bg-white/10
                          ${agent.id === currentAgent.id ? 'hidden group-hover/agent:flex' : 'opacity-0 group-hover/agent:opacity-100'}
                        `}
                        title={`Configure ${agent.name}`}
                      >
                        <GearSix size={15} weight="bold" />
                      </div>
                    )}
                  </button>
                ))}
              </div>

              <div className="border-t border-[var(--border)] p-3">
                <div className="bg-[var(--surface-hover)] rounded-[var(--radius-medium)] p-3 border border-[var(--border)]">
                  <div className="flex items-center gap-2 mb-2">
                    <svg
                      className="w-4 h-4 text-yellow-400"
                      fill="currentColor"
                      viewBox="0 0 256 256"
                    >
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
                      setConfigAgent(null);
                      navigate('/marketplace');
                    }}
                    className="btn btn-primary w-full"
                  >
                    Browse Marketplace
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
