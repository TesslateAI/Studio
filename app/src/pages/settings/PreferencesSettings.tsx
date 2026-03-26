import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { Check } from 'lucide-react';
import {
  ArrowRight,
  SortAscending,
  SortDescending,
  CaretDown,
  MagnifyingGlass,
  Moon,
  Sun,
  X,
} from '@phosphor-icons/react';
import { useTheme } from '../../theme/ThemeContext';
import { marketplaceApi } from '../../lib/api';
import { ToggleSwitch } from '../../components/ui/ToggleSwitch';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';

type ThemeModeFilter = 'all' | 'dark' | 'light';
type ThemeSortField = 'name' | 'mode';
type ThemeSortDirection = 'asc' | 'desc';
type ThemeDisplayMode = 'grid' | 'compact';

interface LibraryThemeItem {
  id: string;
  name: string;
  description: string;
  mode: string;
  is_enabled: boolean;
  color_swatches?: {
    primary?: string;
    accent?: string;
    background?: string;
    surface?: string;
  };
  theme_json?: {
    colors?: Record<string, unknown>;
    spacing?: {
      radiusMedium?: string;
      [key: string]: unknown;
    };
    [key: string]: unknown;
  };
}

function ThemeCard({
  theme,
  isSelected,
  onSelect,
  compact = false,
}: {
  theme: LibraryThemeItem;
  isSelected: boolean;
  onSelect: () => void;
  compact?: boolean;
}) {
  const colors = theme.color_swatches || (theme.theme_json?.colors as Record<string, string>) || {};
  const radiusMedium = theme.theme_json?.spacing?.radiusMedium || '10px';

  if (compact) {
    return (
      <button
        onClick={onSelect}
        disabled={!theme.is_enabled}
        className={`relative flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-medium)] border transition-all text-left w-full ${
          isSelected
            ? 'border-[var(--primary)] bg-[rgba(var(--primary-rgb),0.08)]'
            : 'border-[var(--border)] bg-[var(--surface-hover)] hover:bg-[var(--border)] hover:border-[var(--border-hover)]'
        } ${!theme.is_enabled ? 'opacity-40 cursor-not-allowed' : ''}`}
      >
        {/* Mini color bar */}
        <div className="flex gap-1 flex-shrink-0">
          {['primary', 'background', 'surface', 'accent'].map((key) => (
            <div
              key={key}
              className="w-4 h-4 rounded-sm"
              style={{
                backgroundColor: (colors as Record<string, string>)[key] || '#333',
                border: '1px solid rgba(0,0,0,0.2)',
              }}
            />
          ))}
        </div>

        {/* Name + mode badge */}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-[var(--text)] truncate">{theme.name}</div>
        </div>

        {/* Mode pill */}
        <span
          className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full flex-shrink-0 ${
            theme.mode === 'dark'
              ? 'bg-[var(--surface)] text-[var(--text-muted)]'
              : 'bg-yellow-500/10 text-yellow-400'
          }`}
        >
          {theme.mode === 'dark' ? 'Dark' : 'Light'}
        </span>

        {/* Radius preview */}
        <div
          className="w-3.5 h-3.5 border border-[var(--text-subtle)] flex-shrink-0"
          style={{ borderRadius: radiusMedium, backgroundColor: 'transparent' }}
        />

        {/* Checkmark */}
        {isSelected && (
          <div className="w-4 h-4 rounded-full bg-[var(--primary)] flex items-center justify-center flex-shrink-0">
            <Check size={10} className="text-white" />
          </div>
        )}
      </button>
    );
  }

  return (
    <button
      onClick={onSelect}
      disabled={!theme.is_enabled}
      className={`relative flex flex-col items-start p-3 rounded-[var(--radius-medium)] border transition-all text-left w-full ${
        isSelected
          ? 'border-[var(--primary)] bg-[rgba(var(--primary-rgb),0.08)]'
          : 'border-[var(--border)] bg-[var(--surface-hover)] hover:bg-[var(--border)] hover:border-[var(--border-hover)]'
      } ${!theme.is_enabled ? 'opacity-40 cursor-not-allowed' : ''}`}
    >
      {/* Color preview swatches */}
      <div className="flex gap-1.5 mb-2">
        <div
          className="w-6 h-6 rounded-md"
          style={{
            backgroundColor: (colors as Record<string, string>).primary || '#6366f1',
            border: '1px solid rgba(0,0,0,0.2)',
          }}
          title="Primary"
        />
        <div
          className="w-6 h-6 rounded-md"
          style={{
            backgroundColor: (colors as Record<string, string>).background || '#0a0a0a',
            border: '1px solid rgba(0,0,0,0.2)',
          }}
          title="Background"
        />
        <div
          className="w-6 h-6 rounded-md"
          style={{
            backgroundColor: (colors as Record<string, string>).surface || '#141414',
            border: '1px solid rgba(0,0,0,0.2)',
          }}
          title="Surface"
        />
        <div
          className="w-6 h-6 rounded-md"
          style={{
            backgroundColor: (colors as Record<string, string>).accent || '#8b5cf6',
            border: '1px solid rgba(0,0,0,0.2)',
          }}
          title="Accent"
        />
      </div>

      {/* Theme name and description */}
      <div className="flex-1">
        <div className="text-xs font-medium text-[var(--text)]">{theme.name}</div>
        <div className="text-[11px] text-[var(--text-muted)] mt-0.5 line-clamp-1">
          {theme.description || ''}
        </div>
      </div>

      {/* Border radius preview */}
      <div className="flex items-center gap-1 mt-2">
        <span className="text-[10px] text-[var(--text-subtle)]">Corners:</span>
        <div
          className="w-4 h-4 border border-[var(--text-subtle)]"
          style={{ borderRadius: radiusMedium, backgroundColor: 'transparent' }}
        />
      </div>

      {/* Selected checkmark */}
      {isSelected && (
        <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-[var(--primary)] flex items-center justify-center">
          <Check size={12} className="text-white" />
        </div>
      )}
    </button>
  );
}

export default function PreferencesSettings() {
  const navigate = useNavigate();
  const { themePresetId, setThemePreset, isLoading: themeLoading } = useTheme();
  const [loading, setLoading] = useState(true);
  const [libraryThemes, setLibraryThemes] = useState<LibraryThemeItem[]>([]);

  // Theme toolbar state
  const [modeFilter, setModeFilter] = useState<ThemeModeFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [sortField, setSortField] = useState<ThemeSortField>('name');
  const [sortDirection, setSortDirection] = useState<ThemeSortDirection>('asc');
  const [displayMode, setDisplayMode] = useState<ThemeDisplayMode>('grid');
  const [showSortMenu, setShowSortMenu] = useState(false);
  const sortMenuRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const loadLibraryThemes = useCallback(async () => {
    try {
      const data = await marketplaceApi.getUserLibraryThemes();
      setLibraryThemes(data.themes || []);
    } catch (error) {
      console.error('Failed to load library themes:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLibraryThemes();
  }, [loadLibraryThemes]);

  // Close sort menu on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (sortMenuRef.current && !sortMenuRef.current.contains(e.target as Node)) {
        setShowSortMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Focus search input when shown
  useEffect(() => {
    if (showSearch && searchInputRef.current) {
      searchInputRef.current.focus();
    }
  }, [showSearch]);

  const handleThemeSelect = (presetId: string) => {
    setThemePreset(presetId);
    toast.success('Theme updated');
  };

  // Filter and sort themes
  const enabledThemes = libraryThemes.filter((t) => t.is_enabled);
  const filteredThemes = enabledThemes
    .filter((t) => {
      if (modeFilter !== 'all' && t.mode !== modeFilter) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        if (!t.name.toLowerCase().includes(q) && !(t.description || '').toLowerCase().includes(q))
          return false;
      }
      return true;
    })
    .sort((a, b) => {
      const dir = sortDirection === 'asc' ? 1 : -1;
      if (sortField === 'name') return dir * a.name.localeCompare(b.name);
      // Sort by mode: dark first (desc) or light first (asc)
      return dir * a.mode.localeCompare(b.mode);
    });

  const hasActiveFilters = modeFilter !== 'all' || searchQuery.length > 0;
  const darkCount = enabledThemes.filter((t) => t.mode === 'dark').length;
  const lightCount = enabledThemes.filter((t) => t.mode === 'light').length;

  const sortLabels: Record<ThemeSortField, string> = {
    name: 'Name',
    mode: 'Mode',
  };

  if (loading || themeLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading preferences..." size={60} />
      </div>
    );
  }

  return (
    <SettingsSection title="Preferences" description="Customize your Tesslate Studio experience">
      {/* Theme Selection */}
      <SettingsGroup title="Theme">
        <div className="p-0">
          {/* Toolbar — mode tabs left, search/sort/display right */}
          <div
            className="h-10 flex items-center justify-between border-b"
            style={{ paddingLeft: '7px', paddingRight: '10px', borderColor: 'var(--border)' }}
          >
            {/* Left: Mode filter tabs */}
            <div className="flex items-center gap-1 flex-1 min-w-0">
              <button
                onClick={() => setModeFilter('all')}
                className={`btn btn-sm ${modeFilter === 'all' ? 'btn-tab-active' : 'btn-tab'}`}
              >
                All themes
                <span className="text-[10px] opacity-50 ml-0.5">{enabledThemes.length}</span>
              </button>
              <button
                onClick={() => setModeFilter('dark')}
                className={`btn btn-sm ${modeFilter === 'dark' ? 'btn-tab-active' : 'btn-tab'}`}
              >
                <Moon className="w-3 h-3" weight={modeFilter === 'dark' ? 'fill' : 'regular'} />
                Dark
                <span className="text-[10px] opacity-50">{darkCount}</span>
              </button>
              <button
                onClick={() => setModeFilter('light')}
                className={`btn btn-sm ${modeFilter === 'light' ? 'btn-tab-active' : 'btn-tab'}`}
              >
                <Sun className="w-3 h-3" weight={modeFilter === 'light' ? 'fill' : 'regular'} />
                Light
                <span className="text-[10px] opacity-50">{lightCount}</span>
              </button>

              {/* Search pill — visible when searching */}
              {searchQuery && (
                <button
                  onClick={() => {
                    setSearchQuery('');
                    setShowSearch(false);
                  }}
                  className="btn btn-tab-active btn-sm"
                >
                  &ldquo;{searchQuery}&rdquo;
                  <X className="w-3 h-3 ml-0.5 opacity-60" />
                </button>
              )}
            </div>

            {/* Right: Search, Sort, Display */}
            <div className="flex items-center gap-[2px]">
              {/* Search toggle / inline input */}
              {showSearch ? (
                <div
                  className="flex items-center gap-1 bg-[var(--surface)] border rounded-full px-2 h-[24px]"
                  style={{ borderWidth: 'var(--border-width)', borderColor: 'var(--border-hover)' }}
                >
                  <MagnifyingGlass className="w-3 h-3 text-[var(--text-subtle)]" />
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
                    placeholder="Search themes..."
                    className="bg-transparent border-none outline-none text-xs text-[var(--text)] placeholder:text-[var(--text-subtle)] w-24 sm:w-32"
                  />
                  <button
                    onClick={() => {
                      setSearchQuery('');
                      setShowSearch(false);
                    }}
                    className="text-[var(--text-subtle)] hover:text-[var(--text)]"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setShowSearch(true)}
                  className={`btn btn-icon btn-sm ${searchQuery ? 'btn-active' : ''}`}
                  aria-label="Search themes"
                >
                  <MagnifyingGlass className="w-3.5 h-3.5" />
                </button>
              )}

              {/* Sort button */}
              <div ref={sortMenuRef} className="relative">
                <button
                  onClick={() => setShowSortMenu((v) => !v)}
                  className={`btn btn-sm ${sortField !== 'name' || sortDirection !== 'asc' ? 'btn-active' : ''}`}
                  aria-label="Sort"
                  style={{ gap: '4px' }}
                >
                  {sortDirection === 'desc' ? (
                    <SortDescending className="w-3.5 h-3.5" />
                  ) : (
                    <SortAscending className="w-3.5 h-3.5" />
                  )}
                  <span className="hidden sm:inline text-[11px]">{sortLabels[sortField]}</span>
                  <CaretDown className="w-2.5 h-2.5 opacity-50" />
                </button>

                {showSortMenu && (
                  <div
                    className="absolute right-0 top-full mt-1 z-50 min-w-[160px] py-1 rounded-[var(--radius-medium)] border bg-[var(--surface)] shadow-xl"
                    style={{
                      borderWidth: 'var(--border-width)',
                      borderColor: 'var(--border-hover)',
                    }}
                  >
                    <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">
                      Sort by
                    </div>
                    {(['name', 'mode'] as ThemeSortField[]).map((field) => (
                      <button
                        key={field}
                        onClick={() => {
                          if (sortField === field) {
                            setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'));
                          } else {
                            setSortField(field);
                            setSortDirection('asc');
                          }
                          setShowSortMenu(false);
                        }}
                        className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                          sortField === field
                            ? 'text-[var(--text)] bg-[var(--surface-hover)]'
                            : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
                        }`}
                      >
                        {sortLabels[field]}
                        {sortField === field && (
                          <span className="ml-auto text-[var(--text-subtle)]">
                            {sortDirection === 'asc' ? (
                              <SortAscending className="w-3.5 h-3.5" />
                            ) : (
                              <SortDescending className="w-3.5 h-3.5" />
                            )}
                          </span>
                        )}
                      </button>
                    ))}

                    <div className="my-1 border-t" style={{ borderColor: 'var(--border)' }} />

                    <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">
                      Direction
                    </div>
                    {(['asc', 'desc'] as ThemeSortDirection[]).map((dir) => (
                      <button
                        key={dir}
                        onClick={() => {
                          setSortDirection(dir);
                          setShowSortMenu(false);
                        }}
                        className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                          sortDirection === dir
                            ? 'text-[var(--text)] bg-[var(--surface-hover)]'
                            : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
                        }`}
                      >
                        {dir === 'asc' ? (
                          <>
                            <SortAscending className="w-3.5 h-3.5" /> Ascending
                          </>
                        ) : (
                          <>
                            <SortDescending className="w-3.5 h-3.5" /> Descending
                          </>
                        )}
                        {sortDirection === dir && (
                          <svg className="w-3 h-3 ml-auto" fill="currentColor" viewBox="0 0 16 16">
                            <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z" />
                          </svg>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Display mode toggle */}
              <button
                onClick={() => setDisplayMode((v) => (v === 'grid' ? 'compact' : 'grid'))}
                className={`btn btn-icon btn-sm ${displayMode === 'compact' ? 'btn-active' : ''}`}
                aria-label={
                  displayMode === 'grid' ? 'Switch to compact view' : 'Switch to grid view'
                }
              >
                {displayMode === 'grid' ? (
                  /* Grid icon */
                  <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 16 16">
                    <path d="M1 2.5A1.5 1.5 0 012.5 1h3A1.5 1.5 0 017 2.5v3A1.5 1.5 0 015.5 7h-3A1.5 1.5 0 011 5.5v-3zm8 0A1.5 1.5 0 0110.5 1h3A1.5 1.5 0 0115 2.5v3A1.5 1.5 0 0113.5 7h-3A1.5 1.5 0 019 5.5v-3zm-8 8A1.5 1.5 0 012.5 9h3A1.5 1.5 0 017 10.5v3A1.5 1.5 0 015.5 15h-3A1.5 1.5 0 011 13.5v-3zm8 0A1.5 1.5 0 0110.5 9h3a1.5 1.5 0 011.5 1.5v3a1.5 1.5 0 01-1.5 1.5h-3A1.5 1.5 0 019 13.5v-3z" />
                  </svg>
                ) : (
                  /* List icon */
                  <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 16 16">
                    <path d="M2 4a1 1 0 011-1h10a1 1 0 110 2H3a1 1 0 01-1-1zm0 4a1 1 0 011-1h10a1 1 0 110 2H3a1 1 0 01-1-1zm1 3a1 1 0 100 2h10a1 1 0 100-2H3z" />
                  </svg>
                )}
              </button>
            </div>
          </div>

          {/* Theme Grid/List */}
          <div className="p-4">
            {filteredThemes.length > 0 ? (
              displayMode === 'grid' ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {filteredThemes.map((theme) => (
                    <ThemeCard
                      key={theme.id}
                      theme={theme}
                      isSelected={themePresetId === theme.id}
                      onSelect={() => handleThemeSelect(theme.id)}
                    />
                  ))}
                </div>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {filteredThemes.map((theme) => (
                    <ThemeCard
                      key={theme.id}
                      theme={theme}
                      isSelected={themePresetId === theme.id}
                      onSelect={() => handleThemeSelect(theme.id)}
                      compact
                    />
                  ))}
                </div>
              )
            ) : (
              <div className="text-center py-10">
                <p className="text-xs text-[var(--text-muted)] mb-2">
                  {hasActiveFilters ? 'No themes match your filters' : 'No themes available'}
                </p>
                {hasActiveFilters && (
                  <button
                    onClick={() => {
                      setModeFilter('all');
                      setSearchQuery('');
                      setShowSearch(false);
                    }}
                    className="btn btn-sm"
                  >
                    Clear filters
                  </button>
                )}
              </div>
            )}

            <div className="flex items-center justify-between mt-4">
              <p className="text-xs text-[var(--text-subtle)]">
                Theme changes are automatically saved and will persist across sessions.
              </p>
              <button
                onClick={() => navigate('/marketplace?type=theme')}
                className="flex items-center gap-1 text-xs text-[var(--primary)] hover:text-[var(--primary-hover)] font-medium transition-colors flex-shrink-0"
              >
                Browse more themes
                <ArrowRight size={12} />
              </button>
            </div>
          </div>
        </div>
      </SettingsGroup>

      {/* Notifications - Placeholder for future */}
      <SettingsGroup title="Notifications">
        <SettingsItem
          label="Email notifications"
          description="Receive email updates about your projects"
          control={
            <ToggleSwitch
              active={true}
              onChange={() => toast('Email notifications coming soon!')}
              disabled={false}
            />
          }
        />
        <SettingsItem
          label="Marketing emails"
          description="Receive updates about new features and tips"
          control={
            <ToggleSwitch
              active={false}
              onChange={() => toast('Marketing preferences coming soon!')}
              disabled={false}
            />
          }
        />
      </SettingsGroup>
    </SettingsSection>
  );
}
