import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { debounce } from 'lodash';
import { ArrowLeft, MagnifyingGlass, X, Package, Plus, CaretDown } from '@phosphor-icons/react';
import { AgentCard, SkeletonCard, Pagination, type MarketplaceItem } from '../components/marketplace';
import { UserDropdown } from '../components/ui';
import { SubmitBaseModal } from '../components/modals';
import { marketplaceApi } from '../lib/api';
import toast from 'react-hot-toast';
import { isCanceledError } from '../lib/utils';
import { useTheme } from '../theme/ThemeContext';
import { SEO, generateBreadcrumbStructuredData } from '../components/SEO';
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

// Category definitions
const categories = [
  { id: 'all', label: 'All Categories' },
  { id: 'community', label: 'Community' },
  { id: 'builder', label: 'Builder' },
  { id: 'frontend', label: 'Frontend' },
  { id: 'fullstack', label: 'Fullstack' },
  { id: 'backend', label: 'Backend' },
  { id: 'mobile', label: 'Mobile' },
  { id: 'saas', label: 'SaaS' },
  { id: 'ai', label: 'AI / ML' },
  { id: 'admin', label: 'Admin' },
  { id: 'landing', label: 'Landing Page' },
  { id: 'cli', label: 'CLI' },
  { id: 'data', label: 'Data' },
  { id: 'devops', label: 'DevOps' },
];

