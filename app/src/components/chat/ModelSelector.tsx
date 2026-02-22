import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { Cpu, MagnifyingGlass, CaretDown, Check, Lightning } from '@phosphor-icons/react';
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
}

interface ModelSelectorProps {
  currentAgent: ChatAgent;
  onModelChange: (model: string) => void;
  compact?: boolean;
  /** When true (default), dropdown opens upward; when false, opens downward */
  dropUp?: boolean;
}

/** Extract the raw model name from a full ID (e.g. "openai/gpt-4o" → "gpt-4o") */
function rawModelName(id: string): string {
  const parts = id.split('/');
  return parts[parts.length - 1];
}

/** Compact display for the trigger button */
function formatButtonLabel(model: ModelInfo): string {
  const label = getProviderLabel(model.provider || 'internal', model.provider_name);
  const name = model.name ? rawModelName(model.name) : rawModelName(model.id);
  return `${label}/${name}`;
}

/** Get a friendly provider label */
function getProviderLabel(provider: string, providerName?: string): string {
  if (providerName) return providerName;
  const labels: Record<string, string> = {
    internal: 'Tesslate',
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    groq: 'Groq',
    together: 'Together AI',
    deepseek: 'DeepSeek',
    fireworks: 'Fireworks',
    openrouter: 'OpenRouter',
    'nano-gpt': 'NanoGPT',
  };
  return labels[provider] || provider.charAt(0).toUpperCase() + provider.slice(1);
}

/** Provider sort order — system first, then alphabetical */
function providerOrder(provider: string): number {
  const order: Record<string, number> = { internal: 0, openai: 1, anthropic: 2 };
  return order[provider] ?? 10;
}

