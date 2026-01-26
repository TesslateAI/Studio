import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useInView } from 'react-intersection-observer';
import { debounce } from 'lodash';
import {
  ArrowLeft,
  CaretDown,
  Package,
  MagnifyingGlass,
  X,
} from '@phosphor-icons/react';
import { AgentCard, SkeletonCard, type MarketplaceItem } from '../components/marketplace';
import { UserDropdown } from '../components/ui';
import { marketplaceApi, authApi } from '../lib/api';
import toast from 'react-hot-toast';
import { useTheme } from '../theme/ThemeContext';
import { SEO, generateBreadcrumbStructuredData } from '../components/SEO';
import { useMarketplaceAuth } from '../contexts/MarketplaceAuthContext';

type SortOption = 'featured' | 'popular' | 'newest' | 'name' | 'rating' | 'price_asc' | 'price_desc';
type PricingFilter = 'all' | 'free' | 'paid';

const ITEMS_PER_PAGE = 20;

// Category definitions with metadata
const categoryMeta: Record<string, { label: string; description: string }> = {
  builder: { label: 'Builder', description: 'General-purpose AI coding assistants for any project' },
  frontend: { label: 'Frontend', description: 'Build beautiful user interfaces with modern frameworks' },
  fullstack: { label: 'Fullstack', description: 'End-to-end web application development' },
  backend: { label: 'Backend', description: 'APIs, databases, and server-side logic' },
  data: { label: 'Data', description: 'Data analysis, visualization, and machine learning' },
  devops: { label: 'DevOps', description: 'CI/CD, infrastructure, and deployment automation' },
  mobile: { label: 'Mobile', description: 'iOS, Android, and cross-platform mobile apps' },
};

