import { useState, useEffect, useRef } from 'react';
import {
  Rocket,
  Plus,
  Pencil,
  Trash,
  Eye,
  EyeSlash,
  Globe,
  LockKey,
  MagnifyingGlass,
  CaretDown,
  SortAscending,
  SortDescending,
  X,
  Gear,
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { ConfirmDialog } from '../../components/modals';
import { motion } from 'framer-motion';
import { staggerContainer, staggerItem } from '../../components/cards';

// ─── Types ──────────────────────────────────────────────────────────
export interface LibraryBase {
  id: string;
  name: string;
  slug: string;
  description: string;
  long_description?: string;
  git_repo_url?: string;
  default_branch?: string;
  category: string;
  icon: string;
  visibility: 'private' | 'public';
  tags?: string[];
  features?: string[];
  tech_stack?: string[];
  downloads: number;
  rating: number;
  source_type?: 'git' | 'archive';
  archive_size_bytes?: number;
  created_at: string;
}

// ─── Sort / filter types ────────────────────────────────────────────
type SortField = 'name' | 'downloads' | 'rating';
type SortDir = 'asc' | 'desc';
type FilterStatus = 'all' | 'public' | 'private';
type ViewMode = 'cards' | 'list';

const sortLabels: Record<SortField, string> = {
  name: 'Name',
  downloads: 'Downloads',
  rating: 'Rating',
};

// ─── Props ──────────────────────────────────────────────────────────
interface BasesPageProps {
  bases: LibraryBase[];
  loading: boolean;
  onBrowse: () => void;
  onEdit?: (base: LibraryBase) => void;
  onToggleVisibility?: (base: LibraryBase) => void;
  onDelete?: (base: LibraryBase) => void;
}

// ─── Main BasesPage component ───────────────────────────────────────
export default function BasesPage({
  bases,
  loading,
  onBrowse,
  onEdit,
  onToggleVisibility,
  onDelete,
}: BasesPageProps) {
  // Local state
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [viewMode, setViewMode] = useState<ViewMode>('cards');
  const [showSortMenu, setShowSortMenu] = useState(false);

  // Delete dialog
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [baseToDelete, setBaseToDelete] = useState<LibraryBase | null>(null);

  const searchInputRef = useRef<HTMLInputElement>(null);
  const sortMenuRef = useRef<HTMLDivElement>(null);

  // Focus search input when opened
  useEffect(() => {
    if (showSearch) searchInputRef.current?.focus();
  }, [showSearch]);

  // Close sort menu on outside click
  useEffect(() => {
    if (!showSortMenu) return;
    const handler = (e: MouseEvent) => {
      if (sortMenuRef.current && !sortMenuRef.current.contains(e.target as Node)) {
        setShowSortMenu(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showSortMenu]);

  // ─── Filtering & sorting ─────────────────────────────────────────
  const filtered = bases
    .filter((b) => {
      if (filterStatus === 'public' && b.visibility !== 'public') return false;
      if (filterStatus === 'private' && b.visibility !== 'private') return false;
      return true;
    })
    .filter((b) => {
      if (!searchQuery) return true;
      const q = searchQuery.toLowerCase();
      return (
        b.name.toLowerCase().includes(q) ||
        b.description.toLowerCase().includes(q) ||
        b.category.toLowerCase().includes(q)
      );
    })
    .sort((a, b) => {
      let cmp = 0;
      if (sortField === 'name') cmp = a.name.localeCompare(b.name);
      else if (sortField === 'downloads') cmp = (a.downloads || 0) - (b.downloads || 0);
      else if (sortField === 'rating') cmp = (a.rating || 0) - (b.rating || 0);
      return sortDir === 'desc' ? -cmp : cmp;
    });

  // ─── Handlers ────────────────────────────────────────────────────
  const handleDelete = (base: LibraryBase) => {
    setBaseToDelete(base);
    setShowDeleteDialog(true);
  };

  const confirmDelete = () => {
    if (!baseToDelete) return;
    setShowDeleteDialog(false);
    onDelete(baseToDelete);
    setBaseToDelete(null);
  };

  // ─── Loading state ───────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  // ─── Counts ──────────────────────────────────────────────────────
  const publicCount = bases.filter((b) => b.visibility === 'public').length;
  const privateCount = bases.filter((b) => b.visibility === 'private').length;
  const hasVisibilityData = publicCount > 0 || privateCount > 0;

  // ─── Render ──────────────────────────────────────────────────────
  return (
    <div className="flex-1 overflow-hidden flex flex-col">
      {/* Toolbar */}
      <div className="h-10 flex items-center justify-between flex-shrink-0" style={{ paddingLeft: '7px', paddingRight: '10px' }}>
        {/* Left: Filter tabs */}
        <div className="flex items-center gap-1 flex-1 min-w-0 overflow-x-auto scrollbar-none" style={{ maskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)', WebkitMaskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)' }}>
          <button onClick={() => setFilterStatus('all')} className={`btn ${filterStatus === 'all' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}>
            All bases <span className="text-[10px] opacity-50 ml-0.5">{bases.length}</span>
          </button>
          {hasVisibilityData && (
            <>
              <button onClick={() => setFilterStatus('public')} className={`btn ${filterStatus === 'public' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}>
                Public <span className="text-[10px] opacity-50 ml-0.5">{publicCount}</span>
              </button>
              <button onClick={() => setFilterStatus('private')} className={`btn ${filterStatus === 'private' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}>
                Private <span className="text-[10px] opacity-50 ml-0.5">{privateCount}</span>
              </button>
            </>
          )}
        </div>

        {/* Right: Search, Sort, Display, Divider, Submit Base */}
        <div className="flex items-center gap-[2px]">
          {/* Search toggle */}
          {showSearch ? (
            <div className="flex items-center gap-1.5 bg-[var(--surface)] border border-[var(--border)] rounded-full px-2.5 h-[29px]">
              <MagnifyingGlass size={16} className="text-[var(--text-subtle)]" />
              <input
                ref={searchInputRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') {
                    setSearchQuery('');
                    setShowSearch(false);
                  }
                }}
                placeholder="Search..."
                className="bg-transparent border-none outline-none text-xs w-24 sm:w-32 text-[var(--text)]"
              />
              <button type="button" onClick={() => { setSearchQuery(''); setShowSearch(false); }}>
                <X size={12} className="text-[var(--text-subtle)]" />
              </button>
            </div>
          ) : (
            <button onClick={() => setShowSearch(true)} className={`btn btn-icon ${searchQuery ? 'btn-active' : ''}`}>
              <MagnifyingGlass size={16} />
            </button>
          )}

          {/* Sort */}
          <div ref={sortMenuRef} className="relative">
            <button onClick={() => setShowSortMenu((v) => !v)} className={`btn ${sortField !== 'name' || sortDir !== 'asc' ? 'btn-active' : ''}`} style={{ gap: '4px' }}>
              {sortDir === 'desc' ? <SortDescending size={16} /> : <SortAscending size={16} />}
              <span className="hidden sm:inline text-xs">{sortLabels[sortField]}</span>
              <CaretDown size={12} className="opacity-50" />
            </button>
            {showSortMenu && (
              <div className="absolute right-0 top-full mt-1 z-50 min-w-[180px] py-1 rounded-[var(--radius-medium)] border bg-[var(--surface)]" style={{ borderWidth: 'var(--border-width)', borderColor: 'var(--border-hover)' }}>
                <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">Sort by</div>
                {(['name', 'downloads', 'rating'] as const).map((f) => (
                  <button key={f} onClick={() => { setSortField(f); setShowSortMenu(false); }} className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${sortField === f ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}>
                    {sortLabels[f]}
                  </button>
                ))}
                <div className="my-1 border-t" style={{ borderColor: 'var(--border)' }} />
                <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">Direction</div>
                <button onClick={() => { setSortDir('asc'); setShowSortMenu(false); }} className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 ${sortDir === 'asc' ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}>Ascending</button>
                <button onClick={() => { setSortDir('desc'); setShowSortMenu(false); }} className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 ${sortDir === 'desc' ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}>Descending</button>
              </div>
            )}
          </div>

          {/* Display toggle */}
          <button onClick={() => setViewMode((v) => v === 'cards' ? 'list' : 'cards')} className={`btn btn-icon ${viewMode === 'list' ? 'btn-active' : ''}`}>
            {viewMode === 'cards' ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></svg>
            )}
          </button>

          <div className="w-px h-[22px] bg-[var(--border)] mx-0.5" />

          {/* Browse Marketplace */}
          <button onClick={onBrowse} className="btn btn-filled">
            <Plus size={16} weight="bold" />
            <span className="hidden sm:inline">Browse Bases</span>
          </button>
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-hidden flex relative">
        <div className="flex-1 overflow-auto min-w-0">
          <div className="p-4 md:p-5">
            {bases.length === 0 ? (
              /* Empty state — no bases at all */
              <div className="text-center py-16">
                <div className="w-12 h-12 bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius)] flex items-center justify-center mb-4 mx-auto">
                  <Rocket size={18} className="text-[var(--text-muted)]" />
                </div>
                <h3 className="text-xs font-semibold text-[var(--text)] mb-2">No bases yet</h3>
                <p className="text-[11px] text-[var(--text-muted)] max-w-sm mx-auto mb-6">
                  Browse the marketplace to find project templates and add them to your library.
                </p>
                <button
                  onClick={onBrowse}
                  className="btn btn-filled"
                >
                  <Plus size={14} />
                  Browse Marketplace
                </button>
              </div>
            ) : filtered.length === 0 ? (
              /* No results for current filter/search */
              <div className="text-center py-16">
                <MagnifyingGlass size={48} className="mx-auto mb-4 text-[var(--text-subtle)]" />
                <p className="text-[var(--text-muted)] mb-2">No bases match your filters</p>
                <button
                  onClick={() => { setFilterStatus('all'); setSearchQuery(''); }}
                  className="text-xs text-[var(--primary)] hover:underline"
                >
                  Clear filters
                </button>
              </div>
            ) : viewMode === 'cards' ? (
              <motion.div variants={staggerContainer} initial="initial" animate="animate" className="grid gap-5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}>
                {filtered.map((base) => (
                  <BaseCard
                    key={base.id}
                    base={base}
                    onEdit={onEdit ? () => onEdit(base) : undefined}
                    onToggleVisibility={onToggleVisibility ? () => onToggleVisibility(base) : undefined}
                    onDelete={onDelete ? () => handleDelete(base) : undefined}
                  />
                ))}
              </motion.div>
            ) : (
              <div className="space-y-1">
                {filtered.map((base) => (
                  <BaseListRow
                    key={base.id}
                    base={base}
                    onEdit={onEdit ? () => onEdit(base) : undefined}
                    onToggleVisibility={onToggleVisibility ? () => onToggleVisibility(base) : undefined}
                    onDelete={onDelete ? () => onDelete(base) : undefined}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        isOpen={showDeleteDialog}
        onClose={() => {
          setShowDeleteDialog(false);
          setBaseToDelete(null);
        }}
        onConfirm={confirmDelete}
        title="Delete Base"
        message={`Are you sure you want to delete "${baseToDelete?.name}"? This will remove it from the marketplace and cannot be undone.`}
        confirmText="Delete"
        cancelText="Cancel"
        variant="danger"
      />
    </div>
  );
}

// ─── BaseListRow (list view) ────────────────────────────────────────
function BaseListRow({
  base,
  onEdit,
  onToggleVisibility,
  onDelete,
}: {
  base: LibraryBase;
  onEdit?: () => void;
  onToggleVisibility?: () => void;
  onDelete?: () => void;
}) {
  return (
    <div
      onClick={onEdit}
      className={`group flex items-center gap-3 px-3 py-2 rounded-lg transition-colors hover:bg-[var(--surface-hover)] border border-transparent ${onEdit ? 'cursor-pointer' : ''}`}
    >
      {/* Icon */}
      <div className="w-7 h-7 rounded-lg bg-[var(--surface)] border border-[var(--border)] flex items-center justify-center shrink-0">
        <span className="text-sm">{base.icon}</span>
      </div>

      {/* Name + description */}
      <div className="flex-1 min-w-0">
        <span className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-[var(--text)] truncate">{base.name}</span>
        </span>
        <span className="text-[11px] text-[var(--text-subtle)] block truncate">{base.description}</span>
      </div>

      {/* Category */}
      <span className="text-[10px] text-[var(--text-muted)] hidden sm:block truncate max-w-[80px]">
        {base.category}
      </span>

      {/* Tech stack inline */}
      {base.tech_stack && base.tech_stack.length > 0 && (
        <div className="hidden md:flex items-center gap-1">
          {base.tech_stack.slice(0, 3).map((tech) => (
            <span
              key={tech}
              className="px-1.5 py-px bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-small)] text-[10px] text-[var(--text-subtle)]"
            >
              {tech}
            </span>
          ))}
        </div>
      )}

      {/* Actions — visible on hover, only for creator view */}
      {(onToggleVisibility || onEdit || onDelete) && (
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0" onClick={(e) => e.stopPropagation()}>
          {onToggleVisibility && (
            <button onClick={onToggleVisibility} className="btn btn-sm">
              {base.visibility === 'public' ? <Eye size={12} /> : <EyeSlash size={12} />}
            </button>
          )}
          {onEdit && (
            <button onClick={onEdit} className="btn btn-sm">
              <Pencil size={12} />
            </button>
          )}
          {onDelete && (
            <button onClick={onDelete} className="btn btn-sm btn-danger">
              <Trash size={12} />
            </button>
          )}
        </div>
      )}

      {/* Settings gear (only for creator view) */}
      {onEdit && (
        <button onClick={(e) => { e.stopPropagation(); onEdit(); }} className="shrink-0 p-1 rounded-md hover:bg-[var(--surface)] transition-colors">
          <Gear size={14} className="text-[var(--text-subtle)]" />
        </button>
      )}
    </div>
  );
}

// ─── BaseCard (card view) ───────────────────────────────────────────
function BaseCard({
  base,
  onEdit,
  onToggleVisibility,
  onDelete,
}: {
  base: LibraryBase;
  onEdit?: () => void;
  onToggleVisibility?: () => void;
  onDelete?: () => void;
}) {
  return (
    <motion.div
      variants={staggerItem}
      initial="initial"
      animate="animate"
      onClick={onEdit}
      className={`group relative flex flex-col bg-[var(--surface-hover)] rounded-[var(--radius)] border border-[var(--border)] hover:border-[var(--border-hover)] transition-all duration-200 hover:-translate-y-0.5 ${onEdit ? 'cursor-pointer' : ''}`}
    >
      <div className="p-4 flex flex-col h-full">
        {/* Top row: icon + title + category */}
        <div className="flex items-start gap-2.5 mb-2 pr-16">
          <div className="w-8 h-8 rounded-lg bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center shrink-0">
            <span className="text-lg">{base.icon}</span>
          </div>
          <div className="flex-1 min-w-0">
            <h4 className="text-xs font-semibold text-[var(--text)] line-clamp-1">
              {base.name}
            </h4>
            <span className="text-[11px] text-[var(--text-subtle)]">{base.category}</span>
          </div>
        </div>

        {/* Status indicator — top-right */}
        <div className="absolute top-3 right-3 flex items-center gap-1.5">
          {base.source_type === 'archive' && (
            <span className="text-[10px] text-[var(--text-subtle)]">exported</span>
          )}
          <span className={`flex items-center gap-0.5 text-[10px] text-[var(--text-subtle)]`}>
            {base.visibility === 'public' ? <Globe size={10} /> : <LockKey size={10} />}
            {base.visibility}
          </span>
        </div>

        {/* Description */}
        <p className="text-[11px] leading-relaxed text-[var(--text-muted)] line-clamp-2 mb-3 min-h-[28px]">
          {base.description}
        </p>

        {/* Tech stack tags */}
        {base.tech_stack && base.tech_stack.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-3">
            {base.tech_stack.slice(0, 4).map((tech) => (
              <span
                key={tech}
                className="px-1.5 py-px bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-small)] text-[10px] text-[var(--text-subtle)]"
              >
                {tech}
              </span>
            ))}
          </div>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Stats */}
        <div className="flex items-center gap-3 text-[10px] text-[var(--text-subtle)]">
          <span>{base.downloads || 0} downloads</span>
          <span className="opacity-30">·</span>
          <span>{base.rating?.toFixed(1) || '5.0'} rating</span>
          {base.source_type === 'archive' && base.archive_size_bytes && (
            <>
              <span className="opacity-30">·</span>
              <span>
                {base.archive_size_bytes < 1024 * 1024
                  ? `${(base.archive_size_bytes / 1024).toFixed(0)} KB`
                  : `${(base.archive_size_bytes / 1024 / 1024).toFixed(1)} MB`}
              </span>
            </>
          )}
        </div>

        {/* Actions — only shown for creator view */}
        {(onToggleVisibility || onEdit || onDelete) && (
          <div className="flex items-center gap-1 mt-3 pt-3 border-t border-[var(--border)] opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
            {onToggleVisibility && (
              <button
                onClick={onToggleVisibility}
                aria-label={
                  base.visibility === 'public'
                    ? `Make ${base.name} private`
                    : `Make ${base.name} public`
                }
                className="btn btn-sm"
              >
                {base.visibility === 'public' ? <Eye size={12} /> : <EyeSlash size={12} />}
                {base.visibility === 'public' ? 'Public' : 'Private'}
              </button>
            )}
            {onEdit && (
              <button
                onClick={onEdit}
                aria-label={`Edit ${base.name}`}
                className="btn btn-sm"
              >
                <Pencil size={12} />
                Edit
              </button>
            )}
            <div className="flex-1" />
            {onDelete && (
              <button
                onClick={onDelete}
                aria-label={`Delete ${base.name}`}
                className="btn btn-icon btn-sm btn-danger"
              >
                <Trash size={12} />
              </button>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}
