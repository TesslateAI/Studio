import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Power,
  Plus,
  Trash,
  CaretDown,
  PaintBrush,
  X,
  MagnifyingGlass,
  Storefront,
  SortAscending,
  SortDescending,
  Gear,
} from '@phosphor-icons/react';
import { useTheme } from '../../theme/ThemeContext';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { ConfirmDialog } from '../../components/modals';
import toast from 'react-hot-toast';
import { motion } from 'framer-motion';
import { staggerContainer, staggerItem } from '../../components/cards';

export interface LibraryTheme {
  id: string;
  name: string;
  slug: string;
  description: string;
  mode: string;
  author: string;
  creator_username?: string | null;
  icon: string;
  category: string;
  tags: string[];
  source_type: string;
  pricing_type: string;
  is_published: boolean;
  is_enabled: boolean;
  is_custom: boolean;
  is_in_library: boolean;
  created_by_user_id?: string | null;
  parent_theme_id?: string | null;
  downloads: number;
  color_swatches?: {
    primary?: string;
    accent?: string;
    background?: string;
    surface?: string;
  };
  theme_json: {
    colors: Record<string, unknown>;
    typography?: Record<string, unknown>;
    spacing?: Record<string, unknown>;
    animation?: Record<string, unknown>;
    /** Top-level toggle: when true, all border CSS variables resolve to transparent. */
    borderless?: boolean;
  };
  added_date?: string;
}

type ThemeModeFilter = 'all' | 'dark' | 'light' | 'custom';
type SortField = 'name' | 'author' | 'mode';
type SortDir = 'asc' | 'desc';
type ViewMode = 'cards' | 'list';

const sortLabels: Record<SortField, string> = {
  name: 'Name',
  author: 'Author',
  mode: 'Mode',
};

function makeNewTheme(): LibraryTheme {
  return {
    id: '',
    name: '',
    slug: '',
    description: '',
    mode: 'dark',
    author: '',
    icon: 'palette',
    category: 'general',
    tags: [],
    source_type: 'open',
    pricing_type: 'free',
    is_published: false,
    is_enabled: true,
    is_custom: true,
    is_in_library: true,
    downloads: 0,
    theme_json: {
      colors: {
        primary: '#6366f1',
        primaryHover: '#818cf8',
        primaryRgb: '99, 102, 241',
        accent: '#8b5cf6',
        background: '#0a0a0a',
        surface: '#141414',
        surfaceHover: '#1a1a1a',
        text: '#ffffff',
        textMuted: 'rgba(255, 255, 255, 0.6)',
        textSubtle: 'rgba(255, 255, 255, 0.4)',
        border: 'rgba(255, 255, 255, 0.1)',
        borderHover: 'rgba(255, 255, 255, 0.2)',
        error: '#ef4444',
        success: '#22c55e',
        warning: '#f59e0b',
        info: '#3b82f6',
      },
      typography: {
        fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
        fontFamilyMono: "'JetBrains Mono', 'Fira Code', monospace",
        fontSizeBase: '14px',
        lineHeight: '1.6',
      },
      spacing: {
        radiusSmall: '6px',
        radiusMedium: '10px',
        radiusLarge: '14px',
        radiusXl: '20px',
      },
      animation: {
        durationFast: '0.15s',
        durationNormal: '0.2s',
        durationSlow: '0.3s',
        easing: 'cubic-bezier(0.4, 0, 0.2, 1)',
      },
      borderless: true,
    },
  };
}

