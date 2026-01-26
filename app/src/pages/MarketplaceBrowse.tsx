import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useInView } from 'react-intersection-observer';
import { debounce } from 'lodash';
import {
  ArrowLeft,
  MagnifyingGlass,
  X,
  Package,
} from '@phosphor-icons/react';
import { AgentCard, SkeletonCard, type MarketplaceItem } from '../components/marketplace';
import { UserDropdown } from '../components/ui';
import { marketplaceApi, authApi } from '../lib/api';
import toast from 'react-hot-toast';
import { useTheme } from '../theme/ThemeContext';
import { SEO, generateBreadcrumbStructuredData } from '../components/SEO';
import { useMarketplaceAuth } from '../contexts/MarketplaceAuthContext';

type ItemType = 'agent' | 'base' | 'tool' | 'integration';
type SortOption = 'featured' | 'popular' | 'newest' | 'name' | 'rating' | 'price_asc' | 'price_desc';
type PricingFilter = 'all' | 'free' | 'paid';

const ITEMS_PER_PAGE = 20;

// Category definitions
const categories = [
  { id: 'all', label: 'All Categories' },
  { id: 'builder', label: 'Builder' },
  { id: 'frontend', label: 'Frontend' },
  { id: 'fullstack', label: 'Fullstack' },
  { id: 'backend', label: 'Backend' },
  { id: 'data', label: 'Data' },
  { id: 'devops', label: 'DevOps' },
  { id: 'mobile', label: 'Mobile' },
];

const itemTypeLabels: Record<ItemType, string> = {
  agent: 'Agents',
  base: 'Bases',
  tool: 'Tools',
  integration: 'Integrations',
};

