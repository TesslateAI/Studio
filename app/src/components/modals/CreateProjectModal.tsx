import { useState, useEffect, useMemo, useRef, type KeyboardEvent, type MouseEvent } from 'react';
import { X, Folder, CaretDown, CaretRight } from '@phosphor-icons/react';
import { marketplaceApi, projectsApi } from '../../lib/api';
import { useTeam } from '../../contexts/TeamContext';

interface MarketplaceBase {
  id: string;
  name: string;
  slug: string;
  description?: string;
  icon_url?: string;
  default_port?: number;
}

interface SiblingFolder {
  id: string;
  name: string;
  slug: string;
  updatedAt: string;
}

interface CreateProjectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (projectName: string, baseId?: string, baseVersion?: string) => void;
  isLoading?: boolean;
  initialBaseId?: string;
  baseVersion?: string;
}

const FEATURED_SLUGS = ['nextjs-16', 'vite-react-fastapi', 'vite-react-go', 'expo-default'];

function formatRelative(iso: string): string {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const abs = Math.abs(Math.round((t - Date.now()) / 1000));
  if (abs < 60) return 'now';
  if (abs < 3600) return `${Math.round(abs / 60)}m ago`;
  if (abs < 86400) return `${Math.round(abs / 3600)}h ago`;
  if (abs < 86400 * 30) return `${Math.round(abs / 86400)}d ago`;
  return `${Math.round(abs / (86400 * 30))}mo ago`;
}