// ─── Main ThemesPage component ──────────────────────────────────────
export default function ThemesPage({
  themes,
  loading,
  onToggleEnable,
  onTogglePublish: _onTogglePublish,
  onRemove,
  onDelete,
  onSave,
}: {
  themes: LibraryTheme[];
  loading: boolean;
  onToggleEnable: (theme: LibraryTheme) => void;
  onTogglePublish: (theme: LibraryTheme) => void;
  onRemove: (theme: LibraryTheme) => void;
  onDelete: (theme: LibraryTheme) => void;
  onSave: (
    theme: LibraryTheme,
    data: {
      name: string;
      description: string;
      mode: string;
      theme_json: Record<string, unknown>;
      icon: string;
      category: string;
      tags: string[];
    }
  ) => void;
}) {
  const navigate = useNavigate();
  const { themePresetId, setThemePreset } = useTheme();

  // Local state
  const [editingTheme, setEditingTheme] = useState<LibraryTheme | null>(null);
  const [filterStatus, setFilterStatus] = useState<ThemeModeFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [viewMode, setViewMode] = useState<ViewMode>('cards');
  const [showSortMenu, setShowSortMenu] = useState(false);

  // Delete/remove dialog
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [themeToDelete, setThemeToDelete] = useState<LibraryTheme | null>(null);
  const [deleteAction, setDeleteAction] = useState<'remove' | 'delete'>('remove');

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
  const filtered = themes
    .filter((t) => {
      if (filterStatus === 'dark' && t.mode !== 'dark') return false;
      if (filterStatus === 'light' && t.mode !== 'light') return false;
      if (filterStatus === 'custom' && !t.is_custom) return false;
      return true;
    })
    .filter((t) => {
      if (!searchQuery) return true;
      const q = searchQuery.toLowerCase();
      return (
        t.name.toLowerCase().includes(q) ||
        (t.description || '').toLowerCase().includes(q) ||
        (t.author || '').toLowerCase().includes(q)
      );
    })
    .sort((a, b) => {
      let cmp = 0;
      if (sortField === 'name') cmp = a.name.localeCompare(b.name);
      else if (sortField === 'author') cmp = (a.author || '').localeCompare(b.author || '');
      else if (sortField === 'mode') cmp = a.mode.localeCompare(b.mode);
      return sortDir === 'desc' ? -cmp : cmp;
    });

  // ─── Handlers ────────────────────────────────────────────────────
  const handleCreateTheme = () => setEditingTheme(makeNewTheme());

  const handleApply = (t: LibraryTheme) => {
    setThemePreset(t.id);
    toast.success(`Applied "${t.name}" theme`);
  };

  const handleRemove = (t: LibraryTheme) => {
    setThemeToDelete(t);
    setDeleteAction('remove');
    setShowDeleteDialog(true);
  };

  const handleDelete = (t: LibraryTheme) => {
    setThemeToDelete(t);
    setDeleteAction('delete');
    setShowDeleteDialog(true);
  };

  const confirmRemoveTheme = () => {
    if (!themeToDelete) return;
    setShowDeleteDialog(false);
    if (deleteAction === 'delete') {
      onDelete(themeToDelete);
    } else {
      onRemove(themeToDelete);
    }
    setThemeToDelete(null);
  };

  const handleSaveTheme = (data: {
    name: string;
    description: string;
    mode: string;
    theme_json: Record<string, unknown>;
    icon: string;
    category: string;
    tags: string[];
  }) => {
    if (!editingTheme) return;
    onSave(editingTheme, data);
    setEditingTheme(null);
  };

  // Counts for tabs
  const darkCount = themes.filter((t) => t.mode === 'dark').length;
  const lightCount = themes.filter((t) => t.mode === 'light').length;
  const customCount = themes.filter((t) => t.is_custom).length;

  // ─── Loading state ───────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  // ─── Render ──────────────────────────────────────────────────────
  return (
    <div className="flex-1 overflow-hidden flex flex-col">
      {/* Toolbar */}
      <div
        className="h-10 flex items-center justify-between flex-shrink-0"
        style={{ paddingLeft: '7px', paddingRight: '10px' }}
      >
        {/* Left: Filter tabs */}
        <div
          className="flex items-center gap-1 flex-1 min-w-0 overflow-x-auto scrollbar-none"
          style={{
            maskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)',
            WebkitMaskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)',
          }}
        >
          <button
            onClick={() => setFilterStatus('all')}
            className={`btn ${filterStatus === 'all' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}
          >
            All themes <span className="text-[10px] opacity-50 ml-0.5">{themes.length}</span>
          </button>
          <button
            onClick={() => setFilterStatus('dark')}
            className={`btn ${filterStatus === 'dark' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}
          >
            Dark <span className="text-[10px] opacity-50 ml-0.5">{darkCount}</span>
          </button>
          <button
            onClick={() => setFilterStatus('light')}
            className={`btn ${filterStatus === 'light' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}
          >
            Light <span className="text-[10px] opacity-50 ml-0.5">{lightCount}</span>
          </button>
          <button
            onClick={() => setFilterStatus('custom')}
            className={`btn ${filterStatus === 'custom' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}
          >
            Custom <span className="text-[10px] opacity-50 ml-0.5">{customCount}</span>
          </button>
        </div>

        {/* Right: Search, Sort, Display, Divider, Browse, Create */}
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
              <button
                type="button"
                onClick={() => {
                  setSearchQuery('');
                  setShowSearch(false);
                }}
              >
                <X size={12} className="text-[var(--text-subtle)]" />
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowSearch(true)}
              className={`btn btn-icon ${searchQuery ? 'btn-active' : ''}`}
            >
              <MagnifyingGlass size={16} />
            </button>
          )}

          {/* Sort */}
          <div ref={sortMenuRef} className="relative">
            <button
              onClick={() => setShowSortMenu((v) => !v)}
              className={`btn ${sortField !== 'name' || sortDir !== 'asc' ? 'btn-active' : ''}`}
              style={{ gap: '4px' }}
            >
              {sortDir === 'desc' ? <SortDescending size={16} /> : <SortAscending size={16} />}
              <span className="hidden sm:inline text-xs">{sortLabels[sortField]}</span>
              <CaretDown size={12} className="opacity-50" />
            </button>
            {showSortMenu && (
              <div
                className="absolute right-0 top-full mt-1 z-50 min-w-[180px] py-1 rounded-[var(--radius-medium)] border bg-[var(--surface)]"
                style={{ borderWidth: 'var(--border-width)', borderColor: 'var(--border-hover)' }}
              >
                <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">
                  Sort by
                </div>
                {(['name', 'author', 'mode'] as const).map((f) => (
                  <button
                    key={f}
                    onClick={() => {
                      setSortField(f);
                      setShowSortMenu(false);
                    }}
                    className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${sortField === f ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}
                  >
                    {f === 'name' ? 'Name' : f === 'author' ? 'Author' : 'Mode'}
                  </button>
                ))}
                <div className="my-1 border-t" style={{ borderColor: 'var(--border)' }} />
                <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">
                  Direction
                </div>
                <button
                  onClick={() => {
                    setSortDir('asc');
                    setShowSortMenu(false);
                  }}
                  className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 ${sortDir === 'asc' ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}
                >
                  Ascending
                </button>
                <button
                  onClick={() => {
                    setSortDir('desc');
                    setShowSortMenu(false);
                  }}
                  className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 ${sortDir === 'desc' ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}
                >
                  Descending
                </button>
              </div>
            )}
          </div>

          {/* Display toggle */}
          <button
            onClick={() => setViewMode((v) => (v === 'cards' ? 'list' : 'cards'))}
            className={`btn btn-icon ${viewMode === 'list' ? 'btn-active' : ''}`}
          >
            {viewMode === 'cards' ? (
              <svg
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                viewBox="0 0 24 24"
              >
                <rect x="3" y="3" width="7" height="7" rx="1" />
                <rect x="14" y="3" width="7" height="7" rx="1" />
                <rect x="3" y="14" width="7" height="7" rx="1" />
                <rect x="14" y="14" width="7" height="7" rx="1" />
              </svg>
            ) : (
              <svg
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                viewBox="0 0 24 24"
              >
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            )}
          </button>

          <div className="w-px h-[22px] bg-[var(--border)] mx-0.5" />

          {/* Browse marketplace */}
          <button onClick={() => navigate('/marketplace/browse/theme')} className="btn">
            <Storefront size={16} />
            <span className="hidden sm:inline">Browse</span>
          </button>

          {/* Create theme */}
          <button onClick={handleCreateTheme} className="btn btn-filled">
            <Plus size={16} weight="bold" />
            <span className="hidden sm:inline">Create</span>
          </button>
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-hidden flex relative">
        {/* Theme grid / list */}
        <div className="flex-1 overflow-auto min-w-0">
          <div className="p-4 md:p-5">
            {themes.length === 0 ? (
              /* Empty state -- no themes at all */
              <div className="text-center py-16">
                <PaintBrush size={48} className="mx-auto mb-4 text-[var(--text-subtle)]" />
                <p className="text-[var(--text-muted)] mb-4">Your theme library is empty</p>
                <button
                  onClick={() => navigate('/marketplace/browse/theme')}
                  className="btn btn-filled"
                >
                  Browse Themes
                </button>
              </div>
            ) : filtered.length === 0 ? (
              /* No results for current filter/search */
              <div className="text-center py-16">
                <MagnifyingGlass size={48} className="mx-auto mb-4 text-[var(--text-subtle)]" />
                <p className="text-[var(--text-muted)] mb-2">No themes match your filters</p>
                <button
                  onClick={() => {
                    setFilterStatus('all');
                    setSearchQuery('');
                  }}
                  className="text-xs text-[var(--primary)] hover:underline"
                >
                  Clear filters
                </button>
              </div>
            ) : viewMode === 'cards' ? (
              <motion.div
                variants={staggerContainer}
                initial="initial"
                animate="animate"
                className="grid gap-5"
                style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}
              >
                {filtered.map((t) => (
                  <ThemeCard
                    key={t.id || `theme-${t.name}-${t.slug}`}
                    theme={t}
                    isActive={themePresetId === t.id}
                    isSelected={editingTheme?.id === t.id}
                    onApply={() => handleApply(t)}
                    onToggleEnable={() => onToggleEnable(t)}
                    onEdit={() => setEditingTheme(t)}
                    onRemove={() => handleRemove(t)}
                    onDelete={() => handleDelete(t)}
                  />
                ))}
              </motion.div>
            ) : (
              <div className="space-y-1">
                {filtered.map((t) => (
                  <ThemeListRow
                    key={t.id || `row-${t.name}-${t.slug}`}
                    theme={t}
                    isActive={themePresetId === t.id}
                    isSelected={editingTheme?.id === t.id}
                    onEdit={() => setEditingTheme(t)}
                    onToggleEnable={() => onToggleEnable(t)}
                    onRemove={() => handleRemove(t)}
                    onDelete={() => handleDelete(t)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Detail panel (edit sidebar) */}
        {editingTheme && (
          <div
            className="w-full sm:w-[360px] lg:w-[440px] xl:w-[480px] max-sm:absolute max-sm:inset-0 max-sm:z-30 max-sm:bg-[var(--bg)] flex-shrink-0 overflow-y-auto animate-slide-in-right max-sm:!pl-[var(--app-margin)]"
            style={{ padding: 'var(--app-margin)', paddingLeft: 0 }}
          >
            <EditThemePanel
              theme={editingTheme}
              onClose={() => setEditingTheme(null)}
              onSave={handleSaveTheme}
            />
          </div>
        )}
      </div>

      {/* Delete/Remove Confirmation Dialog */}
      <ConfirmDialog
        isOpen={showDeleteDialog}
        onClose={() => {
          setShowDeleteDialog(false);
          setThemeToDelete(null);
        }}
        onConfirm={confirmRemoveTheme}
        title={deleteAction === 'delete' ? 'Delete Theme' : 'Remove Theme'}
        message={
          deleteAction === 'delete'
            ? `Permanently delete "${themeToDelete?.name}"? This will remove the theme entirely and cannot be undone.`
            : `Remove "${themeToDelete?.name}" from your library? You can re-install it from the Marketplace at any time.`
        }
        confirmText={deleteAction === 'delete' ? 'Delete Permanently' : 'Remove'}
        cancelText="Cancel"
        variant="danger"
      />
    </div>
  );
}

// ─── ThemeListRow (list view) ───────────────────────────────────────
function ThemeListRow({
  theme: t,
  isActive,
  isSelected,
  onEdit,
  onToggleEnable: _onToggleEnable,
  onRemove: _onRemove,
  onDelete: _onDelete,
}: {
  theme: LibraryTheme;
  isActive: boolean;
  isSelected?: boolean;
  onEdit: () => void;
  onToggleEnable: () => void;
  onRemove: () => void;
  onDelete: () => void;
}) {
  const colors = t.color_swatches || (t.theme_json?.colors as Record<string, string>) || {};

  return (
    <div
      onClick={onEdit}
      className={`flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
        isSelected
          ? 'bg-[var(--surface-hover)] border border-[var(--primary)]/30'
          : 'hover:bg-[var(--surface-hover)] border border-transparent'
      } ${!t.is_enabled ? 'opacity-50' : ''}`}
    >
      {/* Color swatches mini */}
      <div className="w-7 h-7 rounded-lg bg-[var(--bg)] border border-[var(--border)] grid grid-cols-2 gap-px p-0.5 shrink-0 overflow-hidden">
        {(['primary', 'background', 'surface', 'accent'] as const).map((key) => (
          <div
            key={key}
            className="rounded-sm"
            style={{ backgroundColor: (colors as Record<string, string>)[key] || '#333' }}
          />
        ))}
      </div>
      {/* Name + dot + description */}
      <div className="flex-1 min-w-0">
        <span className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-[var(--text)] truncate">{t.name}</span>
          <span
            className={`w-1.5 h-1.5 rounded-full shrink-0 ${t.is_enabled ? 'bg-[var(--status-success)]' : 'bg-[var(--text-subtle)]'}`}
          />
        </span>
        <span className="text-[11px] text-[var(--text-subtle)] block truncate">
          {t.description || 'No description'}
        </span>
      </div>
      {/* Mode */}
      <span className="text-[10px] text-[var(--text-muted)] hidden sm:block truncate max-w-[60px]">
        {t.mode}
      </span>
      {/* Active indicator */}
      {isActive && (
        <span className="text-[10px] text-[var(--primary)] hidden sm:block shrink-0">Active</span>
      )}
      {/* Settings */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onEdit();
        }}
        className="shrink-0 p-1 rounded-md hover:bg-[var(--surface)] transition-colors"
      >
        <Gear size={14} className="text-[var(--text-subtle)]" />
      </button>
    </div>
  );
}

// ─── ThemeCard (card view) ──────────────────────────────────────────
function ThemeCard({
  theme: t,
  isActive,
  isSelected,
  onApply,
  onToggleEnable,
  onEdit,
  onRemove,
  onDelete,
}: {
  theme: LibraryTheme;
  isActive: boolean;
  isSelected?: boolean;
  onApply: () => void;
  onToggleEnable: () => void;
  onEdit: () => void;
  onRemove: () => void;
  onDelete: () => void;
}) {
  const colors = t.color_swatches || (t.theme_json?.colors as Record<string, string>) || {};

  return (
    <motion.div
      variants={staggerItem}
      initial="initial"
      animate="animate"
      onClick={onEdit}
      className={`
        group relative flex flex-col h-full cursor-pointer
        bg-[var(--surface)] rounded-[var(--radius)] border border-[var(--border)]
        transition-all duration-200
        hover:-translate-y-1
        hover:bg-[var(--card-hover)]
        ${isSelected ? 'border-[var(--primary)] ring-1 ring-[var(--primary)]/20' : ''}
        ${!t.is_enabled ? 'opacity-45' : ''}
      `}
    >
      <div className="p-4 flex flex-col h-full">
        {/* Top row: color swatches + name + enabled dot */}
        <div className="flex items-center gap-3 mb-3">
          <div className="w-8 h-8 rounded-lg bg-[var(--bg)] border border-[var(--border)] grid grid-cols-2 gap-px p-0.5 shrink-0 overflow-hidden">
            {(['primary', 'background', 'surface', 'accent'] as const).map((key) => (
              <div
                key={key}
                className="rounded-sm"
                style={{ backgroundColor: (colors as Record<string, string>)[key] || '#333' }}
              />
            ))}
          </div>
          <div className="flex-1 min-w-0">
            <span className="flex items-center gap-1.5">
              <span className="text-xs font-semibold text-[var(--text)] truncate">{t.name}</span>
              <span
                className={`w-1.5 h-1.5 rounded-full shrink-0 ${t.is_enabled ? 'bg-[var(--status-success)]' : 'bg-[var(--text-subtle)]'}`}
              />
            </span>
            <span className="text-[11px] text-[var(--text-subtle)] block truncate">
              {t.creator_username ? `@${t.creator_username}` : t.author || 'Tesslate'}
            </span>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onEdit();
            }}
            className="shrink-0 p-1 rounded-md hover:bg-[var(--surface)] transition-colors"
            aria-label="Theme settings"
          >
            <Gear
              size={14}
              className="text-[var(--text-subtle)] group-hover:text-[var(--text-muted)] transition-colors"
            />
          </button>
        </div>

        {/* Description */}
        <p className="text-[11px] leading-relaxed text-[var(--text-muted)] line-clamp-2 mb-3 min-h-[28px]">
          {t.description || 'No description'}
        </p>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Metadata row -- monochrome, quiet */}
        <div className="flex items-center gap-2 text-[10px] text-[var(--text-subtle)]">
          <span>{t.mode}</span>
          {isActive && (
            <>
              <span className="opacity-30">&middot;</span>
              <span className="text-[var(--primary)]">Active</span>
            </>
          )}
          {t.is_custom && (
            <>
              <span className="opacity-30">&middot;</span>
              <span>Custom</span>
            </>
          )}
        </div>

        {/* Actions */}
        <div
          className="flex items-center gap-1 mt-3 pt-3 border-t border-[var(--border)]"
          onClick={(e) => e.stopPropagation()}
        >
          {!isActive && t.is_enabled && (
            <button onClick={onApply} className="btn btn-sm">
              <PaintBrush size={12} />
              Apply
            </button>
          )}
          <button onClick={onToggleEnable} className="btn btn-sm">
            <Power size={12} />
            {t.is_enabled ? 'Disable' : 'Enable'}
          </button>
          <div className="flex-1" />
          <button
            onClick={t.is_custom && !t.is_published ? onDelete : onRemove}
            className="btn btn-icon btn-sm btn-danger"
          >
            <Trash size={12} />
          </button>
        </div>
      </div>
    </motion.div>
  );
}