export default function MarketplaceBrowse() {
  const navigate = useNavigate();
  const { itemType: itemTypeParam } = useParams<{ itemType: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { theme } = useTheme();
  const { isAuthenticated } = useMarketplaceAuth();

  // Validate item type
  const itemType: ItemType = ['agent', 'base', 'tool', 'integration'].includes(itemTypeParam || '')
    ? (itemTypeParam as ItemType)
    : 'agent';

  // Refs
  const searchInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // State - Filters
  const [selectedCategory, setSelectedCategory] = useState<string>(
    searchParams.get('category') || 'all'
  );
  const [searchQuery, setSearchQuery] = useState(searchParams.get('search') || '');
  const [sortBy, setSortBy] = useState<SortOption>(
    (searchParams.get('sort') as SortOption) || 'popular'
  );
  const [pricingFilter, setPricingFilter] = useState<PricingFilter>(
    (searchParams.get('pricing') as PricingFilter) || 'all'
  );

  // State - Data
  const [items, setItems] = useState<MarketplaceItem[]>([]);
  const [basesCache, setBasesCache] = useState<MarketplaceItem[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [totalCount, setTotalCount] = useState<number | null>(null);

  // State - Loading
  const [initialLoading, setInitialLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [filtering, setFiltering] = useState(false);

  // State - User (for dropdown)
  const [userName, setUserName] = useState<string>('');
  const [userCredits, setUserCredits] = useState<number>(0);
  const [userTier, setUserTier] = useState<string>('free');

  // Intersection observer for infinite scroll
  const { ref: loadMoreRef, inView } = useInView({
    threshold: 0,
    rootMargin: '100px',
  });

  // "/" keyboard shortcut to focus search
  useEffect(() => {
    const handleSlashKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
      ) {
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

  // Fetch user data for dropdown (only when authenticated)
  useEffect(() => {
    if (!isAuthenticated) return;

    const fetchUserData = async () => {
      try {
        const user = await authApi.getCurrentUser();
        setUserName(user.name || user.username || 'there');
        setUserCredits(user.credits_balance || 0);
        setUserTier(user.subscription_tier || 'free');
      } catch (e) {
        console.error('Failed to fetch user data:', e);
      }
    };
    fetchUserData();
  }, [isAuthenticated]);

  const sortOptions: { id: SortOption; label: string }[] = [
    { id: 'popular', label: 'Most Popular' },
    { id: 'rating', label: 'Highest Rated' },
    { id: 'newest', label: 'Recently Added' },
    { id: 'name', label: 'Name A-Z' },
    { id: 'price_asc', label: 'Price: Low to High' },
    { id: 'price_desc', label: 'Price: High to Low' },
  ];

  const pricingOptions: { id: PricingFilter; label: string }[] = [
    { id: 'all', label: 'All Prices' },
    { id: 'free', label: 'Free' },
    { id: 'paid', label: 'Paid' },
  ];

  // Load items with server-side filtering
  const loadItems = useCallback(
    async (params: {
      category: string;
      search: string;
      sort: SortOption;
      pricing: PricingFilter;
      pageNum: number;
      append?: boolean;
    }) => {
      const { category, search, sort, pricing, pageNum, append = false } = params;

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

          if (pageNum === 1) {
            setTotalCount(result.total || data.length);
          }
          setHasMore(data.length === ITEMS_PER_PAGE);
        } else if (itemType === 'base') {
          // Bases use client-side filtering
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
          if (pageNum === 1) {
            setTotalCount(data.length);
          }
          setHasMore(false);
        } else {
          data = [];
          setTotalCount(0);
          setHasMore(false);
        }

        if (append && pageNum > 1) {
          setItems((prev) => [...prev, ...data]);
        } else {
          setItems(data);
        }
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          return;
        }
        console.error('Failed to load:', err);
        toast.error('Failed to load items');
      } finally {
        setInitialLoading(false);
        setLoadingMore(false);
        setFiltering(false);
      }
    },
    [itemType, basesCache, initialLoading]
  );

  // Client-side filtering for bases
  const filterBasesClientSide = (
    bases: MarketplaceItem[],
    filters: { category: string; search: string; sort: SortOption; pricing: PricingFilter }
  ): MarketplaceItem[] => {
    let filtered = [...bases];

    if (filters.category !== 'all') {
      filtered = filtered.filter(
        (item) => item.category?.toLowerCase() === filters.category.toLowerCase()
      );
    }

    if (filters.search) {
      const query = filters.search.toLowerCase();
      filtered = filtered.filter(
        (item) =>
          item.name.toLowerCase().includes(query) ||
          item.description.toLowerCase().includes(query) ||
          item.tags?.some((tag) => tag.toLowerCase().includes(query))
      );
    }

    if (filters.pricing === 'free') {
      filtered = filtered.filter((item) => item.pricing_type === 'free' || item.price === 0);
    } else if (filters.pricing === 'paid') {
      filtered = filtered.filter((item) => item.pricing_type !== 'free' && item.price > 0);
    }

    switch (filters.sort) {
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
        (params: { category: string; search: string; sort: SortOption; pricing: PricingFilter }) => {
          setPage(1);
          loadItems({ ...params, pageNum: 1 });
        },
        300
      ),
    [loadItems]
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      debouncedLoadItems.cancel();
      abortControllerRef.current?.abort();
    };
  }, [debouncedLoadItems]);

  // Initial load
  useEffect(() => {
    setInitialLoading(true);
    setItems([]);
    setPage(1);
    loadItems({
      category: selectedCategory,
      search: searchQuery,
      sort: sortBy,
      pricing: pricingFilter,
      pageNum: 1,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemType]);

  // Handle filter changes
  useEffect(() => {
    if (initialLoading) return;

    // Update URL params
    const params = new URLSearchParams();
    if (selectedCategory !== 'all') params.set('category', selectedCategory);
    if (searchQuery) params.set('search', searchQuery);
    if (sortBy !== 'popular') params.set('sort', sortBy);
    if (pricingFilter !== 'all') params.set('pricing', pricingFilter);
    setSearchParams(params, { replace: true });

    if (searchQuery) {
      debouncedLoadItems({
        category: selectedCategory,
        search: searchQuery,
        sort: sortBy,
        pricing: pricingFilter,
      });
    } else {
      debouncedLoadItems.cancel();
      setPage(1);
      loadItems({
        category: selectedCategory,
        search: searchQuery,
        sort: sortBy,
        pricing: pricingFilter,
        pageNum: 1,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCategory, searchQuery, sortBy, pricingFilter]);

  // Infinite scroll
  useEffect(() => {
    if (inView && hasMore && !loadingMore && !initialLoading && !filtering) {
      const nextPage = page + 1;
      setPage(nextPage);
      loadItems({
        category: selectedCategory,
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
        item.item_type === 'base'
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

  const hasActiveFilters =
    selectedCategory !== 'all' || pricingFilter !== 'all' || searchQuery !== '';

  // Generate SEO data
  const baseUrl = typeof window !== 'undefined' ? window.location.origin : 'https://tesslate.com';
  const itemTypeLabel = itemTypeLabels[itemType];
  const breadcrumbData = generateBreadcrumbStructuredData([
    { name: 'Marketplace', url: `${baseUrl}/marketplace` },
    { name: itemTypeLabel, url: `${baseUrl}/marketplace/browse/${itemType}` },
  ]);

  return (
    <>
      <SEO
        title={`Browse All ${itemTypeLabel} - Tesslate Marketplace`}
        description={`Discover and browse all ${itemTypeLabel.toLowerCase()} available on Tesslate Marketplace. Filter by category, price, and more to find the perfect AI-powered tools for your projects.`}
        keywords={[itemTypeLabel, 'AI agents', 'coding agents', 'project templates', 'developer tools', 'Tesslate', 'browse marketplace']}
        url={`${baseUrl}/marketplace/browse/${itemType}`}
        structuredData={breadcrumbData}
      />
      <div className="h-screen overflow-y-auto bg-[var(--bg)]">
        {/* Header */}
      <div
        className={`border-b ${theme === 'light' ? 'border-black/10 bg-white/80' : 'border-white/10 bg-[#0a0a0a]/80'} backdrop-blur-xl sticky top-0 z-40`}
      >
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="py-4 sm:py-6">
            <button
              onClick={() => navigate('/marketplace')}
              className={`
                flex items-center gap-2 mb-3 text-sm transition-colors
                ${theme === 'light' ? 'text-black/60 hover:text-black' : 'text-white/60 hover:text-white'}
              `}
            >
              <ArrowLeft size={16} />
              Back to Marketplace
            </button>

            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <h1
                  className={`font-heading text-xl sm:text-2xl font-bold ${theme === 'light' ? 'text-black' : 'text-white'}`}
                >
                  Browse {itemTypeLabels[itemType]}
                </h1>
                {totalCount !== null && (
                  <p className={`text-sm mt-1 ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}>
                    {totalCount} {totalCount === 1 ? 'result' : 'results'}
                  </p>
                )}
              </div>

              <div className="flex items-center gap-3">
                {/* Search Bar - Mobile & Desktop */}
                <div
                  className={`
                    relative flex items-center gap-3 px-4 py-2.5 rounded-xl border w-full sm:w-80
                    ${
                      theme === 'light'
                        ? 'bg-black/5 border-black/10'
                        : 'bg-white/5 border-white/10'
                    }
                  `}
                >
                <MagnifyingGlass
                  size={18}
                  className={theme === 'light' ? 'text-black/40' : 'text-white/40'}
                />
                <input
                  ref={searchInputRef}
                  type="text"
                  placeholder="Search... (press /)"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className={`
                    flex-1 bg-transparent outline-none focus-visible:outline-none text-sm
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
                    <X size={14} />
                  </button>
                )}
                </div>

                {/* User Dropdown - Only show when authenticated */}
                {isAuthenticated && (
                  <UserDropdown
                    userName={userName}
                    userCredits={userCredits}
                    userTier={userTier}
                  />
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content with Sidebar */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="flex flex-col lg:flex-row gap-6">
          {/* Sidebar Filters - Hidden on mobile, shown as horizontal on tablet, sidebar on desktop */}
          <aside
            className={`
              lg:w-56 flex-shrink-0
              ${theme === 'light' ? 'lg:border-r lg:border-black/10' : 'lg:border-r lg:border-white/10'}
              lg:pr-6
            `}
          >
            {/* Mobile/Tablet: Horizontal filter row */}
            <div className="flex flex-wrap gap-2 lg:hidden mb-4">
              {/* Category Select */}
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                className={`
                  px-3 py-2 rounded-lg text-sm border
                  ${
                    theme === 'light'
                      ? 'bg-white border-black/10 text-black'
                      : 'bg-white/5 border-white/10 text-white'
                  }
                `}
              >
                {categories.map((cat) => (
                  <option key={cat.id} value={cat.id}>
                    {cat.label}
                  </option>
                ))}
              </select>

              {/* Price Select */}
              <select
                value={pricingFilter}
                onChange={(e) => setPricingFilter(e.target.value as PricingFilter)}
                className={`
                  px-3 py-2 rounded-lg text-sm border
                  ${
                    theme === 'light'
                      ? 'bg-white border-black/10 text-black'
                      : 'bg-white/5 border-white/10 text-white'
                  }
                `}
              >
                {pricingOptions.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.label}
                  </option>
                ))}
              </select>

              {/* Sort Select */}
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as SortOption)}
                className={`
                  px-3 py-2 rounded-lg text-sm border
                  ${
                    theme === 'light'
                      ? 'bg-white border-black/10 text-black'
                      : 'bg-white/5 border-white/10 text-white'
                  }
                `}
              >
                {sortOptions.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Desktop: Sidebar filters */}
            <div className="hidden lg:block space-y-6">
              {/* Categories */}
              <div>
                <h3
                  className={`text-xs font-semibold uppercase tracking-wider mb-3 ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}
                >
                  Category
                </h3>
                <div className="space-y-1">
                  {categories.map((cat) => (
                    <button
                      key={cat.id}
                      onClick={() => setSelectedCategory(cat.id)}
                      className={`
                        w-full text-left px-3 py-2 rounded-lg text-sm transition-colors
                        ${
                          selectedCategory === cat.id
                            ? theme === 'light'
                              ? 'bg-black/10 text-black font-medium'
                              : 'bg-white/10 text-white font-medium'
                            : theme === 'light'
                              ? 'text-black/70 hover:bg-black/5 hover:text-black'
                              : 'text-white/70 hover:bg-white/5 hover:text-white'
                        }
                      `}
                    >
                      {cat.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Price Filter */}
              <div>
                <h3
                  className={`text-xs font-semibold uppercase tracking-wider mb-3 ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}
                >
                  Price
                </h3>
                <div className="space-y-1">
                  {pricingOptions.map((opt) => (
                    <button
                      key={opt.id}
                      onClick={() => setPricingFilter(opt.id)}
                      className={`
                        w-full text-left px-3 py-2 rounded-lg text-sm transition-colors
                        ${
                          pricingFilter === opt.id
                            ? theme === 'light'
                              ? 'bg-black/10 text-black font-medium'
                              : 'bg-white/10 text-white font-medium'
                            : theme === 'light'
                              ? 'text-black/70 hover:bg-black/5 hover:text-black'
                              : 'text-white/70 hover:bg-white/5 hover:text-white'
                        }
                      `}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Sort */}
              <div>
                <h3
                  className={`text-xs font-semibold uppercase tracking-wider mb-3 ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}
                >
                  Sort By
                </h3>
                <div className="space-y-1">
                  {sortOptions.map((opt) => (
                    <button
                      key={opt.id}
                      onClick={() => setSortBy(opt.id)}
                      className={`
                        w-full text-left px-3 py-2 rounded-lg text-sm transition-colors
                        ${
                          sortBy === opt.id
                            ? theme === 'light'
                              ? 'bg-black/10 text-black font-medium'
                              : 'bg-white/10 text-white font-medium'
                            : theme === 'light'
                              ? 'text-black/70 hover:bg-black/5 hover:text-black'
                              : 'text-white/70 hover:bg-white/5 hover:text-white'
                        }
                      `}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Clear Filters */}
              {hasActiveFilters && (
                <button
                  onClick={() => {
                    setSelectedCategory('all');
                    setPricingFilter('all');
                    setSearchQuery('');
                  }}
                  className={`
                    w-full px-3 py-2 text-sm rounded-lg border transition-colors
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
          </aside>

          {/* Main Content */}
          <main className={`flex-1 ${filtering ? 'opacity-60' : ''} transition-opacity`}>
            {initialLoading ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {Array.from({ length: 9 }).map((_, i) => (
                  <SkeletonCard key={i} />
                ))}
              </div>
            ) : items.length > 0 || loadingMore ? (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {items.map((item) => (
                    <AgentCard key={item.id} item={item} onInstall={handleInstall} isAuthenticated={isAuthenticated} />
                  ))}
                  {loadingMore &&
                    Array.from({ length: 3 }).map((_, i) => <SkeletonCard key={`loading-${i}`} />)}
                </div>

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
                    ? `No ${itemType}s found matching "${searchQuery}"`
                    : `No ${itemType}s available${selectedCategory !== 'all' ? ` in ${selectedCategory}` : ''}`}
                </p>
                {hasActiveFilters && (
                  <button
                    onClick={() => {
                      setSelectedCategory('all');
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
          </main>
        </div>
      </div>
    </div>
    </>
  );
}
