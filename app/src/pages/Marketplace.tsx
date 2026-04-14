import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTeam } from '../contexts/TeamContext';
import { debounce } from 'lodash';
import {
  MagnifyingGlass,
  Cpu,
  Package,
  Wrench,
  Plug,
  Plugs,
  PaintBrush,
  CaretDown,
  Folder,
  Storefront,
  Books,
  Sun,
  Moon,
  Gear,
  SignOut,
  ChatCircleDots,
  Article,
  X,
  Funnel,
  Lightning,
} from '@phosphor-icons/react';
import { MobileMenu } from '../components/ui';
import {
  AgentCard,
  SkeletonCard,
  type MarketplaceItem,
} from '../components/marketplace';
import { marketplaceApi } from '../lib/api';
import toast from 'react-hot-toast';
import { isCanceledError } from '../lib/utils';
import { useTheme } from '../theme/ThemeContext';
import { SEO, generateMarketplaceStructuredData } from '../components/SEO';
import { useMarketplaceAuth } from '../contexts/MarketplaceAuthContext';

type ItemType = 'agent' | 'base' | 'theme' | 'tool' | 'integration' | 'skill' | 'mcp_server';
type SortOption =
  | 'featured'
  | 'popular'
  | 'newest'
  | 'name'
  | 'rating'
  | 'price_asc'
  | 'price_desc';
type PricingFilter = 'all' | 'free' | 'paid';

const ITEMS_PER_PAGE = 20;

// Category definitions with descriptions for category tiles
const categories = [
  { id: 'builder', label: 'Builder', description: 'General-purpose AI coding assistants' },
  { id: 'frontend', label: 'Frontend', description: 'Build beautiful user interfaces' },
  { id: 'fullstack', label: 'Fullstack', description: 'End-to-end web development' },
  { id: 'backend', label: 'Backend', description: 'APIs, databases, and servers' },
  { id: 'data', label: 'Data', description: 'Analytics, ML, and visualization' },
  { id: 'devops', label: 'DevOps', description: 'CI/CD and infrastructure' },
  { id: 'mobile', label: 'Mobile', description: 'iOS and Android apps' },
];

