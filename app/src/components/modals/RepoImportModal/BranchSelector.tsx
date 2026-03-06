import { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CaretDown, MagnifyingGlass, GitBranch, Shield, Check } from '@phosphor-icons/react';
import type { GitProviderBranch } from '../../../types/git-providers';

interface BranchSelectorProps {
  branches: GitProviderBranch[];
  selected: GitProviderBranch | null;
  onSelect: (branch: GitProviderBranch) => void;
  disabled?: boolean;
  loading?: boolean;
}

export function BranchSelector({
  branches,
  selected,
  onSelect,
  disabled = false,
  loading = false,
}: BranchSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [highlightIndex, setHighlightIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const filtered = search.trim()
    ? branches.filter((b) => b.name.toLowerCase().includes(search.toLowerCase()))
    : branches;

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
        setSearch('');
      }
    };
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  // Focus search input when dropdown opens
  useEffect(() => {
    if (isOpen && searchRef.current) {
      searchRef.current.focus();
    }
  }, [isOpen]);

  // Reset highlight when filter changes
  useEffect(() => {
    setHighlightIndex(0);
  }, [search]);

  // Scroll highlighted item into view
  useEffect(() => {
    if (isOpen && listRef.current) {
      const items = listRef.current.querySelectorAll('[data-branch-item]');
      items[highlightIndex]?.scrollIntoView({ block: 'nearest' });
    }
  }, [highlightIndex, isOpen]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!isOpen) {
        if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
          e.preventDefault();
          setIsOpen(true);
        }
        return;
      }

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          setHighlightIndex((i) => Math.min(i + 1, filtered.length - 1));
          break;
        case 'ArrowUp':
          e.preventDefault();
          setHighlightIndex((i) => Math.max(i - 1, 0));
          break;
        case 'Enter':
          e.preventDefault();
          if (filtered[highlightIndex]) {
            onSelect(filtered[highlightIndex]);
            setIsOpen(false);
            setSearch('');
          }
          break;
        case 'Escape':
          e.preventDefault();
          setIsOpen(false);
          setSearch('');
          break;
      }
    },
    [isOpen, filtered, highlightIndex, onSelect]
  );

  return (
    <div ref={containerRef} className="relative" onKeyDown={handleKeyDown}>
      <label className="block text-sm font-medium text-[var(--text)] mb-2">Branch</label>
      <button
        type="button"
        onClick={() => {
          if (!disabled && !loading && branches.length > 0) {
            setIsOpen(!isOpen);
          }
        }}
        disabled={disabled || loading || branches.length === 0}
        className="w-full flex items-center justify-between bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 rounded-xl transition-all min-h-[44px] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/30 focus:border-[var(--primary)]/50 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <span className="flex items-center gap-2 truncate">
          <GitBranch className="w-4 h-4 text-gray-400 flex-shrink-0" />
          {loading ? (
            <span className="text-gray-500">Loading branches...</span>
          ) : selected ? (
            <>
              <span className="truncate">{selected.name}</span>
              {selected.is_default && (
                <span className="text-[10px] bg-[var(--primary)]/15 text-[var(--primary)] px-1.5 py-0.5 rounded font-medium flex-shrink-0">
                  default
                </span>
              )}
            </>
          ) : branches.length === 0 ? (
            <span className="text-gray-500">No branches available</span>
          ) : (
            <span className="text-gray-500">Select a branch</span>
          )}
        </span>
        <CaretDown
          className={`w-4 h-4 text-gray-400 flex-shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="absolute z-50 mt-1 w-full bg-[var(--surface)] border border-white/10 rounded-xl shadow-xl overflow-hidden sm:max-h-64"
            style={{ maxHeight: 'min(260px, 50vh)' }}
          >
            {/* Search input */}
            {branches.length > 5 && (
              <div className="p-2 border-b border-white/5">
                <div className="relative">
                  <MagnifyingGlass className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                  <input
                    ref={searchRef}
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="w-full bg-white/5 border border-white/10 text-[var(--text)] text-sm pl-9 pr-3 py-2 rounded-lg focus:outline-none focus:ring-1 focus:ring-[var(--primary)]/30 placeholder-gray-500"
                    placeholder="Filter branches..."
                  />
                </div>
              </div>
            )}

            {/* Branch list */}
            <div ref={listRef} className="overflow-y-auto" style={{ maxHeight: 'min(200px, 40vh)' }}>
              {filtered.length === 0 ? (
                <div className="text-center text-sm text-gray-500 py-4">No matching branches</div>
              ) : (
                filtered.map((branch, i) => {
                  const isSelected = selected?.name === branch.name;
                  const isHighlighted = i === highlightIndex;

                  return (
                    <button
                      key={branch.name}
                      data-branch-item
                      type="button"
                      onClick={() => {
                        onSelect(branch);
                        setIsOpen(false);
                        setSearch('');
                      }}
                      className={`w-full text-left px-4 py-2.5 flex items-center gap-2 transition-colors min-h-[40px] ${
                        isHighlighted ? 'bg-white/10' : 'hover:bg-white/5'
                      }`}
                    >
                      <GitBranch className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
                      <span className="flex-1 truncate text-sm text-[var(--text)]">
                        {branch.name}
                      </span>
                      <span className="flex items-center gap-1.5 flex-shrink-0">
                        {branch.is_default && (
                          <span className="text-[10px] bg-[var(--primary)]/15 text-[var(--primary)] px-1.5 py-0.5 rounded font-medium">
                            default
                          </span>
                        )}
                        {branch.protected && (
                          <Shield size={12} weight="fill" className="text-yellow-500" />
                        )}
                        <span className="text-[11px] font-mono text-gray-500">
                          {branch.commit_sha?.slice(0, 7)}
                        </span>
                        {isSelected && (
                          <Check size={14} weight="bold" className="text-[var(--primary)]" />
                        )}
                      </span>
                    </button>
                  );
                })
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