export function CreateProjectModal({
  isOpen,
  onClose,
  onConfirm,
  isLoading = false,
  initialBaseId,
  baseVersion,
}: CreateProjectModalProps) {
  const { activeTeam } = useTeam();

  const [projectName, setProjectName] = useState('');
  const [selectedBase, setSelectedBase] = useState<MarketplaceBase | null>(null);
  const [allBases, setAllBases] = useState<MarketplaceBase[]>([]);
  const [userBases, setUserBases] = useState<MarketplaceBase[]>([]);
  const [templatePickerOpen, setTemplatePickerOpen] = useState(false);

  const [siblings, setSiblings] = useState<SiblingFolder[]>([]);

  const inputRef = useRef<HTMLInputElement>(null);
  const templateBtnRef = useRef<HTMLButtonElement>(null);
  const templatePanelRef = useRef<HTMLDivElement>(null);

  // Load templates
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    Promise.all([
      marketplaceApi.getAllBases({ limit: 50 }),
      marketplaceApi.getUserBases().catch(() => ({ bases: [] })),
    ])
      .then(([allBasesRes, userBasesRes]) => {
        if (cancelled) return;
        const bases = (allBasesRes.bases || allBasesRes || []) as MarketplaceBase[];
        const userBasesData = (userBasesRes.bases || userBasesRes || []) as MarketplaceBase[];
        setAllBases(bases);
        setUserBases(userBasesData);
        setSelectedBase((current) => {
          if (current) return current;
          if (initialBaseId) {
            const preselected = bases.find((b) => b.id === initialBaseId);
            if (preselected) return preselected;
          }
          const defaultBase = FEATURED_SLUGS.map((slug) =>
            bases.find((b) => b.slug === slug)
          ).find(Boolean);
          return defaultBase || null;
        });
      })
      .catch((error) => console.error('Failed to load bases:', error));
    return () => {
      cancelled = true;
    };
  }, [isOpen, initialBaseId]);

  // Load existing sibling folders
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    projectsApi
      .getAll(activeTeam?.slug)
      .then((data: unknown) => {
        if (cancelled) return;
        const list = (Array.isArray(data) ? data : []) as Array<Record<string, unknown>>;
        const mapped: SiblingFolder[] = list
          .map((p) => ({
            id: (p.id as string) || '',
            name: (p.name as string) || 'Untitled',
            slug: (p.slug as string) || '',
            updatedAt:
              (p.updated_at as string) || (p.created_at as string) || new Date(0).toISOString(),
          }))
          .filter((p) => p.slug)
          .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
        setSiblings(mapped);
      })
      .catch(() => {
        if (!cancelled) setSiblings([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, activeTeam?.slug]);

  // Autofocus inline cursor
  useEffect(() => {
    if (isOpen) {
      const t = setTimeout(() => inputRef.current?.focus(), 40);
      return () => clearTimeout(t);
    }
  }, [isOpen]);

  // Close template picker on outside click
  useEffect(() => {
    if (!templatePickerOpen) return;
    const onClick = (e: globalThis.MouseEvent) => {
      const target = e.target as Node;
      if (
        !templatePanelRef.current?.contains(target) &&
        !templateBtnRef.current?.contains(target)
      ) {
        setTemplatePickerOpen(false);
      }
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [templatePickerOpen]);

  const displayBases = useMemo(() => {
    const featured = FEATURED_SLUGS.map((slug) => allBases.find((b) => b.slug === slug)).filter(
      Boolean
    ) as MarketplaceBase[];
    const featuredIds = new Set(featured.map((b) => b.id));
    const userOnly = userBases.filter((b) => !featuredIds.has(b.id));
    return [...featured, ...userOnly];
  }, [allBases, userBases]);

  const isInLibrary = (baseId: string) => userBases.some((b) => b.id === baseId);

  const handleBaseClick = async (base: MarketplaceBase) => {
    setTemplatePickerOpen(false);
    if (isInLibrary(base.id)) {
      setSelectedBase(base);
      inputRef.current?.focus();
      return;
    }
    try {
      await marketplaceApi.purchaseBase(base.id);
      const userBasesRes = await marketplaceApi.getUserBases();
      setUserBases((userBasesRes.bases || userBasesRes || []) as MarketplaceBase[]);
      setSelectedBase(base);
      inputRef.current?.focus();
    } catch (error) {
      console.error('Failed to add to library:', error);
    }
  };

  const resetAndClose = () => {
    if (isLoading) return;
    setProjectName('');
    setSelectedBase(null);
    setTemplatePickerOpen(false);
    onClose();
  };

  const handleConfirm = () => {
    if (isLoading || !projectName.trim() || !selectedBase) return;
    onConfirm(projectName.trim(), selectedBase.id, baseVersion || undefined);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' && projectName.trim() && selectedBase && !isLoading) {
      e.preventDefault();
      handleConfirm();
    } else if (e.key === 'Escape' && !isLoading) {
      e.preventDefault();
      resetAndClose();
    }
  };

  const stopPropagation = (e: MouseEvent<HTMLDivElement>) => e.stopPropagation();

  if (!isOpen) return null;

  const teamSlug = activeTeam?.slug || 'team';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-2 backdrop-blur-sm sm:p-4"
      onClick={resetAndClose}
      onKeyDown={handleKeyDown}
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-workspace-title"
    >
      <div
        onClick={stopPropagation}
        className="flex max-h-[calc(100dvh-1rem)] w-full max-w-[460px] flex-col overflow-hidden rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-large)] sm:max-h-[calc(100dvh-2rem)]"
      >
        {/* Path header */}
        <div className="flex items-center justify-between gap-2 border-b border-[var(--border)] bg-[var(--sidebar-bg)] px-3 py-2">
          <div
            id="create-workspace-title"
            className="flex min-w-0 items-center gap-1 text-[11px] text-[var(--text-muted)]"
          >
            <Folder
              size={12}
              weight="fill"
              className="flex-shrink-0 text-[var(--primary)]"
            />
            <span className="truncate">{teamSlug}</span>
            <CaretRight size={9} className="flex-shrink-0 text-[var(--text-subtle)]" />
            <span className="truncate text-[var(--text)]">New folder</span>
          </div>
          <button
            type="button"
            onClick={resetAndClose}
            disabled={isLoading}
            aria-label="Close"
            className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-[var(--radius-small)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] disabled:opacity-50 motion-safe:transition-colors"
          >
            <X size={13} />
          </button>
        </div>

        {/* Folder list — siblings + inline "new folder" row with cursor */}
        <div className="flex-1 overflow-y-auto bg-[var(--bg)] px-1.5 py-1.5">
          {siblings.slice(0, 50).map((s) => (
            <div
              key={s.id}
              className="flex items-center gap-2 rounded-[var(--radius-small)] px-2 py-1.5"
            >
              <Folder
                size={14}
                weight="duotone"
                className="flex-shrink-0 text-[var(--text-subtle)]"
              />
              <span className="min-w-0 flex-1 truncate text-[12px] text-[var(--text-muted)]">
                {s.name}
              </span>
              <span className="flex-shrink-0 text-[10px] text-[var(--text-subtle)]">
                {formatRelative(s.updatedAt)}
              </span>
            </div>
          ))}

          {/* The new folder row — this is where the cursor lives */}
          <div className="flex items-center gap-2 rounded-[var(--radius-small)] bg-[rgba(var(--primary-rgb),0.08)] px-2 py-1.5 ring-1 ring-[var(--primary)]">
            <Folder
              size={14}
              weight="fill"
              className="flex-shrink-0 text-[var(--primary)]"
            />
            <input
              ref={inputRef}
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="new folder"
              disabled={isLoading}
              maxLength={100}
              autoComplete="off"
              spellCheck={false}
              aria-label="Folder name"
              className="min-w-0 flex-1 border-0 bg-transparent p-0 text-[12px] text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none disabled:opacity-50 caret-[var(--primary)]"
            />
          </div>
        </div>

        {/* Footer — template + keyboard hint + primary action */}
        <div className="relative flex items-center justify-between gap-2 border-t border-[var(--border)] bg-[var(--sidebar-bg)] px-3 py-2">
          {/* Template picker — tiny affordance */}
          <button
            type="button"
            ref={templateBtnRef}
            onClick={() => setTemplatePickerOpen((v) => !v)}
            disabled={isLoading}
            className="flex min-w-0 items-center gap-1 rounded-[var(--radius-small)] px-1.5 py-1 text-[11px] text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] disabled:opacity-50"
          >
            <span className="text-[var(--text-subtle)]">as</span>
            <span className="truncate text-[var(--text)]">
              {selectedBase?.name || 'template'}
            </span>
            <CaretDown
              size={9}
              className={`flex-shrink-0 text-[var(--text-subtle)] motion-safe:transition-transform ${
                templatePickerOpen ? 'rotate-180' : ''
              }`}
            />
          </button>

          <div className="flex flex-shrink-0 items-center gap-2">
            <span className="hidden text-[10px] text-[var(--text-subtle)] sm:inline">
              <kbd className="font-mono">esc</kbd> cancel ·{' '}
              <kbd className="font-mono">↵</kbd> create
            </span>
            <button
              type="button"
              onClick={handleConfirm}
              disabled={!projectName.trim() || !selectedBase || isLoading}
              className="btn btn-sm btn-filled"
            >
              {isLoading ? 'Creating…' : 'Create'}
            </button>
          </div>

          {/* Template dropdown */}
          {templatePickerOpen && (
            <div
              ref={templatePanelRef}
              className="absolute bottom-full left-2 mb-1 max-h-[240px] w-[220px] overflow-y-auto rounded-[var(--radius-small)] border border-[var(--border-hover)] bg-[var(--surface)] p-1 shadow-[var(--shadow-large)]"
            >
              {displayBases.length === 0 ? (
                <div className="px-2 py-1.5 text-[11px] text-[var(--text-subtle)]">
                  Loading…
                </div>
              ) : (
                displayBases.map((base) => {
                  const isSelected = selectedBase?.id === base.id;
                  return (
                    <button
                      key={base.id}
                      type="button"
                      onClick={() => handleBaseClick(base)}
                      className={[
                        'flex w-full items-center gap-2 rounded-[var(--radius-small)] px-2 py-1.5 text-left text-[11px] motion-safe:transition-colors',
                        isSelected
                          ? 'bg-[rgba(var(--primary-rgb),0.12)] text-[var(--text)]'
                          : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]',
                      ].join(' ')}
                    >
                      <span className="min-w-0 flex-1 truncate">{base.name}</span>
                      {isSelected && (
                        <span className="flex-shrink-0 text-[var(--primary)]">•</span>
                      )}
                    </button>
                  );
                })
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
