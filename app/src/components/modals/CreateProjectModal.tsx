import { useState, useEffect, useMemo } from 'react';
import { FilePlus, X } from '@phosphor-icons/react';
import { Link } from 'react-router-dom';
import { marketplaceApi } from '../../lib/api';
import { TemplateCard, AddMoreCard } from '../TemplateCard';

interface MarketplaceBase {
  id: string;
  name: string;
  slug: string;
  description?: string;
  icon_url?: string;
  default_port?: number;
}

interface CreateProjectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (projectName: string, baseId?: string, baseVersion?: string) => void;
  isLoading?: boolean;
  initialBaseId?: string;
  baseVersion?: string;
}

// Featured bases shown by default (even if not in user's library)
// Must match seeded slugs from orchestrator/app/seeds/marketplace_bases.py
const FEATURED_SLUGS = [
  'nextjs-16',
  'vite-react-fastapi',
  'vite-react-go',
  'expo-default',
];

export function CreateProjectModal({
  isOpen,
  onClose,
  onConfirm,
  isLoading = false,
  initialBaseId,
  baseVersion,
}: CreateProjectModalProps) {
  const [projectName, setProjectName] = useState('');
  const [selectedBase, setSelectedBase] = useState<MarketplaceBase | null>(null);
  const [allBases, setAllBases] = useState<MarketplaceBase[]>([]);
  const [userBases, setUserBases] = useState<MarketplaceBase[]>([]);
  const [loadingBases, setLoadingBases] = useState(true);

  // Load bases when modal opens
  useEffect(() => {
    if (isOpen) {
      loadBases();
    }
  }, [isOpen]);

  const loadBases = async () => {
    setLoadingBases(true);
    try {
      // Load all bases and user's library in parallel
      const [allBasesRes, userBasesRes] = await Promise.all([
        marketplaceApi.getAllBases({ limit: 50 }),
        marketplaceApi.getUserBases().catch(() => ({ bases: [] })),
      ]);

      const bases = allBasesRes.bases || allBasesRes || [];
      const userBasesData = userBasesRes.bases || userBasesRes || [];

      setAllBases(bases);
      setUserBases(userBasesData);

      // Auto-select: initialBaseId (from "Use This Version") or first featured base
      if (!selectedBase) {
        if (initialBaseId) {
          const preselected = bases.find((b: MarketplaceBase) => b.id === initialBaseId);
          if (preselected) {
            setSelectedBase(preselected);
          }
        }
        if (!selectedBase && !initialBaseId) {
          const defaultBase = FEATURED_SLUGS.map((slug) =>
            bases.find((b: MarketplaceBase) => b.slug === slug)
          ).find(Boolean);
          if (defaultBase) {
            setSelectedBase(defaultBase);
          }
        }
      }
    } catch (error) {
      console.error('Failed to load bases:', error);
    } finally {
      setLoadingBases(false);
    }
  };

  // Combine: featured bases first, then user's added bases (deduplicated)
  const displayBases = useMemo(() => {
    // Get featured bases in order
    const featured = FEATURED_SLUGS.map((slug) => allBases.find((b) => b.slug === slug)).filter(
      Boolean
    ) as MarketplaceBase[];

    // Get user bases that aren't already in featured
    const featuredIds = new Set(featured.map((b) => b.id));
    const userOnly = userBases.filter((b) => !featuredIds.has(b.id));

    return [...featured, ...userOnly];
  }, [allBases, userBases]);

  // Check if a base is in user's library
  const isInLibrary = (baseId: string) => {
    return userBases.some((b) => b.id === baseId);
  };

  // Add base to library (purchase for free) and optionally select it
  const handleAddToLibrary = async (base: MarketplaceBase, andSelect: boolean = false) => {
    try {
      await marketplaceApi.purchaseBase(base.id);
      // Refresh user bases
      const userBasesRes = await marketplaceApi.getUserBases();
      setUserBases(userBasesRes.bases || userBasesRes || []);
      // Select the base after adding
      if (andSelect) {
        setSelectedBase(base);
      }
    } catch (error) {
      console.error('Failed to add to library:', error);
    }
  };

  // Handle base card click - add to library first if needed
  const handleBaseClick = async (base: MarketplaceBase) => {
    if (isInLibrary(base.id)) {
      // Already in library, just select it
      setSelectedBase(base);
    } else {
      // Not in library - add it first, then select it
      await handleAddToLibrary(base, true);
    }
  };

  if (!isOpen) return null;

  const handleConfirm = () => {
    if (isLoading || !projectName.trim() || !selectedBase) return;
    onConfirm(projectName.trim(), selectedBase.id, baseVersion || undefined);
  };

  const handleClose = () => {
    if (!isLoading) {
      setProjectName('');
      setSelectedBase(null);
      onClose();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && projectName.trim() && selectedBase && !isLoading) {
      handleConfirm();
    } else if (e.key === 'Escape' && !isLoading) {
      handleClose();
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={handleClose}
    >
      <div
        className="bg-[var(--surface)] p-6 sm:p-8 rounded-3xl w-full max-w-lg shadow-2xl border border-white/10 animate-in fade-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-start gap-4 flex-1">
            <div className="w-12 h-12 bg-[rgba(var(--primary-rgb),0.2)] rounded-xl flex items-center justify-center flex-shrink-0">
              <FilePlus className="w-6 h-6 text-[var(--primary)]" weight="fill" />
            </div>
            <div className="flex-1">
              <h2 className="font-heading text-xl font-bold text-[var(--text)] mb-2">
                Create New Project
              </h2>
              <p className="text-sm text-gray-400 leading-relaxed">
                Pick a template and name your project
              </p>
            </div>
          </div>
          {!isLoading && (
            <button
              onClick={handleClose}
              className="text-gray-400 hover:text-white transition-colors p-1 ml-2"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* Template Selection */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-[var(--text)] mb-3">
            Choose a Template
            {baseVersion && (
              <span className="ml-2 px-2 py-0.5 bg-[rgba(var(--primary-rgb),0.15)] text-[var(--primary)] text-xs rounded-md font-medium">
                version: {baseVersion}
              </span>
            )}
          </label>

          {loadingBases ? (
            <div className="flex items-center justify-center h-36">
              <div className="w-6 h-6 border-2 border-white/20 border-t-[var(--primary)] rounded-full animate-spin" />
            </div>
          ) : (
            <>
              {/* Horizontal scroll container */}
              <div className="overflow-x-auto pb-2 -mx-6 px-6 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent">
                <div className="flex gap-3 min-w-max">
                  {displayBases.map((base) => (
                    <TemplateCard
                      key={base.id}
                      base={base}
                      selected={selectedBase?.id === base.id}
                      onClick={() => handleBaseClick(base)}
                      inLibrary={isInLibrary(base.id)}
                    />
                  ))}
                  <AddMoreCard onClick={handleClose} />
                </div>
              </div>

              {/* Marketplace upsell */}
              <p className="text-sm text-white/40 mt-3">
                Looking for something else?{' '}
                <Link
                  to="/marketplace?tab=bases"
                  className="text-[var(--primary)] hover:underline"
                  onClick={handleClose}
                >
                  Explore Marketplace
                </Link>
              </p>
            </>
          )}
        </div>

        {/* Project Name Input */}
        <div className="mb-6">
          <label
            htmlFor="projectName"
            className="block text-sm font-medium text-[var(--text)] mb-2"
          >
            Project Name
          </label>
          <input
            id="projectName"
            type="text"
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="My Awesome Project"
            disabled={isLoading}
            autoFocus
            maxLength={100}
            className="
              w-full px-4 py-3 bg-[var(--bg)] border border-[var(--border-color)]
              text-[var(--text)] rounded-xl
              focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent
              placeholder:text-[var(--text)]/40
              disabled:opacity-50 disabled:cursor-not-allowed
              transition-all
            "
          />
          <p className="mt-2 text-xs text-gray-500">{projectName.length}/100 characters</p>
        </div>

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={handleClose}
            disabled={isLoading}
            className="flex-1 bg-white/5 border border-white/10 text-[var(--text)] py-3 rounded-xl font-semibold hover:bg-white/10 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={isLoading || !projectName.trim() || !selectedBase}
            className="flex-1 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:bg-gray-600 disabled:cursor-not-allowed text-white py-3 rounded-xl font-semibold transition-all"
          >
            {isLoading ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                Creating...
              </span>
            ) : (
              'Create Project'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