export default function MarketplaceCategory() {
  const navigate = useNavigate();
  const { category } = useParams<{ category: string }>();
  const { theme } = useTheme();
  const { isAuthenticated } = useMarketplaceAuth();

  // Refs
  const searchInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Get category metadata
  const meta = category ? categoryMeta[category] : null;

  // State - Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<SortOption>('popular');
  const [pricingFilter, setPricingFilter] = useState<PricingFilter>('all');
  const [showSortDropdown, setShowSortDropdown] = useState(false);
  const [showPriceDropdown, setShowPriceDropdown] = useState(false);

  // State - Data
  const [items, setItems] = useState<MarketplaceItem[]>([]);
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

  // "/" keyboard shortcut to focus search (like GitHub, Slack, etc.)
  // Using native event listener because useHotkeys doesn't reliably handle "/" key
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
    { id: 'free', label: 'Free Only' },
    { id: 'paid', label: 'Paid Only' },
  ];

  // Load items with server-side filtering
  const loadItems = useCallback(
    async (params: {
      search: string;
      sort: SortOption;
      pricing: PricingFilter;
      pageNum: number;
      append?: boolean;
    }) => {
      if (!category) return;

      const { search, sort, pricing, pageNum, append = false } = params;

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
        const result = await marketplaceApi.getAllAgents(
          {
            category,
            pricing_type: pricing !== 'all' ? pricing : undefined,
            search: search || undefined,
            sort,
            page: pageNum,
            limit: ITEMS_PER_PAGE,
          },
          { signal: abortControllerRef.current.signal }
        );

        const data = (result.agents || []).map((agent: Record<string, unknown>) => ({
          ...agent,
          item_type: 'agent' as const,
        }));

        // Update total count on first page
        if (pageNum === 1) {
          setTotalCount(result.total || data.length);
        }

        // Check if there are more items
        setHasMore(data.length === ITEMS_PER_PAGE);

        // Update items
        if (append && pageNum > 1) {
          setItems((prev) => [...prev, ...data]);
        } else {
          setItems(data);
        }
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          return;
        }
        console.error('Failed to load category:', err);
        toast.error('Failed to load items');
      } finally {
        setInitialLoading(false);
        setLoadingMore(false);
        setFiltering(false);
      }
    },
    [category, initialLoading]
  );

  // Debounced search
  const debouncedLoadItems = useMemo(
    () =>
      debounce(
        (params: { search: string; sort: SortOption; pricing: PricingFilter }) => {
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

  // Initial load when category changes
  useEffect(() => {
    if (category) {
      setInitialLoading(true);
      setItems([]);
      setPage(1);
      loadItems({
        search: searchQuery,
        sort: sortBy,
        pricing: pricingFilter,
        pageNum: 1,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category]);

  // Handle filter changes
  useEffect(() => {
    if (initialLoading || !category) return;

    if (searchQuery) {
      debouncedLoadItems({
        search: searchQuery,
        sort: sortBy,
        pricing: pricingFilter,
      });
    } else {
      debouncedLoadItems.cancel();
      setPage(1);
      loadItems({
        search: searchQuery,
        sort: sortBy,
        pricing: pricingFilter,
        pageNum: 1,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery, sortBy, pricingFilter]);

  // Infinite scroll
  useEffect(() => {
    if (inView && hasMore && !loadingMore && !initialLoading && !filtering) {
      const nextPage = page + 1;
      setPage(nextPage);
      loadItems({
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
      const data = await marketplaceApi.purchaseAgent(item.id);

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

  // Invalid category
  if (!category || !meta) {
    return (
      <div className="h-screen flex items-center justify-center bg-[var(--bg)]">
        <div className="text-center">
          <Package size={48} className="mx-auto mb-4 text-white/20" />
          <p className="text-white/40 mb-4">Category not found</p>
          <button
            onClick={() => navigate('/marketplace')}
            className="px-4 py-2 bg-[var(--primary)] text-white rounded-lg text-sm font-medium"
          >
            Back to Marketplace
          </button>
        </div>
      </div>
    );
  }

  // Generate SEO data
  const baseUrl = typeof window !== 'undefined' ? window.location.origin : 'https://tesslate.com';
  const breadcrumbData = generateBreadcrumbStructuredData([
    { name: 'Marketplace', url: `${baseUrl}/marketplace` },
    { name: meta.label, url: `${baseUrl}/marketplace/category/${category}` },
  ]);

  return (
    <>
      <SEO
        title={`${meta.label} AI Agents & Templates`}
        description={`${meta.description}. Discover the best ${meta.label.toLowerCase()} AI agents and templates on Tesslate Marketplace.`}
        keywords={[meta.label, `${meta.label.toLowerCase()} agents`, 'AI agents', 'coding agents', 'project templates', 'Tesslate']}
        url={`${baseUrl}/marketplace/category/${category}`}
        structuredData={breadcrumbData}
      />
      <div className="h-screen overflow-y-auto bg-[var(--bg)]">
        {/* Header */}
        <div
          className={`border-b ${theme === 'light' ? 'border-black/10 bg-white/80' : 'border-white/10 bg-[#0a0a0a]/80'} backdrop-blur-xl sticky top-0 z-40`}
        >
        <div className="max-w-6xl mx-auto px-6 md:px-12">
          {/* Back Button & Title */}
          <div className="py-6">
            <button
              onClick={() => navigate('/marketplace')}
              className={`
                flex items-center gap-2 mb-4 text-sm transition-colors
                ${theme === 'light' ? 'text-black/60 hover:text-black' : 'text-white/60 hover:text-white'}
              `}
            >
              <ArrowLeft size={16} />
              Back to Marketplace
            </button>

            <div className="flex items-center justify-between">
              <div>
                <h1
                  className={`font-heading text-2xl font-bold ${theme === 'light' ? 'text-black' : 'text-white'}`}
                >
                  {meta.label}
                </h1>
                <p className={`text-sm mt-1 ${theme === 'light' ? 'text-black/60' : 'text-white/60'}`}>
                  {meta.description}
                </p>
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

          {/* Search Bar */}
          <div className="pb-4">
            <div
              className={`
                relative max-w-xl flex items-center gap-3 px-4 py-2.5 rounded-xl border
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
                placeholder="Search in this category... (press / to focus)"
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
          </div>

          {/* Filters Bar */}
          <div className="flex items-center justify-between pb-4 gap-4">
            {/* Left: Dropdowns */}
            <div className="flex items-center gap-2">
              {/* Price Filter */}
              <div className="relative">
                <button
                  onClick={() => setShowPriceDropdown(!showPriceDropdown)}
                  className={`
                    flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all border
                    ${pricingFilter !== 'all' ? 'border-[var(--primary)] text-[var(--primary)]' : ''}
                    ${
                      theme === 'light'
                        ? 'border-black/10 text-black/60 hover:text-black hover:bg-black/5'
                        : 'border-white/10 text-white/60 hover:text-white hover:bg-white/5'
                    }
                  `}
                >
                  {pricingOptions.find((o) => o.id === pricingFilter)?.label}
                  <CaretDown size={14} />
                </button>

                {showPriceDropdown && (
                  <>
                    <div
                      className="fixed inset-0 z-40"
                      onClick={() => setShowPriceDropdown(false)}
                    />
                    <div
                      className={`
                        absolute left-0 top-full mt-2 py-2 rounded-xl border shadow-xl z-50 min-w-[140px]
                        ${
                          theme === 'light'
                            ? 'bg-white border-black/10'
                            : 'bg-[#1a1a1c] border-white/10'
                        }
                      `}
                    >
                      {pricingOptions.map((option) => (
                        <button
                          key={option.id}
                          onClick={() => {
                            setPricingFilter(option.id);
                            setShowPriceDropdown(false);
                          }}
                          className={`
                            w-full px-4 py-2 text-left text-sm transition-colors
                            ${
                              pricingFilter === option.id
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

              {/* Sort Dropdown */}
              <div className="relative">
                <button
                  onClick={() => setShowSortDropdown(!showSortDropdown)}
                  className={`
                    flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all border
                    ${
                      theme === 'light'
                        ? 'border-black/10 text-black/60 hover:text-black hover:bg-black/5'
                        : 'border-white/10 text-white/60 hover:text-white hover:bg-white/5'
                    }
                  `}
                >
                  Sort: {sortOptions.find((o) => o.id === sortBy)?.label}
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
                        absolute left-0 top-full mt-2 py-2 rounded-xl border shadow-xl z-50 min-w-[180px]
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

            {/* Right: Count */}
            {totalCount !== null && (
              <span className={`text-sm ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}>
                {totalCount} {totalCount === 1 ? 'item' : 'items'}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className={`max-w-6xl mx-auto px-6 md:px-12 py-8 ${filtering ? 'opacity-60' : ''} transition-opacity`}>
        {initialLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        ) : items.length > 0 || loadingMore ? (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {items.map((item) => (
                <AgentCard key={item.id} item={item} onInstall={handleInstall} isAuthenticated={isAuthenticated} />
              ))}
              {loadingMore &&
                Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={`loading-${i}`} />)}
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
                ? `No items found matching "${searchQuery}"`
                : `No items available in ${meta.label} yet`}
            </p>
            {(searchQuery || pricingFilter !== 'all') && (
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
      </div>
    </div>
    </>
  );
}