export function ModelSelector({
  currentAgent,
  onModelChange,
  compact = false,
  dropUp = true,
}: ModelSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [hasFetched, setHasFetched] = useState(false);
  const lastFetchedAt = useRef<number>(0);
  const [search, setSearch] = useState('');
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const activeModel = currentAgent.selectedModel || currentAgent.model || '';
  const isReadOnly = currentAgent.sourceType === 'closed' && !currentAgent.isCustom;

  // Close dropdown on click outside or window losing focus
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleBlur = () => setIsOpen(false);

    document.addEventListener('mousedown', handleClickOutside);
    window.addEventListener('blur', handleBlur);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      window.removeEventListener('blur', handleBlur);
    };
  }, [isOpen]);

  // Focus search on open
  useEffect(() => {
    if (isOpen && searchRef.current) {
      setTimeout(() => searchRef.current?.focus(), 50);
    }
    if (!isOpen) {
      setSearch('');
      setActiveTab(null);
    }
  }, [isOpen]);

  // Fetch models on first open
  const handleToggle = useCallback(async () => {
    if (isReadOnly) return;

    if (isOpen) {
      setIsOpen(false);
      return;
    }

    setIsOpen(true);

    // Refetch if never fetched or if data is stale (>5 min)
    const STALE_MS = 5 * 60 * 1000;
    const isStale = Date.now() - lastFetchedAt.current > STALE_MS;

    if (!hasFetched || isStale) {
      if (!hasFetched) setIsLoading(true);
      try {
        const data = await marketplaceApi.getAvailableModels();
        const raw: unknown[] = Array.isArray(data) ? data : data.models || [];
        const modelList: ModelInfo[] = raw
          .map((m) => {
            if (typeof m === 'string') return { id: m, pricing: null };
            const obj = m as Record<string, unknown>;
            const id = obj.id as string;
            const pricing = (obj.pricing as { input: number; output: number }) || null;
            return id
              ? {
                  id,
                  name: (obj.name as string) ?? undefined,
                  source: (obj.source as string) ?? undefined,
                  provider: (obj.provider as string) ?? undefined,
                  provider_name: (obj.provider_name as string) ?? undefined,
                  pricing,
                  health: (obj.health as ModelInfo['health']) ?? undefined,
                }
              : null;
          })
          .filter((m): m is ModelInfo => m !== null);
        setModels(modelList);
        setHasFetched(true);
        lastFetchedAt.current = Date.now();
      } catch (error) {
        console.error('Failed to fetch models:', error);
      } finally {
        setIsLoading(false);
      }
    }
  }, [isOpen, isReadOnly, hasFetched]);

  const handleSelect = (model: string) => {
    onModelChange(model);
    setIsOpen(false);
  };

  // Build display list: ensure current model is always visible
  const allModels = useMemo(() => {
    if (!hasFetched) return [];
    const list = [...models];
    if (activeModel && !list.some((m) => m.id === activeModel)) {
      list.unshift({ id: activeModel, pricing: null, provider: 'internal' });
    }
    return list;
  }, [hasFetched, models, activeModel]);

  // Get unique providers for tabs
  const providers = useMemo(() => {
    const seen = new Map<string, string>();
    for (const m of allModels) {
      const p = m.provider || 'internal';
      if (!seen.has(p)) {
        seen.set(p, getProviderLabel(p, m.provider_name));
      }
    }
    return Array.from(seen.entries())
      .map(([id, label]) => ({ id, label }))
      .sort((a, b) => providerOrder(a.id) - providerOrder(b.id));
  }, [allModels]);

  // Filter models by search + active tab
  const filteredModels = useMemo(() => {
    let filtered = allModels;

    if (activeTab) {
      filtered = filtered.filter((m) => (m.provider || 'internal') === activeTab);
    }

    if (search.trim()) {
      const q = search.toLowerCase();
      filtered = filtered.filter(
        (m) =>
          m.id.toLowerCase().includes(q) ||
          (m.name && m.name.toLowerCase().includes(q)) ||
          (m.provider_name && m.provider_name.toLowerCase().includes(q))
      );
    }

    return filtered;
  }, [allModels, activeTab, search]);

  // Find the active model's info for button label
  const activeModelInfo = useMemo(() => {
    if (allModels.length > 0) {
      const found = allModels.find((m) => m.id === activeModel);
      if (found) return found;
    }
    // Derive provider from model ID prefix (e.g. "asdf/glm-5" → provider "asdf")
    const slashIdx = activeModel.indexOf('/');
    const fallbackProvider = slashIdx > 0 ? activeModel.substring(0, slashIdx) : 'internal';
    return { id: activeModel, pricing: null, provider: fallbackProvider } as ModelInfo;
  }, [allModels, activeModel]);

  // No model info at all — hide the selector
  if (!activeModel) return null;

  return (
    <div className="relative" ref={dropdownRef} onFocus={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          handleToggle();
        }}
        disabled={isReadOnly}
        className={`
          flex items-center gap-1.5
          transition-all
          text-xs font-medium
          h-8
          rounded-xl
          border-2 border-[var(--border-color)]
          overflow-hidden
          max-w-[220px]
          ${compact ? 'px-2' : 'px-3'}
          ${
            isReadOnly
              ? 'text-[var(--text)]/40 cursor-default bg-[var(--text)]/5'
              : isOpen
                ? 'text-[var(--text)] bg-[var(--primary)]/15 border-[var(--primary)]/30'
                : 'text-[var(--text)] bg-[var(--text)]/10 hover:bg-[var(--text)]/20 active:bg-[var(--text)]/30'
          }
        `}
        title={isReadOnly ? `Model: ${activeModel} (not changeable)` : `Model: ${activeModel}`}
      >
        <Cpu size={14} weight="bold" className="flex-shrink-0" />
        {!compact && (
          <span className="truncate max-w-[180px]">{formatButtonLabel(activeModelInfo)}</span>
        )}
        {!compact && !isReadOnly && (
          <CaretDown
            size={12}
            weight="bold"
            className={`flex-shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          />
        )}
      </button>

      {isOpen && !isReadOnly && (
        <div
          className={`
            absolute ${dropUp ? 'bottom-full mb-2' : 'top-full mt-2'} left-0
            bg-[rgba(16,16,18,0.98)] backdrop-blur-xl
            border border-white/[0.08] rounded-xl
            w-[460px] h-[400px] z-[10000]
            shadow-2xl shadow-black/40
            flex flex-col overflow-hidden
          `}
        >
          {/* Search bar */}
          <div className="px-3 pt-3 pb-2 flex-shrink-0">
            <div className="relative">
              <MagnifyingGlass
                size={15}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/30"
              />
              <input
                ref={searchRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search models..."
                className="w-full pl-8 pr-3 py-2 bg-white/[0.06] border border-white/[0.08] rounded-lg text-sm text-white placeholder-white/30 focus:outline-none focus:border-[var(--primary)]/40 transition-colors"
                onKeyDown={(e) => {
                  if (e.key === 'Escape') setIsOpen(false);
                }}
              />
            </div>
          </div>

          {/* Divider */}
          <div className="h-px bg-white/[0.06] flex-shrink-0" />

          {/* Main content: tabs on the left, models on the right */}
          <div className="flex flex-1 min-h-0">
            {/* Provider tabs — vertical sidebar */}
            {providers.length > 1 && (
              <div className="w-[130px] flex-shrink-0 border-r border-white/[0.06] overflow-y-auto py-1">
                <button
                  onClick={() => setActiveTab(null)}
                  className={`w-full px-3 py-2 text-left text-xs font-medium transition-colors ${
                    activeTab === null
                      ? 'bg-[var(--primary)]/15 text-[var(--primary)] border-r-2 border-[var(--primary)]'
                      : 'text-white/50 hover:bg-white/[0.04] hover:text-white/70'
                  }`}
                >
                  All Models
                </button>
                {providers.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => setActiveTab(activeTab === p.id ? null : p.id)}
                    className={`w-full px-3 py-2 text-left text-xs font-medium transition-colors ${
                      activeTab === p.id
                        ? 'bg-[var(--primary)]/15 text-[var(--primary)] border-r-2 border-[var(--primary)]'
                        : 'text-white/50 hover:bg-white/[0.04] hover:text-white/70'
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            )}

            {/* Model list */}
            <div className="flex-1 overflow-y-auto overscroll-contain min-h-0">
              {isLoading ? (
                <div className="px-4 py-8 text-center">
                  <div className="inline-block w-5 h-5 border-2 border-white/20 border-t-[var(--primary)] rounded-full animate-spin mb-2" />
                  <div className="text-xs text-white/40">Loading models...</div>
                </div>
              ) : filteredModels.length === 0 ? (
                <div className="px-4 py-8 text-center">
                  <MagnifyingGlass size={24} className="mx-auto mb-2 text-white/20" />
                  <div className="text-sm text-white/40">
                    {search.trim() ? 'No models match your search' : 'No models available'}
                  </div>
                </div>
              ) : (
                <div className="py-1">
                  {filteredModels.map((model) => (
                    <ModelRow
                      key={model.id}
                      model={model}
                      isActive={model.id === activeModel}
                      onSelect={handleSelect}
                      showProvider={!activeTab}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ModelRow({
  model,
  isActive,
  onSelect,
  showProvider = false,
}: {
  model: ModelInfo;
  isActive: boolean;
  onSelect: (id: string) => void;
  showProvider?: boolean;
}) {
  const isFree = model.pricing != null && model.pricing.input === 0 && model.pricing.output === 0;
  const modelName = model.name ? rawModelName(model.name) : rawModelName(model.id);
  const providerLabel = getProviderLabel(model.provider || 'internal', model.provider_name);

  return (
    <button
      type="button"
      onClick={() => onSelect(model.id)}
      className={`
        w-full px-3 py-2 flex items-center gap-2.5
        text-sm transition-colors group
        ${isActive ? 'bg-[var(--primary)]/10 text-white' : 'text-white/80 hover:bg-white/[0.06]'}
      `}
    >
      <div
        className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
          model.health === 'unhealthy' || model.health === 'timeout'
            ? 'bg-red-400/70'
            : model.health === 'healthy'
              ? 'bg-emerald-400/70'
              : isActive
                ? 'bg-[var(--primary)]'
                : 'bg-white/15 group-hover:bg-white/25'
        }`}
      />

      <div className="flex-1 text-left min-w-0">
        <div className="truncate text-[13px] leading-tight">
          {showProvider && <span className="text-white/40">{providerLabel} / </span>}
          {modelName}
        </div>
        {model.pricing != null && (
          <div className="text-[10px] mt-0.5 leading-tight">
            {isFree ? (
              <span className="text-green-400/70 inline-flex items-center gap-0.5">
                <Lightning size={9} weight="fill" />
                Free
              </span>
            ) : (
              <span className="text-white/30">
                ${model.pricing.input.toFixed(2)} / ${model.pricing.output.toFixed(2)} per 1M
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
}