export default function Marketplace() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { theme, toggleTheme } = useTheme();
  const { isAuthenticated } = useMarketplaceAuth();
  const { teamSwitchKey } = useTeam();

  // Refs
  const searchInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // State - Filters
  const [selectedItemType, setSelectedItemType] = useState<ItemType>(
    (searchParams.get('type') as ItemType) || 'agent'
  );
  const [searchQuery, setSearchQuery] = useState(searchParams.get('search') || '');
  const [sortBy, setSortBy] = useState<SortOption>(
    (searchParams.get('sort') as SortOption) || 'featured'
  );
  const [pricingFilter, setPricingFilter] = useState<PricingFilter>(
    (searchParams.get('pricing') as PricingFilter) || 'all'
  );
  const [showSortDropdown, setShowSortDropdown] = useState(false);
  const [showFilterDropdown, setShowFilterDropdown] = useState(false);

  // State - Data
  const [items, setItems] = useState<MarketplaceItem[]>([]);
  const [_page, setPage] = useState(1);

  // State - Loading (isolated for non-blocking UI)
  const [initialLoading, setInitialLoading] = useState(true);
  const [filtering, setFiltering] = useState(false);

  // "/" keyboard shortcut to focus search (like GitHub, Slack, etc.)
  // Using native event listener because useHotkeys doesn't reliably handle "/" key
  useEffect(() => {
    const handleSlashKey = (e: KeyboardEvent) => {
      // Don't trigger if focused on form element
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return;
      }

      if (e.key === '/') {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };

    document.addEventListener('keydown', handleSlashKey);
    return () => document.removeEventListener('keydown', handleSlashKey);
  }, []);

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  // Mobile menu items
  const mobileMenuItems = {
    left: [
      {
        icon: <Folder className="w-5 h-5" weight="fill" />,
        title: 'Projects',
        onClick: () => navigate('/dashboard'),
      },
      {
        icon: <Storefront className="w-5 h-5" weight="fill" />,
        title: 'Marketplace',
        onClick: () => {},
        active: true,
      },
      {
        icon: <Books className="w-5 h-5" weight="fill" />,
        title: 'Library',
        onClick: () => navigate('/library'),
      },
      {
        icon: <ChatCircleDots className="w-5 h-5" weight="fill" />,
        title: 'Feedback',
        onClick: () => navigate('/feedback'),
      },
      {
        icon: <Article className="w-5 h-5" weight="fill" />,
        title: 'Documentation',
        onClick: () => window.open('https://docs.tesslate.com', '_blank'),
      },
    ],
    right: [
      {
        icon:
          theme === 'dark' ? (
            <Sun className="w-5 h-5" weight="fill" />
          ) : (
            <Moon className="w-5 h-5" weight="fill" />
          ),
        title: theme === 'dark' ? 'Light Mode' : 'Dark Mode',
        onClick: toggleTheme,
      },
      {
        icon: <Gear className="w-5 h-5" weight="fill" />,
        title: 'Settings',
        onClick: () => navigate('/settings'),
      },
      { icon: <SignOut className="w-5 h-5" weight="fill" />, title: 'Logout', onClick: logout },
    ],
  };

  const itemTypes: { id: ItemType; label: string; icon: React.ReactNode }[] = [
    { id: 'agent', label: 'Agents', icon: <Cpu size={16} /> },
    { id: 'base', label: 'Bases', icon: <Package size={16} /> },
    { id: 'tool', label: 'Tools', icon: <Wrench size={16} /> },
    { id: 'integration', label: 'Integrations', icon: <Plug size={16} /> },
    { id: 'theme', label: 'Themes', icon: <PaintBrush size={16} /> },
    { id: 'skill', label: 'Skills', icon: <Lightning size={16} /> },
    { id: 'mcp_server', label: 'Connectors', icon: <Plugs size={16} /> },
  ];

  const sortOptions: { id: SortOption; label: string }[] = [
    { id: 'featured', label: 'Featured' },
    { id: 'popular', label: 'Most Popular' },
    { id: 'newest', label: 'Recently Added' },
    { id: 'name', label: 'Name A-Z' },
    { id: 'rating', label: 'Highest Rated' },
    { id: 'price_asc', label: 'Price: Low to High' },
    { id: 'price_desc', label: 'Price: High to Low' },
  ];

  const pricingOptions: { id: PricingFilter; label: string }[] = [
    { id: 'all', label: 'All Prices' },
    { id: 'free', label: 'Free Only' },
    { id: 'paid', label: 'Paid Only' },
  ];

  // Load items with server-side filtering
  const loadItems = useCallback(
    async (params: {
      itemType: ItemType;
      category: string;
      search: string;
      sort: SortOption;
      pricing: PricingFilter;
      pageNum: number;
    }) => {
      const { itemType, category, search, sort, pricing, pageNum } = params;

      // Cancel any in-flight request
      abortControllerRef.current?.abort();
      abortControllerRef.current = new AbortController();

      // Set appropriate loading state
      if (!initialLoading) {
        setFiltering(true);
      }

      try {
        let data: MarketplaceItem[];

        if (itemType === 'agent') {
          const result = await marketplaceApi.getAllAgents(
            {
              category: category !== 'all' ? category : undefined,
              pricing_type: pricing !== 'all' ? pricing : undefined,
              search: search || undefined,
              sort,
              page: pageNum,
              limit: ITEMS_PER_PAGE,
            },
            { signal: abortControllerRef.current.signal }
          );
          data = (result.agents || []).map((agent: Record<string, unknown>) => ({
            ...agent,
            item_type: 'agent' as ItemType,
          }));
        } else if (itemType === 'base') {
          const result = await marketplaceApi.getAllBases(
            {
              category: category !== 'all' ? category : undefined,
              pricing_type: pricing !== 'all' ? pricing : undefined,
              search: search || undefined,
              sort,
              page: pageNum,
              limit: ITEMS_PER_PAGE,
            },
            { signal: abortControllerRef.current.signal }
          );
          data = (result.bases || []).map((base: Record<string, unknown>) => ({
            ...base,
            item_type: 'base' as ItemType,
          }));
        } else if (itemType === 'theme') {
          const result = await marketplaceApi.getMarketplaceThemes({
            category: category !== 'all' ? category : undefined,
            pricing: pricing !== 'all' ? pricing : undefined,
            search: search || undefined,
            sort,
            page: pageNum,
            limit: ITEMS_PER_PAGE,
          });
          data = (result.items || []).map((theme: Record<string, unknown>) => ({
            ...theme,
            item_type: 'theme' as ItemType,
          }));
        } else if (itemType === 'skill') {
          const result = await marketplaceApi.getAllSkills(
            {
              category: category !== 'all' ? category : undefined,
              pricing_type: pricing !== 'all' ? pricing : undefined,
              search: search || undefined,
              sort,
              page: pageNum,
              limit: ITEMS_PER_PAGE,
            },
            { signal: abortControllerRef.current.signal }
          );
          data = (result.skills || []).map((skill: Record<string, unknown>) => ({
            ...skill,
            item_type: 'skill' as ItemType,
          }));
        } else if (itemType === 'mcp_server') {
          const result = await marketplaceApi.getAllMcpServers(
            {
              category: category !== 'all' ? category : undefined,
              pricing_type: pricing !== 'all' ? pricing : undefined,
              search: search || undefined,
              sort,
              page: pageNum,
              limit: ITEMS_PER_PAGE,
            },
            { signal: abortControllerRef.current.signal }
          );
          data = (result.mcp_servers || []).map((server: Record<string, unknown>) => ({
            ...server,
            item_type: 'mcp_server' as ItemType,
          }));
        } else {
          // Tools and integrations - coming soon
          data = [];
        }

        setItems(data);
      } catch (err) {
        // Silently ignore cancelled requests (both native AbortError and Axios CanceledError)
        if (isCanceledError(err)) {
          return;
        }
        console.error('Failed to load marketplace:', err);
        toast.error('Failed to load marketplace');
      } finally {
        setInitialLoading(false);
        setFiltering(false);
      }
    },
    [initialLoading]
  );

  // Debounced search
  const debouncedLoadItems = useMemo(
    () =>
      debounce(
        (params: {
          itemType: ItemType;
          category: string;
          search: string;
          sort: SortOption;
          pricing: PricingFilter;
        }) => {
          setPage(1);
          loadItems({ ...params, pageNum: 1 });
        },
        300
      ),
    [loadItems]
  );

  // Cleanup debounce on unmount
  useEffect(() => {
    return () => {
      debouncedLoadItems.cancel();
      abortControllerRef.current?.abort();
    };
  }, [debouncedLoadItems]);

  // Initial load — re-fetch on team switch to update is_purchased flags
  useEffect(() => {
    loadItems({
      itemType: selectedItemType,
      category: 'all', // Main page always shows all categories
      search: searchQuery,
      sort: sortBy,
      pricing: pricingFilter,
      pageNum: 1,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamSwitchKey]);

  // Handle filter changes (with debounce for search)
  useEffect(() => {
    if (initialLoading) return;

    // Update URL params (category is handled by dedicated category pages)
    const params = new URLSearchParams();
    if (selectedItemType !== 'agent') params.set('type', selectedItemType);
    if (searchQuery) params.set('search', searchQuery);
    if (sortBy !== 'featured') params.set('sort', sortBy);
    if (pricingFilter !== 'all') params.set('pricing', pricingFilter);
    setSearchParams(params, { replace: true });

    // Debounce search, immediate for others
    if (searchQuery) {
      debouncedLoadItems({
        itemType: selectedItemType,
        category: 'all', // Main page always shows all categories
        search: searchQuery,
        sort: sortBy,
        pricing: pricingFilter,
      });
    } else {
      debouncedLoadItems.cancel();
      setPage(1);
      loadItems({
        itemType: selectedItemType,
        category: 'all', // Main page always shows all categories
        search: searchQuery,
        sort: sortBy,
        pricing: pricingFilter,
        pageNum: 1,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedItemType, searchQuery, sortBy, pricingFilter]);

  const handleInstall = async (item: MarketplaceItem) => {
    if (item.is_purchased) {
      toast.success(`${item.name} already in your library`);
      return;
    }

    if (!item.is_active) {
      return;
    }

    try {
      // Connectors (MCP servers) install straight into the Library at user
      // scope. OAuth authorization happens later via Library → Connectors →
      // Connect, so the user can review the connector before sending them
      // through a provider login flow.
      if (item.item_type === 'mcp_server') {
        await marketplaceApi.installMcpServer(item.id, undefined, { scope_level: 'user' });
        toast.success(`${item.name} added to your library — open Library → Connectors to connect.`);
        setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, is_purchased: true } : i)));
        return;
      }

      const data =
        item.item_type === 'theme'
          ? await marketplaceApi.addThemeToLibrary(item.id)
          : item.item_type === 'base'
            ? await marketplaceApi.purchaseBase(item.id)
            : item.item_type === 'skill'
              ? await marketplaceApi.purchaseSkill(item.id)
              : await marketplaceApi.purchaseAgent(item.id);

      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        toast.success(`${item.name} added to your library!`);
        setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, is_purchased: true } : i)));
      }
    } catch (error) {
      console.error('Failed to install:', error);
      toast.error('Failed to add to library');
    }
  };

  // Handle item type change
  const handleItemTypeChange = (type: ItemType) => {
    setSelectedItemType(type);
    setPage(1);
  };

  // Featured = top 3 by rating (with downloads as tiebreaker), rest go to regular
  const sortedByRating = [...items].sort((a, b) => {
    const ratingDiff = (b.rating || 0) - (a.rating || 0);
    if (ratingDiff !== 0) return ratingDiff;
    return (b.downloads || b.usage_count || 0) - (a.downloads || a.usage_count || 0);
  });
  const featuredItems = sortedByRating.slice(0, 3);
  const featuredIds = new Set(featuredItems.map((item) => item.id));
  const regularItems = items.filter((item) => !featuredIds.has(item.id));

  // Check if any filters are active
  const hasActiveFilters = pricingFilter !== 'all' || searchQuery !== '';

  return (
    <>
      <SEO
        title="AI Agents & Templates Marketplace"
        description="Discover AI-powered coding agents, project templates, and developer tools. Build faster with pre-built solutions from the Tesslate Marketplace."
        keywords={[
          'AI agents',
          'coding agents',
          'project templates',
          'developer tools',
          'code generation',
          'web development',
          'Tesslate',
        ]}
        url={typeof window !== 'undefined' ? window.location.href : undefined}
        structuredData={generateMarketplaceStructuredData()}
      />
      <MobileMenu leftItems={mobileMenuItems.left} rightItems={mobileMenuItems.right} />

      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header — sticky above scroll */}
        <div className="flex-shrink-0">
          {/* Title Row */}
          <div
            className="h-10 flex items-center justify-between gap-[6px]"
            style={{
              paddingLeft: '18px',
              paddingRight: '4px',
              borderBottom: 'var(--border-width) solid var(--border)',
            }}
          >
            {/* Mobile hamburger */}
            <button
              onClick={() => window.dispatchEvent(new Event('toggleMobileMenu'))}
              className="mobile-only btn btn-icon mr-1"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 6h16M4 12h16M4 18h16"
                />
              </svg>
            </button>
            <h2 className="text-xs font-semibold text-[var(--text)] flex-1">Marketplace</h2>
          </div>

          {/* Tab Bar — type tabs left, filter/sort right */}
          <div
            className="h-10 flex items-center justify-between"
            style={{ paddingLeft: '7px', paddingRight: '10px' }}
          >
            {/* Item Type Tabs — scrollable with fade */}
            <div
              className="flex items-center gap-1 overflow-x-auto scrollbar-none flex-1 min-w-0"
              style={{
                maskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)',
                WebkitMaskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)',
              }}
            >
              {itemTypes.map((type) => (
                <button
                  key={type.id}
                  onClick={() => handleItemTypeChange(type.id)}
                  className={`btn shrink-0 ${selectedItemType === type.id ? 'btn-tab-active' : 'btn-tab'}`}
                >
                  {type.icon}
                  {type.label}
                </button>
              ))}
            </div>

            {/* Filter + Sort */}
            <div className="flex items-center gap-[2px]">
              {/* Filter Dropdown */}
              <div className="relative">
                <button
                  onClick={() => setShowFilterDropdown(!showFilterDropdown)}
                  className={`btn btn-icon ${hasActiveFilters ? 'btn-active' : ''}`}
                  aria-label="Filter"
                >
                  <Funnel size={16} weight={hasActiveFilters ? 'fill' : 'regular'} />
                </button>

                {showFilterDropdown && (
                  <>
                    <div
                      className="fixed inset-0 z-40"
                      onClick={() => setShowFilterDropdown(false)}
                    />
                    <div
                      className="absolute right-0 top-full mt-1 z-50 min-w-[200px] py-1 rounded-[var(--radius-medium)] border bg-[var(--surface)] shadow-xl"
                      style={{
                        borderWidth: 'var(--border-width)',
                        borderColor: 'var(--border-hover)',
                      }}
                    >
                      <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">
                        Price
                      </div>
                      {pricingOptions.map((option) => (
                        <button
                          key={option.id}
                          onClick={() => setPricingFilter(option.id)}
                          className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                            pricingFilter === option.id
                              ? 'text-[var(--text)] bg-[var(--surface-hover)]'
                              : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
                          }`}
                        >
                          {option.label}
                          {pricingFilter === option.id && (
                            <svg
                              className="w-3 h-3 ml-auto"
                              fill="currentColor"
                              viewBox="0 0 16 16"
                            >
                              <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z" />
                            </svg>
                          )}
                        </button>
                      ))}

                      {hasActiveFilters && (
                        <>
                          <div className="my-1 border-t" style={{ borderColor: 'var(--border)' }} />
                          <button
                            onClick={() => {
                              setPricingFilter('all');
                              setSearchQuery('');
                              setShowFilterDropdown(false);
                            }}
                            className="w-full text-left px-3 py-1.5 text-xs text-[var(--status-error)] hover:bg-[var(--surface-hover)] transition-colors"
                          >
                            Clear all filters
                          </button>
                        </>
                      )}
                    </div>
                  </>
                )}
              </div>

              {/* Sort Dropdown */}
              <div className="relative">
                <button
                  onClick={() => setShowSortDropdown(!showSortDropdown)}
                  className={`btn ${sortBy !== 'featured' ? 'btn-active' : ''}`}
                  style={{ gap: '4px' }}
                >
                  <span className="hidden sm:inline text-xs">
                    {sortOptions.find((o) => o.id === sortBy)?.label}
                  </span>
                  <CaretDown className="w-3 h-3 opacity-50" />
                </button>

                {showSortDropdown && (
                  <>
                    <div
                      className="fixed inset-0 z-40"
                      onClick={() => setShowSortDropdown(false)}
                    />
                    <div
                      className="absolute right-0 top-full mt-1 z-50 min-w-[180px] py-1 rounded-[var(--radius-medium)] border bg-[var(--surface)] shadow-xl"
                      style={{
                        borderWidth: 'var(--border-width)',
                        borderColor: 'var(--border-hover)',
                      }}
                    >
                      <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">
                        Sort by
                      </div>
                      {sortOptions.map((option) => (
                        <button
                          key={option.id}
                          onClick={() => {
                            setSortBy(option.id);
                            setShowSortDropdown(false);
                          }}
                          className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                            sortBy === option.id
                              ? 'text-[var(--text)] bg-[var(--surface-hover)]'
                              : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
                          }`}
                        >
                          {option.label}
                          {sortBy === option.id && (
                            <svg
                              className="w-3 h-3 ml-auto"
                              fill="currentColor"
                              viewBox="0 0 16 16"
                            >
                              <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z" />
                            </svg>
                          )}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Search Bar */}
        <div className="px-5 pt-4 pb-3 border-b border-[var(--border)]">
          <div className="relative max-w-xl mx-auto flex items-center">
            <MagnifyingGlass size={18} className="absolute left-4 text-[var(--text-subtle)]" />
            <input
              ref={searchInputRef}
              type="text"
              placeholder="Search marketplace..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full h-9 pl-11 pr-10 bg-[var(--surface)] border border-[var(--border)] rounded-full text-xs text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--border-hover)] transition-colors"
            />
            {searchQuery ? (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-3 text-[var(--text-subtle)] hover:text-[var(--text)] transition-colors"
                aria-label="Clear search"
              >
                <X size={16} />
              </button>
            ) : (
              <kbd className="absolute right-4 text-[11px] font-mono text-[var(--text-subtle)] bg-[var(--surface-hover)] px-1.5 py-0.5 rounded">
                /
              </kbd>
            )}
          </div>
        </div>

        {/* Scrollable Content */}
        <div key={teamSwitchKey} className="flex-1 overflow-y-auto overflow-x-hidden" style={{ animation: 'fade-in 0.25s ease-out' }}>
          <div className={`px-5 py-5 ${filtering ? 'opacity-60' : ''} transition-opacity`}>
            {/* Initial Loading - Skeleton */}
            {initialLoading ? (
              <>
                <section className="mb-10">
                  <div className="h-4 w-32 rounded bg-[var(--surface-hover)] mb-5 animate-pulse" />
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {Array.from({ length: 3 }).map((_, i) => (
                      <SkeletonCard key={i} />
                    ))}
                  </div>
                </section>
                <section>
                  <div className="h-4 w-40 rounded bg-[var(--surface-hover)] mb-5 animate-pulse" />
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {Array.from({ length: 6 }).map((_, i) => (
                      <SkeletonCard key={i} />
                    ))}
                  </div>
                </section>
              </>
            ) : (
              <>
                {/* Featured Section */}
                {featuredItems.length > 0 && (
                  <section className="mb-10">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-xs font-semibold text-[var(--text)]">Featured</h3>
                      <button
                        onClick={() =>
                          navigate(`/marketplace/browse/${selectedItemType}?sort=rating`)
                        }
                        className="btn"
                      >
                        See All →
                      </button>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                      {featuredItems.slice(0, 3).map((item) => (
                        <AgentCard
                          key={item.id}
                          item={item}
                          onInstall={handleInstall}
                          isAuthenticated={isAuthenticated}
                        />
                      ))}
                    </div>
                  </section>
                )}

                {/* Browse by Category Section */}
                <section className="mb-10">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-xs font-semibold text-[var(--text)]">Browse by Category</h3>
                    <button onClick={() => navigate('/marketplace/browse/agent')} className="btn">
                      See All →
                    </button>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-4 gap-2">
                    {categories.map((cat) => (
                      <button
                        key={cat.id}
                        onClick={() => navigate(`/marketplace/browse/agent?category=${cat.id}`)}
                        className="p-3 rounded-[var(--radius-medium)] border border-[var(--border)] bg-[var(--surface)] text-left transition-colors hover:bg-[var(--surface-hover)] hover:border-[var(--border-hover)] group"
                      >
                        <div className="font-medium text-xs text-[var(--text)]">{cat.label}</div>
                        <div className="text-[11px] mt-0.5 line-clamp-2 text-[var(--text-muted)]">
                          {cat.description}
                        </div>
                      </button>
                    ))}
                  </div>
                </section>

                {/* All Items Section */}
                <section>
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-xs font-semibold text-[var(--text)]">
                      {searchQuery
                        ? `Results for "${searchQuery}"`
                        : `All ${itemTypes.find((t) => t.id === selectedItemType)?.label}`}
                    </h3>
                    {!searchQuery && (
                      <button
                        onClick={() => navigate(`/marketplace/browse/${selectedItemType}`)}
                        className="btn"
                      >
                        See All →
                      </button>
                    )}
                  </div>

                  {items.length > 0 ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                      {/* "All <Type>" should literally show every item — the
                          Featured section above is a curated subset, not a
                          deduper. With small catalogs (e.g. 4 connectors),
                          the previous regularItems split left only 1 card
                          here. */}
                      {items.map((item) => (
                        <AgentCard
                          key={item.id}
                          item={item}
                          onInstall={handleInstall}
                          isAuthenticated={isAuthenticated}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="text-center py-12 rounded-[var(--radius)] bg-[var(--surface)]">
                      <Package size={36} className="mx-auto mb-3 text-[var(--text-subtle)]" />
                      <p className="text-xs text-[var(--text-muted)]">
                        {searchQuery
                          ? `No ${selectedItemType}s found matching "${searchQuery}"`
                          : `No ${selectedItemType}s available yet`}
                      </p>
                      {hasActiveFilters && (
                        <button
                          onClick={() => {
                            setPricingFilter('all');
                            setSearchQuery('');
                          }}
                          className="btn btn-sm mt-3"
                        >
                          Clear Filters
                        </button>
                      )}
                    </div>
                  )}
                </section>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
