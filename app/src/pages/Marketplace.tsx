import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useInView } from 'react-intersection-observer';
import { debounce } from 'lodash';
import {
  MagnifyingGlass,
  Cpu,
  Package,
  Wrench,
  Plug,
  PaintBrush,
  CaretDown,
  Folder,
  Storefront,
  Books,
  Sun,
  Moon,
  Gear,
  SignOut,
  X,
  Funnel,
} from '@phosphor-icons/react';
import { MobileMenu, UserDropdown } from '../components/ui';
import {
  AgentCard,
  FeaturedCard,
  SkeletonCard,
  type MarketplaceItem,
} from '../components/marketplace';
import { marketplaceApi } from '../lib/api';
import toast from 'react-hot-toast';
import { isCanceledError } from '../lib/utils';
import { useTheme } from '../theme/ThemeContext';
import { SEO, generateMarketplaceStructuredData } from '../components/SEO';
import { useMarketplaceAuth } from '../contexts/MarketplaceAuthContext';

type ItemType = 'agent' | 'base' | 'theme' | 'tool' | 'integration';
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
  const [basesCache, setBasesCache] = useState<MarketplaceItem[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);

  // State - Loading (isolated for non-blocking UI)
  const [initialLoading, setInitialLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [filtering, setFiltering] = useState(false);

  // Intersection observer for infinite scroll
  const { ref: loadMoreRef, inView } = useInView({
    threshold: 0,
    rootMargin: '100px',
  });

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
      append?: boolean;
    }) => {
      const { itemType, category, search, sort, pricing, pageNum, append = false } = params;

      // Cancel any in-flight request
      abortControllerRef.current?.abort();
      abortControllerRef.current = new AbortController();

      // Set appropriate loading state
      if (pageNum === 1 && !append) {
        if (initialLoading) {
          // Keep initial loading
        } else {
          setFiltering(true);
        }
      } else {
        setLoadingMore(true);
      }

      try {
        let data: MarketplaceItem[];

        if (itemType === 'agent') {
          // Server-side filtering for agents
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

          // Check if there are more items
          setHasMore(data.length === ITEMS_PER_PAGE);
        } else if (itemType === 'base') {
          // Bases use client-side filtering (API doesn't support same params)
          if (basesCache.length === 0) {
            const result = await marketplaceApi.getAllBases();
            const bases = (result.bases || []).map((base: Record<string, unknown>) => ({
              ...base,
              item_type: 'base' as ItemType,
            }));
            setBasesCache(bases);
            data = filterBasesClientSide(bases, { category, search, sort, pricing });
          } else {
            data = filterBasesClientSide(basesCache, { category, search, sort, pricing });
          }
          setHasMore(false); // Bases loaded all at once
        } else if (itemType === 'theme') {
          // Server-side filtering for themes
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
          setHasMore(data.length === ITEMS_PER_PAGE);
        } else {
          // Tools and integrations - coming soon
          data = [];
          setHasMore(false);
        }

        // Update items
        if (append && pageNum > 1) {
          setItems((prev) => [...prev, ...data]);
        } else {
          setItems(data);
        }
      } catch (err) {
        // Silently ignore cancelled requests (both native AbortError and Axios CanceledError)
        if (isCanceledError(err)) {
          return;
        }
        console.error('Failed to load marketplace:', err);
        toast.error('Failed to load marketplace');
      } finally {
        setInitialLoading(false);
        setLoadingMore(false);
        setFiltering(false);
      }
    },
    [basesCache, initialLoading]
  );

  // Client-side filtering for bases (until backend supports it)
  const filterBasesClientSide = (
    bases: MarketplaceItem[],
    filters: { category: string; search: string; sort: SortOption; pricing: PricingFilter }
  ): MarketplaceItem[] => {
    let filtered = [...bases];

    // Category filter
    if (filters.category !== 'all') {
      filtered = filtered.filter(
        (item) => item.category?.toLowerCase() === filters.category.toLowerCase()
      );
    }

    // Search filter
    if (filters.search) {
      const query = filters.search.toLowerCase();
      filtered = filtered.filter(
        (item) =>
          item.name.toLowerCase().includes(query) ||
          item.description.toLowerCase().includes(query) ||
          item.tags?.some((tag) => tag.toLowerCase().includes(query))
      );
    }

    // Pricing filter
    if (filters.pricing === 'free') {
      filtered = filtered.filter((item) => item.pricing_type === 'free' || item.price === 0);
    } else if (filters.pricing === 'paid') {
      filtered = filtered.filter((item) => item.pricing_type !== 'free' && item.price > 0);
    }

    // Sort
    switch (filters.sort) {
      case 'featured':
        filtered.sort((a, b) => (b.is_featured ? 1 : 0) - (a.is_featured ? 1 : 0));
        break;
      case 'popular':
        filtered.sort(
          (a, b) => (b.downloads || b.usage_count || 0) - (a.downloads || a.usage_count || 0)
        );
        break;
      case 'newest':
        filtered.sort((a, b) => b.id.localeCompare(a.id));
        break;
      case 'name':
        filtered.sort((a, b) => a.name.localeCompare(b.name));
        break;
      case 'rating':
        filtered.sort((a, b) => (b.rating || 0) - (a.rating || 0));
        break;
      case 'price_asc':
        filtered.sort((a, b) => (a.price || 0) - (b.price || 0));
        break;
      case 'price_desc':
        filtered.sort((a, b) => (b.price || 0) - (a.price || 0));
        break;
    }

    return filtered;
  };

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

  // Initial load
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
  }, []);

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

  // Infinite scroll - load more when intersection triggers
  useEffect(() => {
    if (inView && hasMore && !loadingMore && !initialLoading && !filtering) {
      const nextPage = page + 1;
      setPage(nextPage);
      loadItems({
        itemType: selectedItemType,
        category: 'all', // Main page always shows all categories
        search: searchQuery,
        sort: sortBy,
        pricing: pricingFilter,
        pageNum: nextPage,
        append: true,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inView, hasMore, loadingMore, initialLoading, filtering]);

  const handleInstall = async (item: MarketplaceItem) => {
    if (item.is_purchased) {
      toast.success(`${item.name} already in your library`);
      return;
    }

    if (!item.is_active) {
      return;
    }

    try {
      const data =
        item.item_type === 'theme'
          ? await marketplaceApi.addThemeToLibrary(item.id)
          : item.item_type === 'base'
            ? await marketplaceApi.purchaseBase(item.id)
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

      <div className="h-screen overflow-y-auto bg-[var(--bg)]">
        {/* Header */}
        <div
          className={`border-b ${theme === 'light' ? 'border-black/10 bg-white/80' : 'border-white/10 bg-[#0a0a0a]/80'} backdrop-blur-xl sticky top-0 z-40`}
        >
          <div className="max-w-6xl mx-auto px-6 md:px-12">
            {/* Top Bar */}
            <div className="h-14 flex items-center justify-between">
              <h1
                className={`font-heading text-xl font-bold ${theme === 'light' ? 'text-black' : 'text-white'}`}
              >
                Marketplace
              </h1>

              <div className="flex items-center gap-3">
                {/* User Dropdown - Only show when authenticated */}
                {isAuthenticated && <UserDropdown />}

                {/* Mobile hamburger */}
                <button
                  onClick={() => window.dispatchEvent(new Event('toggleMobileMenu'))}
                  className="md:hidden p-2 hover:bg-white/10 active:bg-white/20 rounded-lg transition-colors"
                >
                  <svg
                    className="w-6 h-6 text-[var(--text)]"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M4 6h16M4 12h16M4 18h16"
                    />
                  </svg>
                </button>
              </div>
            </div>

            {/* Search Bar */}
            <div className="py-6">
              <div
                className={`
                relative max-w-2xl mx-auto flex items-center gap-3 px-4 py-3 rounded-xl border
                ${theme === 'light' ? 'bg-black/5 border-black/10' : 'bg-white/5 border-white/10'}
              `}
              >
                <MagnifyingGlass
                  size={20}
                  className={theme === 'light' ? 'text-black/40' : 'text-white/40'}
                />
                <input
                  ref={searchInputRef}
                  type="text"
                  placeholder="Search extensions..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className={`
                    flex-1 bg-transparent outline-none !outline-none focus:outline-none focus-visible:outline-none focus:ring-0 text-sm
                    ${theme === 'light' ? 'text-black placeholder-black/40' : 'text-white placeholder-white/40'}
                  `}
                />
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery('')}
                    className={`
                      p-1 rounded-full transition-colors
                      ${theme === 'light' ? 'hover:bg-black/10 text-black/40' : 'hover:bg-white/10 text-white/40'}
                    `}
                    aria-label="Clear search"
                  >
                    <X size={16} />
                  </button>
                )}
                <kbd
                  className={`
                  hidden sm:flex items-center gap-1 px-2 py-1 rounded text-xs font-mono
                  ${theme === 'light' ? 'bg-black/10 text-black/50' : 'bg-white/10 text-white/50'}
                `}
                >
                  /
                </kbd>
              </div>
            </div>

            {/* Tab Navigation */}
            <div className="flex items-center justify-between pb-4 gap-4">
              {/* Item Type Tabs */}
              <div className="flex items-center gap-1 overflow-x-auto">
                {itemTypes.map((type) => (
                  <button
                    key={type.id}
                    onClick={() => handleItemTypeChange(type.id)}
                    className={`
                      flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap
                      ${
                        selectedItemType === type.id
                          ? 'bg-[var(--primary)] text-white'
                          : theme === 'light'
                            ? 'text-black/60 hover:text-black hover:bg-black/5'
                            : 'text-white/60 hover:text-white hover:bg-white/5'
                      }
                    `}
                  >
                    {type.icon}
                    <span className="hidden sm:inline">{type.label}</span>
                  </button>
                ))}
              </div>

              {/* Filter & Sort */}
              <div className="flex items-center gap-2">
                {/* Filter Dropdown */}
                <div className="relative">
                  <button
                    onClick={() => setShowFilterDropdown(!showFilterDropdown)}
                    className={`
                      flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all
                      ${hasActiveFilters ? 'bg-[var(--primary)]/10 text-[var(--primary)]' : ''}
                      ${
                        theme === 'light'
                          ? 'text-black/60 hover:text-black hover:bg-black/5'
                          : 'text-white/60 hover:text-white hover:bg-white/5'
                      }
                    `}
                  >
                    <Funnel size={16} />
                    <span className="hidden sm:inline">Filter</span>
                    {hasActiveFilters && (
                      <span className="w-2 h-2 rounded-full bg-[var(--primary)]" />
                    )}
                  </button>

                  {showFilterDropdown && (
                    <>
                      <div
                        className="fixed inset-0 z-40"
                        onClick={() => setShowFilterDropdown(false)}
                      />
                      <div
                        className={`
                        absolute right-0 top-full mt-2 py-3 px-4 rounded-xl border shadow-xl z-50 min-w-[200px]
                        ${
                          theme === 'light'
                            ? 'bg-white border-black/10'
                            : 'bg-[#1a1a1c] border-white/10'
                        }
                      `}
                      >
                        <div className="mb-3">
                          <label
                            className={`text-xs font-medium uppercase tracking-wider ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}
                          >
                            Price
                          </label>
                          <div className="mt-2 space-y-1">
                            {pricingOptions.map((option) => (
                              <button
                                key={option.id}
                                onClick={() => {
                                  setPricingFilter(option.id);
                                }}
                                className={`
                                  w-full px-3 py-2 text-left text-sm rounded-lg transition-colors
                                  ${
                                    pricingFilter === option.id
                                      ? 'bg-[var(--primary)]/10 text-[var(--primary)]'
                                      : theme === 'light'
                                        ? 'text-black/70 hover:bg-black/5'
                                        : 'text-white/70 hover:bg-white/5'
                                  }
                                `}
                              >
                                {option.label}
                              </button>
                            ))}
                          </div>
                        </div>

                        {hasActiveFilters && (
                          <button
                            onClick={() => {
                              setPricingFilter('all');
                              setSearchQuery('');
                              setShowFilterDropdown(false);
                            }}
                            className={`
                              w-full px-3 py-2 text-sm rounded-lg border mt-2
                              ${
                                theme === 'light'
                                  ? 'border-black/10 text-black/60 hover:bg-black/5'
                                  : 'border-white/10 text-white/60 hover:bg-white/5'
                              }
                            `}
                          >
                            Clear All Filters
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </div>

                {/* Sort Dropdown */}
                <div className="relative">
                  <button
                    onClick={() => setShowSortDropdown(!showSortDropdown)}
                    className={`
                      flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all
                      ${
                        theme === 'light'
                          ? 'text-black/60 hover:text-black hover:bg-black/5'
                          : 'text-white/60 hover:text-white hover:bg-white/5'
                      }
                    `}
                  >
                    <span className="hidden sm:inline">
                      {sortOptions.find((o) => o.id === sortBy)?.label}
                    </span>
                    <CaretDown size={14} />
                  </button>

                  {showSortDropdown && (
                    <>
                      <div
                        className="fixed inset-0 z-40"
                        onClick={() => setShowSortDropdown(false)}
                      />
                      <div
                        className={`
                        absolute right-0 top-full mt-2 py-2 rounded-xl border shadow-xl z-50 min-w-[180px]
                        ${
                          theme === 'light'
                            ? 'bg-white border-black/10'
                            : 'bg-[#1a1a1c] border-white/10'
                        }
                      `}
                      >
                        {sortOptions.map((option) => (
                          <button
                            key={option.id}
                            onClick={() => {
                              setSortBy(option.id);
                              setShowSortDropdown(false);
                            }}
                            className={`
                              w-full px-4 py-2 text-left text-sm transition-colors
                              ${
                                sortBy === option.id
                                  ? 'text-[var(--primary)]'
                                  : theme === 'light'
                                    ? 'text-black/70 hover:bg-black/5'
                                    : 'text-white/70 hover:bg-white/5'
                              }
                            `}
                          >
                            {option.label}
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div
          className={`max-w-6xl mx-auto px-6 md:px-12 py-8 ${filtering ? 'opacity-60' : ''} transition-opacity`}
        >
          {/* Initial Loading - Skeleton */}
          {initialLoading ? (
            <>
              {/* Featured skeleton */}
              <section className="mb-12">
                <div
                  className={`h-6 w-32 rounded mb-6 ${theme === 'light' ? 'bg-black/10' : 'bg-white/10'} animate-pulse`}
                />
                <div className="space-y-4">
                  <SkeletonCard variant="featured" />
                  <SkeletonCard variant="featured" />
                </div>
              </section>

              {/* Grid skeleton */}
              <section>
                <div
                  className={`h-6 w-40 rounded mb-6 ${theme === 'light' ? 'bg-black/10' : 'bg-white/10'} animate-pulse`}
                />
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <SkeletonCard key={i} />
                  ))}
                </div>
              </section>
            </>
          ) : (
            <>
              {/* Featured Section */}
              {featuredItems.length > 0 && (
                <section className="mb-12">
                  <div className="flex items-center justify-between mb-6">
                    <h2
                      className={`font-heading text-xl font-bold ${theme === 'light' ? 'text-black' : 'text-white'}`}
                    >
                      Featured
                    </h2>
                    <button
                      onClick={() =>
                        navigate(`/marketplace/browse/${selectedItemType}?sort=rating`)
                      }
                      className={`
                        flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-full transition-colors
                        ${theme === 'light' ? 'bg-black/5 hover:bg-black/10 text-black/70 hover:text-black' : 'bg-white/10 hover:bg-white/15 text-white/80 hover:text-white'}
                      `}
                    >
                      See All
                      <span className="text-lg">→</span>
                    </button>
                  </div>
                  <div className="space-y-4">
                    {featuredItems.slice(0, 3).map((item) => (
                      <FeaturedCard
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
              <section className="mb-12">
                <div className="flex items-center justify-between mb-6">
                  <h2
                    className={`font-heading text-xl font-bold ${theme === 'light' ? 'text-black' : 'text-white'}`}
                  >
                    Browse by Category
                  </h2>
                  <button
                    onClick={() => navigate('/marketplace/browse/agent')}
                    className={`
                      flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-full transition-colors
                      ${theme === 'light' ? 'bg-black/5 hover:bg-black/10 text-black/70 hover:text-black' : 'bg-white/10 hover:bg-white/15 text-white/80 hover:text-white'}
                    `}
                  >
                    See All
                    <span className="text-lg">→</span>
                  </button>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-3">
                  {categories.map((cat) => (
                    <button
                      key={cat.id}
                      onClick={() => navigate(`/marketplace/browse/agent?category=${cat.id}`)}
                      className={`
                        p-4 rounded-xl border text-left transition-all group
                        ${
                          theme === 'light'
                            ? 'bg-white border-black/10 hover:border-[var(--primary)] hover:shadow-lg'
                            : 'bg-white/5 border-white/10 hover:border-[var(--primary)] hover:bg-white/10'
                        }
                      `}
                    >
                      <div
                        className={`font-medium text-sm ${theme === 'light' ? 'text-black' : 'text-white'}`}
                      >
                        {cat.label}
                      </div>
                      <div
                        className={`text-xs mt-1 line-clamp-2 ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}
                      >
                        {cat.description}
                      </div>
                    </button>
                  ))}
                </div>
              </section>

              {/* All Items Section */}
              <section>
                <div className="flex items-center justify-between mb-6">
                  <h2
                    className={`font-heading text-xl font-bold ${theme === 'light' ? 'text-black' : 'text-white'}`}
                  >
                    {searchQuery
                      ? `Results for "${searchQuery}"`
                      : `All ${itemTypes.find((t) => t.id === selectedItemType)?.label}`}
                  </h2>
                  {!searchQuery && (
                    <button
                      onClick={() => navigate(`/marketplace/browse/${selectedItemType}`)}
                      className={`
                        flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-full transition-colors
                        ${theme === 'light' ? 'bg-black/5 hover:bg-black/10 text-black/70 hover:text-black' : 'bg-white/10 hover:bg-white/15 text-white/80 hover:text-white'}
                      `}
                    >
                      See All
                      <span className="text-lg">→</span>
                    </button>
                  )}
                </div>

                {regularItems.length > 0 || loadingMore ? (
                  <>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                      {regularItems.map((item) => (
                        <AgentCard
                          key={item.id}
                          item={item}
                          onInstall={handleInstall}
                          isAuthenticated={isAuthenticated}
                        />
                      ))}
                      {/* Loading more skeletons */}
                      {loadingMore &&
                        Array.from({ length: 4 }).map((_, i) => (
                          <SkeletonCard key={`loading-${i}`} />
                        ))}
                    </div>

                    {/* Infinite scroll trigger */}
                    {hasMore && !loadingMore && <div ref={loadMoreRef} className="h-10 mt-4" />}
                  </>
                ) : (
                  <div
                    className={`
                    text-center py-16 rounded-2xl
                    ${theme === 'light' ? 'bg-black/5' : 'bg-white/5'}
                  `}
                  >
                    <Package
                      size={48}
                      className={`mx-auto mb-4 ${theme === 'light' ? 'text-black/20' : 'text-white/20'}`}
                    />
                    <p className={theme === 'light' ? 'text-black/40' : 'text-white/40'}>
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
                        className="mt-4 px-4 py-2 bg-[var(--primary)] text-white rounded-lg text-sm font-medium hover:bg-[var(--primary-hover)] transition-colors"
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
    </>
  );
}