const itemTypeLabels: Record<ItemType, string> = {
  agent: 'Agents',
  base: 'Bases',
  theme: 'Themes',
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
  const itemType: ItemType = ['agent', 'base', 'theme', 'tool', 'integration'].includes(
    itemTypeParam || ''
  )
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
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalCount, setTotalCount] = useState<number | null>(null);

  // State - Loading
  const [initialLoading, setInitialLoading] = useState(true);
  const [filtering, setFiltering] = useState(false);

  // State - Submit base modal
  const [showSubmitBaseModal, setShowSubmitBaseModal] = useState(false);

  // State - Mobile filter dropdowns
  const [showMobileCategoryDropdown, setShowMobileCategoryDropdown] = useState(false);
  const [showMobilePriceDropdown, setShowMobilePriceDropdown] = useState(false);
  const [showMobileSortDropdown, setShowMobileSortDropdown] = useState(false);

  // "/" keyboard shortcut to focus search
  useEffect(() => {
    const handleSlashKey = (e: KeyboardEvent) => {
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

  // Load items with server-side filtering and pagination
  const loadItems = useCallback(
    async (params: {
      category: string;
      search: string;
      sort: SortOption;
      pricing: PricingFilter;
      pageNum: number;
    }) => {
      const { category, search, sort, pricing, pageNum } = params;

      // Cancel any in-flight request
      abortControllerRef.current?.abort();
      abortControllerRef.current = new AbortController();

      // Set appropriate loading state
      if (pageNum === 1) {
        if (!initialLoading) {
          setFiltering(true);
        }
      } else {
        setFiltering(true);
      }

      try {
        let data: MarketplaceItem[];
        let resultTotal = 0;
        let resultTotalPages = 1;

        if (itemType === 'agent') {
          // "community" is a creator_type filter, not a database category
          const isCommunityFilter = category === 'community';
          const result = await marketplaceApi.getAllAgents(
            {
              category: category !== 'all' && !isCommunityFilter ? category : undefined,
              pricing_type: pricing !== 'all' ? pricing : undefined,
              search: search || undefined,
              sort,
              page: pageNum,
              limit: isCommunityFilter ? 100 : ITEMS_PER_PAGE,
            },
            { signal: abortControllerRef.current.signal }
          );
          data = (result.agents || []).map((agent: Record<string, unknown>) => ({
            ...agent,
            item_type: 'agent' as ItemType,
          }));

          // Client-side filter for community agents
          if (isCommunityFilter) {
            data = data.filter((item) => item.creator_type === 'community');
            resultTotal = data.length;
            resultTotalPages = 1;
          } else {
            resultTotal = result.total || data.length;
            resultTotalPages = result.total_pages || 1;
          }
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
          resultTotal = result.total || data.length;
          resultTotalPages = result.total_pages || 1;
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
          resultTotal = result.total || data.length;
          resultTotalPages = result.total_pages || 1;
        } else {
          data = [];
        }

        setItems(data);
        setTotalCount(resultTotal);
        setTotalPages(resultTotalPages);
      } catch (err) {
        // Silently ignore cancelled requests (both native AbortError and Axios CanceledError)
        if (isCanceledError(err)) {
          return;
        }
        console.error('Failed to load:', err);
        toast.error('Failed to load items');
      } finally {
        setInitialLoading(false);
        setFiltering(false);
      }
    },
    [itemType, initialLoading]
  );

  // Debounced search
  const debouncedLoadItems = useMemo(
    () =>
      debounce(
        (params: {
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

  // Handle page change from Pagination component
  const handlePageChange = useCallback(
    (newPage: number) => {
      setPage(newPage);
      loadItems({
        category: selectedCategory,
        search: searchQuery,
        sort: sortBy,
        pricing: pricingFilter,
        pageNum: newPage,
      });
      // Scroll to top of results
      window.scrollTo({ top: 0, behavior: 'smooth' });
    },
    [selectedCategory, searchQuery, sortBy, pricingFilter, loadItems]
  );

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
        keywords={[
          itemTypeLabel,
          'AI agents',
          'coding agents',
          'project templates',
          'developer tools',
          'Tesslate',
          'browse marketplace',
        ]}
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
                    <p
                      className={`text-sm mt-1 ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}
                    >
                      {totalCount} {totalCount === 1 ? 'result' : 'results'}
                    </p>
                  )}
                </div>

                <div className="flex items-center gap-3">
                  {/* Submit Template Button - Only for bases tab when authenticated */}
                  {itemType === 'base' && isAuthenticated && (
                    <button
                      onClick={() => setShowSubmitBaseModal(true)}
                      className="flex items-center gap-2 px-4 py-2.5 bg-[var(--primary)] text-white rounded-xl text-sm font-medium hover:opacity-90 transition-all whitespace-nowrap"
                    >
                      <Plus size={16} weight="bold" />
                      Submit Template
                    </button>
                  )}

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
                  {isAuthenticated && <UserDropdown />}
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
              {/* Mobile/Tablet: Styled pill-button dropdowns */}
              <div className="flex flex-wrap gap-2 lg:hidden mb-4">
                {/* Category Dropdown */}
                <div className="relative">
                  <button
                    onClick={() => {
                      setShowMobileCategoryDropdown(!showMobileCategoryDropdown);
                      setShowMobilePriceDropdown(false);
                      setShowMobileSortDropdown(false);
                    }}
                    className={`
                      flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm border transition-colors
                      ${selectedCategory !== 'all'
                        ? 'bg-[var(--primary)]/10 border-[var(--primary)]/30 text-[var(--primary)]'
                        : theme === 'light'
                          ? 'bg-white border-black/10 text-black/70 hover:border-black/20'
                          : 'bg-white/5 border-white/10 text-white/70 hover:border-white/20'
                      }
                    `}
                  >
                    {categories.find((c) => c.id === selectedCategory)?.label || 'Category'}
                    <CaretDown size={12} />
                  </button>
                  {showMobileCategoryDropdown && (
                    <>
                      <div className="fixed inset-0 z-40" onClick={() => setShowMobileCategoryDropdown(false)} />
                      <div
                        className={`
                          absolute left-0 top-full mt-1 py-1 rounded-xl border shadow-xl z-50 min-w-[180px] max-h-64 overflow-y-auto
                          ${theme === 'light' ? 'bg-white border-black/10' : 'bg-[#1a1a1c] border-white/10'}
                        `}
                      >
                        {categories.map((cat) => (
                          <button
                            key={cat.id}
                            onClick={() => {
                              setSelectedCategory(cat.id);
                              setShowMobileCategoryDropdown(false);
                            }}
                            className={`
                              w-full px-3 py-2 text-left text-sm transition-colors
                              ${selectedCategory === cat.id
                                ? 'text-[var(--primary)] font-medium'
                                : theme === 'light'
                                  ? 'text-black/70 hover:bg-black/5'
                                  : 'text-white/70 hover:bg-white/5'
                              }
                            `}
                          >
                            {cat.label}
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </div>

                {/* Price Dropdown */}
                <div className="relative">
                  <button
                    onClick={() => {
                      setShowMobilePriceDropdown(!showMobilePriceDropdown);
                      setShowMobileCategoryDropdown(false);
                      setShowMobileSortDropdown(false);
                    }}
                    className={`
                      flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm border transition-colors
                      ${pricingFilter !== 'all'
                        ? 'bg-[var(--primary)]/10 border-[var(--primary)]/30 text-[var(--primary)]'
                        : theme === 'light'
                          ? 'bg-white border-black/10 text-black/70 hover:border-black/20'
                          : 'bg-white/5 border-white/10 text-white/70 hover:border-white/20'
                      }
                    `}
                  >
                    {pricingOptions.find((o) => o.id === pricingFilter)?.label || 'Price'}
                    <CaretDown size={12} />
                  </button>
                  {showMobilePriceDropdown && (
                    <>
                      <div className="fixed inset-0 z-40" onClick={() => setShowMobilePriceDropdown(false)} />
                      <div
                        className={`
                          absolute left-0 top-full mt-1 py-1 rounded-xl border shadow-xl z-50 min-w-[140px]
                          ${theme === 'light' ? 'bg-white border-black/10' : 'bg-[#1a1a1c] border-white/10'}
                        `}
                      >
                        {pricingOptions.map((opt) => (
                          <button
                            key={opt.id}
                            onClick={() => {
                              setPricingFilter(opt.id);
                              setShowMobilePriceDropdown(false);
                            }}
                            className={`
                              w-full px-3 py-2 text-left text-sm transition-colors
                              ${pricingFilter === opt.id
                                ? 'text-[var(--primary)] font-medium'
                                : theme === 'light'
                                  ? 'text-black/70 hover:bg-black/5'
                                  : 'text-white/70 hover:bg-white/5'
                              }
                            `}
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </div>

                {/* Sort Dropdown */}
                <div className="relative">
                  <button
                    onClick={() => {
                      setShowMobileSortDropdown(!showMobileSortDropdown);
                      setShowMobileCategoryDropdown(false);
                      setShowMobilePriceDropdown(false);
                    }}
                    className={`
                      flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm border transition-colors
                      ${theme === 'light'
                        ? 'bg-white border-black/10 text-black/70 hover:border-black/20'
                        : 'bg-white/5 border-white/10 text-white/70 hover:border-white/20'
                      }
                    `}
                  >
                    {sortOptions.find((o) => o.id === sortBy)?.label || 'Sort'}
                    <CaretDown size={12} />
                  </button>
                  {showMobileSortDropdown && (
                    <>
                      <div className="fixed inset-0 z-40" onClick={() => setShowMobileSortDropdown(false)} />
                      <div
                        className={`
                          absolute left-0 top-full mt-1 py-1 rounded-xl border shadow-xl z-50 min-w-[180px]
                          ${theme === 'light' ? 'bg-white border-black/10' : 'bg-[#1a1a1c] border-white/10'}
                        `}
                      >
                        {sortOptions.map((opt) => (
                          <button
                            key={opt.id}
                            onClick={() => {
                              setSortBy(opt.id);
                              setShowMobileSortDropdown(false);
                            }}
                            className={`
                              w-full px-3 py-2 text-left text-sm transition-colors
                              ${sortBy === opt.id
                                ? 'text-[var(--primary)] font-medium'
                                : theme === 'light'
                                  ? 'text-black/70 hover:bg-black/5'
                                  : 'text-white/70 hover:bg-white/5'
                              }
                            `}
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </div>
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
            <main className="flex-1">
              {initialLoading ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
                  {Array.from({ length: 9 }).map((_, i) => (
                    <SkeletonCard key={i} />
                  ))}
                </div>
              ) : items.length > 0 ? (
                <>
                  <div className={`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5 ${filtering ? 'opacity-60' : ''} transition-opacity`}>
                    {items.map((item) => (
                      <AgentCard
                        key={item.id}
                        item={item}
                        onInstall={handleInstall}
                        isAuthenticated={isAuthenticated}
                      />
                    ))}
                  </div>

                  <Pagination
                    currentPage={page}
                    totalPages={totalPages}
                    onPageChange={handlePageChange}
                  />
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

      {/* Submit Base Modal */}
      <SubmitBaseModal
        isOpen={showSubmitBaseModal}
        onClose={() => setShowSubmitBaseModal(false)}
        onSuccess={() => {
          setShowSubmitBaseModal(false);
          // Refresh the bases list
          setPage(1);
          loadItems({
            category: selectedCategory,
            search: searchQuery,
            sort: sortBy,
            pricing: pricingFilter,
            pageNum: 1,
          });
        }}
      />
    </>
  );
}
