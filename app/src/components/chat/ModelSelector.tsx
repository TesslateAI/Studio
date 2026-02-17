import { useState, useRef, useEffect, useMemo } from 'react';
import { Cpu } from '@phosphor-icons/react';
import { marketplaceApi } from '../../lib/api';
import { type ChatAgent } from '../../types/chat';

interface ModelSelectorProps {
  currentAgent: ChatAgent;
  onModelChange: (model: string) => void;
  compact?: boolean;
}

/** Extract short display name from a model ID (e.g. "openai/gpt-4o" → "gpt-4o") */
function displayModelName(model: string): string {
  const parts = model.split('/');
  return parts[parts.length - 1];
}

export function ModelSelector({ currentAgent, onModelChange, compact = false }: ModelSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [hasFetched, setHasFetched] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const activeModel = currentAgent.selectedModel || currentAgent.model || '';
  const isReadOnly = currentAgent.sourceType === 'closed' && !currentAgent.isCustom;

  // Close dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Fetch models on first open
  const handleToggle = async () => {
    if (isReadOnly) return;

    if (isOpen) {
      setIsOpen(false);
      return;
    }

    setIsOpen(true);

    if (!hasFetched) {
      setIsLoading(true);
      try {
        const data = await marketplaceApi.getAvailableModels();
        const raw: unknown[] = Array.isArray(data) ? data : data.models || [];
        // API returns model objects ({ id, name, ... }) — extract the id string
        const modelList: string[] = raw.map((m) =>
          typeof m === 'string' ? m : (m as Record<string, unknown>).id as string
        ).filter(Boolean);
        setModels(modelList);
        setHasFetched(true);
      } catch (error) {
        console.error('Failed to fetch models:', error);
      } finally {
        setIsLoading(false);
      }
    }
  };

  const handleSelect = (model: string) => {
    onModelChange(model);
    setIsOpen(false);
  };

  // Build display list: ensure current model is always visible
  const displayModels = useMemo(() => {
    if (!hasFetched) return [];
    const list = [...models];
    if (activeModel && !list.includes(activeModel)) {
      list.unshift(activeModel);
    }
    return list;
  }, [hasFetched, models, activeModel]);

  // No model info at all — hide the selector
  if (!activeModel) return null;

  return (
    <div className="relative" ref={dropdownRef}>
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
          flex-shrink-0
          h-8
          rounded-xl
          border-2 border-[var(--border-color)]
          ${compact ? 'px-2' : 'px-3'}
          ${
            isReadOnly
              ? 'text-[var(--text)]/40 cursor-default bg-[var(--text)]/5'
              : 'text-[var(--text)] bg-[var(--text)]/10 hover:bg-[var(--text)]/20 active:bg-[var(--text)]/30'
          }
        `}
        title={isReadOnly ? `Model: ${activeModel} (not changeable)` : `Model: ${activeModel}`}
      >
        <Cpu size={14} weight="bold" className="flex-shrink-0" />
        {!compact && (
          <span className="truncate max-w-[120px]">{displayModelName(activeModel)}</span>
        )}
        {!compact && !isReadOnly && (
          <svg className="w-3 h-3 ml-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 256 256">
            <path d="M213.66,101.66l-80,80a8,8,0,0,1-11.32,0l-80-80A8,8,0,0,1,53.66,90.34L128,164.69l74.34-74.35a8,8,0,0,1,11.32,11.32Z" />
          </svg>
        )}
      </button>

      {isOpen && !isReadOnly && (
        <div
          className="
            absolute bottom-full left-0 mb-2
            bg-[rgba(20,20,20,0.98)] backdrop-blur-xl
            border border-white/10 rounded-xl
            min-w-[280px] max-h-[300px] overflow-y-auto z-[10000]
            shadow-lg
          "
        >
          <div className="px-4 py-2 text-xs text-gray-400 border-b border-white/5">
            SELECT MODEL
          </div>

          {isLoading ? (
            <div className="px-4 py-3 text-sm text-gray-400">Loading models...</div>
          ) : displayModels.length === 0 ? (
            <div className="px-4 py-3 text-sm text-gray-400">No models available</div>
          ) : (
            displayModels.map((model) => (
              <button
                key={model}
                type="button"
                onClick={() => handleSelect(model)}
                className={`
                  w-full px-4 py-2.5 flex items-center gap-3
                  text-sm text-white transition-colors
                  hover:bg-white/8
                  ${model === activeModel ? 'bg-[rgba(255,107,0,0.2)]' : ''}
                `}
              >
                <Cpu size={14} className="flex-shrink-0 text-gray-400" />
                <span className="flex-1 text-left truncate">{model}</span>
                {model === activeModel && (
                  <span className="text-xs text-green-400 flex-shrink-0">Active</span>
                )}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