// ─── EditThemePanel (detail sidebar) ────────────────────────────────
function EditThemePanel({
  theme,
  onClose,
  onSave,
}: {
  theme: LibraryTheme;
  onClose: () => void;
  onSave: (data: {
    name: string;
    description: string;
    mode: string;
    theme_json: Record<string, unknown>;
    icon: string;
    category: string;
    tags: string[];
  }) => void;
}) {
  const [name, setName] = useState(theme.name);
  const [description, setDescription] = useState(theme.description || '');
  const [mode, setMode] = useState(theme.mode || 'dark');
  const [icon, setIcon] = useState(theme.icon || 'palette');
  const [category, setCategory] = useState(theme.category || 'general');
  const [tagsInput, setTagsInput] = useState((theme.tags || []).join(', '));
  const [borderless, setBorderless] = useState<boolean>(
    Boolean((theme.theme_json as { borderless?: boolean } | undefined)?.borderless)
  );
  const [themeColors, setThemeColors] = useState<Record<string, string>>(() => {
    const c = (theme.theme_json?.colors || {}) as Record<string, unknown>;
    const flat: Record<string, string> = {};
    for (const [k, v] of Object.entries(c)) {
      if (typeof v === 'string') {
        flat[k] = v;
      } else if (typeof v === 'object' && v !== null) {
        for (const [nk, nv] of Object.entries(v as Record<string, string>)) {
          flat[`${k}.${nk}`] = nv;
        }
      }
    }
    return flat;
  });
  const [saving, setSaving] = useState(false);

  // Collapsible section state
  const [propertiesExpanded, setPropertiesExpanded] = useState(true);
  const [previewExpanded, setPreviewExpanded] = useState(true);

  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    primary: true,
    background: true,
    text: false,
    border: false,
    sidebar: false,
    input: false,
    status: false,
    code: false,
  });

  const toggleSection = (key: string) => {
    setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const colorGroups = [
    {
      key: 'primary',
      label: 'Primary Colors',
      fields: ['primary', 'primaryHover', 'primaryRgb', 'accent'],
    },
    {
      key: 'background',
      label: 'Background',
      fields: ['background', 'surface', 'surfaceHover'],
    },
    {
      key: 'text',
      label: 'Text',
      fields: ['text', 'textMuted', 'textSubtle'],
    },
    {
      key: 'border',
      label: 'Border',
      fields: ['border', 'borderHover'],
    },
    {
      key: 'sidebar',
      label: 'Sidebar',
      fields: [
        'sidebar.background',
        'sidebar.text',
        'sidebar.border',
        'sidebar.hover',
        'sidebar.active',
      ],
    },
    {
      key: 'input',
      label: 'Input',
      fields: [
        'input.background',
        'input.border',
        'input.borderFocus',
        'input.text',
        'input.placeholder',
      ],
    },
    {
      key: 'status',
      label: 'Status Colors',
      fields: ['error', 'success', 'warning', 'info'],
    },
    {
      key: 'code',
      label: 'Code',
      fields: [
        'code.inlineBackground',
        'code.inlineText',
        'code.blockBackground',
        'code.blockBorder',
        'code.blockText',
      ],
    },
  ];

  const updateColor = (key: string, value: string) => {
    setThemeColors((prev) => ({ ...prev, [key]: value }));
  };

  const toHexForInput = (val: string) => {
    if (!val) return '#333333';
    if (val.startsWith('#') && (val.length === 7 || val.length === 4)) return val;
    const rgbMatch = val.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (rgbMatch) {
      const r = parseInt(rgbMatch[1]).toString(16).padStart(2, '0');
      const g = parseInt(rgbMatch[2]).toString(16).padStart(2, '0');
      const b = parseInt(rgbMatch[3]).toString(16).padStart(2, '0');
      return `#${r}${g}${b}`;
    }
    return '#333333';
  };

  const handleSave = () => {
    if (!name.trim()) {
      toast.error('Theme name is required');
      return;
    }
    setSaving(true);

    const colors: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(themeColors)) {
      if (k.includes('.')) {
        const [parent, child] = k.split('.');
        if (!colors[parent]) colors[parent] = {};
        (colors[parent] as Record<string, string>)[child] = v;
      } else {
        colors[k] = v;
      }
    }

    onSave({
      name: name.trim(),
      description: description.trim(),
      mode,
      theme_json: {
        colors,
        typography: theme.theme_json?.typography || {},
        spacing: theme.theme_json?.spacing || {},
        animation: theme.theme_json?.animation || {},
        borderless,
      },
      icon,
      category,
      tags: tagsInput
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
    });
  };

  // Card wrapper for each section
  const card =
    'bg-[var(--surface-hover)] rounded-[var(--radius)] border border-[var(--border)] overflow-hidden';

  // Collapsible section header
  const SectionHeader = ({
    label,
    count,
    expanded,
    onToggle,
  }: {
    label: string;
    count?: number;
    expanded: boolean;
    onToggle: () => void;
  }) => (
    <div className="flex items-center">
      <button
        type="button"
        onClick={onToggle}
        className="flex-1 flex items-center gap-2 px-4 py-2.5 hover:bg-[var(--surface-hover)] transition-colors group"
      >
        <span className="text-[11px] font-medium text-[var(--text-muted)] group-hover:text-[var(--text)]">
          {label}
        </span>
        {count != null && count > 0 && (
          <span className="text-[10px] text-[var(--text-subtle)]">{count}</span>
        )}
        <span
          className={`transition-transform duration-200 text-[var(--text-subtle)] ${expanded ? 'rotate-0' : '-rotate-90'}`}
        >
          <CaretDown size={10} />
        </span>
      </button>
    </div>
  );

  const inputClass =
    'w-full px-2.5 py-1.5 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)] focus:outline-none focus:border-[var(--border-hover)]';

  return (
    <div className="flex flex-col gap-2">
      {/* Identity card -- save + close + name */}
      <div className={card}>
        <div className="flex items-center justify-between h-10 px-4 border-b border-[var(--border)]">
          <span className="text-xs font-semibold text-[var(--text)] truncate">
            {name || 'New Theme'}
          </span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || !name.trim()}
              className="btn btn-sm btn-filled"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button type="button" onClick={onClose} className="btn btn-icon btn-sm">
              <X size={14} />
            </button>
          </div>
        </div>
        <div className="p-4 space-y-3">
          <div>
            <label className="block text-[10px] font-medium text-[var(--text-subtle)] mb-1">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={inputClass}
              placeholder="My Custom Theme"
            />
          </div>
          <div>
            <label className="block text-[10px] font-medium text-[var(--text-subtle)] mb-1">
              Description
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className={inputClass}
              placeholder="A beautiful dark theme with..."
            />
          </div>
        </div>
      </div>

      {/* Properties card */}
      <div className={card}>
        <SectionHeader
          label="Properties"
          expanded={propertiesExpanded}
          onToggle={() => setPropertiesExpanded(!propertiesExpanded)}
        />
        {propertiesExpanded && (
          <div className="px-4 pb-4 space-y-3">
            <div className="flex items-center gap-3">
              <span className="text-[11px] text-[var(--text-subtle)] w-14 flex-shrink-0">Mode</span>
              <div className="flex gap-1.5 flex-1">
                <button
                  type="button"
                  onClick={() => setMode('dark')}
                  className={`flex-1 px-2.5 py-1.5 rounded-[var(--radius-small)] text-xs font-medium transition-colors ${
                    mode === 'dark'
                      ? 'bg-[var(--primary)] text-white'
                      : 'bg-[var(--bg)] border border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--surface)]'
                  }`}
                >
                  Dark
                </button>
                <button
                  type="button"
                  onClick={() => setMode('light')}
                  className={`flex-1 px-2.5 py-1.5 rounded-[var(--radius-small)] text-xs font-medium transition-colors ${
                    mode === 'light'
                      ? 'bg-[var(--primary)] text-white'
                      : 'bg-[var(--bg)] border border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--surface)]'
                  }`}
                >
                  Light
                </button>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[11px] text-[var(--text-subtle)] w-14 flex-shrink-0">
                Category
              </span>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className={inputClass + ' flex-1'}
              >
                <option value="general">General</option>
                <option value="minimal">Minimal</option>
                <option value="vibrant">Vibrant</option>
                <option value="professional">Professional</option>
              </select>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[11px] text-[var(--text-subtle)] w-14 flex-shrink-0">Icon</span>
              <input
                type="text"
                value={icon}
                onChange={(e) => setIcon(e.target.value)}
                className={inputClass + ' flex-1'}
                placeholder="palette"
              />
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[11px] text-[var(--text-subtle)] w-14 flex-shrink-0">Tags</span>
              <input
                type="text"
                value={tagsInput}
                onChange={(e) => setTagsInput(e.target.value)}
                className={inputClass + ' flex-1'}
                placeholder="dark, minimal, blue"
              />
            </div>
            {/* Borderless toggle — when on, the frontend forces every
                border CSS variable to transparent for this theme. The
                color values themselves are preserved so flipping it back
                off restores the original look. */}
            <div className="flex items-center gap-3">
              <span className="text-[11px] text-[var(--text-subtle)] w-14 flex-shrink-0">
                Borders
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={!borderless}
                onClick={() => setBorderless((v) => !v)}
                className={`flex-1 flex items-center justify-between px-2.5 py-1.5 rounded-[var(--radius-small)] text-xs transition-colors ${
                  borderless
                    ? 'bg-[var(--surface-hover)] text-[var(--text-muted)]'
                    : 'bg-[var(--bg)] text-[var(--text)]'
                }`}
              >
                <span>{borderless ? 'Hidden (borderless)' : 'Visible'}</span>
                <span
                  className={`relative inline-flex h-3.5 w-7 items-center rounded-full transition-colors ${
                    borderless ? 'bg-[var(--text-subtle)]' : 'bg-[var(--primary)]'
                  }`}
                >
                  <span
                    className={`inline-block h-2.5 w-2.5 transform rounded-full bg-white transition-transform ${
                      borderless ? 'translate-x-1' : 'translate-x-3.5'
                    }`}
                  />
                </span>
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Preview card */}
      <div className={card}>
        <SectionHeader
          label="Preview"
          expanded={previewExpanded}
          onToggle={() => setPreviewExpanded(!previewExpanded)}
        />
        {previewExpanded && (
          <div className="px-4 pb-4">
            <div
              className="rounded-xl border overflow-hidden p-4"
              style={{
                backgroundColor: themeColors.background || '#0a0a0a',
                borderColor: themeColors.border || 'rgba(255,255,255,0.1)',
              }}
            >
              <div
                className="rounded-lg p-3 mb-2"
                style={{
                  backgroundColor: themeColors.surface || '#141414',
                  borderColor: themeColors.border || 'rgba(255,255,255,0.1)',
                  border: '1px solid',
                }}
              >
                <div
                  className="text-sm font-medium mb-1"
                  style={{ color: themeColors.text || '#fff' }}
                >
                  Sample Card
                </div>
                <div
                  className="text-xs mb-2"
                  style={{ color: themeColors.textMuted || 'rgba(255,255,255,0.6)' }}
                >
                  This is how content looks with your theme colors.
                </div>
                <button
                  className="px-3 py-1 rounded-md text-xs font-medium text-white"
                  style={{ backgroundColor: themeColors.primary || '#6366f1' }}
                >
                  Primary Button
                </button>
              </div>
              <div className="flex gap-2">
                <span
                  className="px-2 py-0.5 rounded text-[10px] font-medium"
                  style={{
                    backgroundColor: themeColors.success || '#22c55e',
                    color: '#fff',
                  }}
                >
                  Success
                </span>
                <span
                  className="px-2 py-0.5 rounded text-[10px] font-medium"
                  style={{
                    backgroundColor: themeColors.error || '#ef4444',
                    color: '#fff',
                  }}
                >
                  Error
                </span>
                <span
                  className="px-2 py-0.5 rounded text-[10px] font-medium"
                  style={{
                    backgroundColor: themeColors.accent || '#8b5cf6',
                    color: '#fff',
                  }}
                >
                  Accent
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Color group cards */}
      {colorGroups.map((group) => (
        <div key={group.key} className={card}>
          <SectionHeader
            label={group.label}
            count={group.fields.filter((f) => themeColors[f]).length}
            expanded={expandedSections[group.key] || false}
            onToggle={() => toggleSection(group.key)}
          />
          {expandedSections[group.key] && (
            <div className="px-4 pb-4 space-y-2">
              {group.fields.map((field) => (
                <div key={field} className="flex items-center gap-2">
                  <input
                    type="color"
                    value={toHexForInput(themeColors[field] || '')}
                    onChange={(e) => updateColor(field, e.target.value)}
                    className="w-7 h-7 rounded border border-[var(--border)] cursor-pointer bg-transparent"
                  />
                  <div className="flex-1 min-w-0">
                    <label className="text-[10px] text-[var(--text-subtle)] block truncate">
                      {field}
                    </label>
                    <input
                      type="text"
                      value={themeColors[field] || ''}
                      onChange={(e) => updateColor(field, e.target.value)}
                      className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-[11px] text-[var(--text-muted)] focus:outline-none focus:border-[var(--border-hover)]"
                      placeholder="#000000"
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
