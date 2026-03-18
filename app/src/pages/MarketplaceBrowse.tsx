import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { debounce } from 'lodash';
import { ArrowLeft, MagnifyingGlass, X, Package, Plus, CaretDown } from '@phosphor-icons/react';
import { AgentCard, SkeletonCard, Pagination, type MarketplaceItem } from '../components/marketplace';
import { SubmitBaseModal } from '../components/modals';
import { marketplaceApi } from '../lib/api';
import toast from 'react-hot-toast';
import { isCanceledError } from '../lib/utils';
import { SEO, generateBreadcrumbStructuredData } from '../components/SEO';
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
  skill: 'Skills',
  mcp_server: 'MCP Servers',
};

export default function MarketplaceBrowse() {
  const navigate = useNavigate();
  const { itemType: itemTypeParam } = useParams<{ itemType: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { isAuthenticated } = useMarketplaceAuth();

  // Validate item type
  const itemType: ItemType = ['agent', 'base', 'theme', 'tool', 'integration', 'skill', 'mcp_server'].includes(
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
          resultTotal = result.total || data.length;
          resultTotalPages = result.total_pages || 1;
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
            : item.item_type === 'skill'
              ? await marketplaceApi.purchaseSkill(item.id)
              : item.item_type === 'mcp_server'
                ? await marketplaceApi.installMcpServer(item.id)
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
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {/* Header — compact toolbar rows */}
        <div className="flex-shrink-0 sticky top-0 z-40 bg-[var(--bg)]">
          {/* Title Row */}
          <div className="h-10 flex items-center gap-3" style={{ paddingLeft: '7px', paddingRight: '10px', borderBottom: 'var(--border-width) solid var(--border)' }}>
            <button onClick={() => navigate('/marketplace')} className="btn btn-sm">
              <ArrowLeft size={14} />
              Marketplace
            </button>
            <span className="text-xs font-semibold text-[var(--text)]">Browse {itemTypeLabels[itemType]}</span>
            {totalCount !== null && (
              <span className="text-[10px] text-[var(--text-subtle)]">{totalCount}</span>
            )}
            <div className="flex-1" />
            <div className="flex items-center gap-[2px]">
              {itemType === 'base' && isAuthenticated && (
                <button onClick={() => setShowSubmitBaseModal(true)} className="btn btn-filled">
                  <Plus size={14} weight="bold" />
                  <span className="hidden sm:inline">Submit Template</span>
                </button>
              )}
              <div className="relative hidden sm:flex items-center">
                <MagnifyingGlass size={14} className="absolute left-3 text-[var(--text-subtle)]" />
                <input
                  ref={searchInputRef}
                  type="text"
                  placeholder="Search..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-48 h-[29px] pl-8 pr-8 bg-[var(--surface)] border border-[var(--border)] rounded-full text-xs text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--border-hover)] transition-colors"
                />
                {searchQuery ? (
                  <button onClick={() => setSearchQuery('')} className="absolute right-2.5 text-[var(--text-subtle)] hover:text-[var(--text)]" aria-label="Clear search">
                    <X size={12} />
                  </button>
                ) : (
                  <kbd className="absolute right-3 text-[10px] font-mono text-[var(--text-subtle)]">/</kbd>
                )}
              </div>
            </div>
          </div>

          {/* Tab Row — scrollable category pills (visible on all sizes) */}
          <div className="h-10 flex items-center overflow-x-auto scrollbar-none" style={{ paddingLeft: '7px', paddingRight: '10px', borderBottom: 'var(--border-width) solid var(--border)', maskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)', WebkitMaskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)' }}>
            {categories.map((cat) => (
              <button
                key={cat.id}
                onClick={() => setSelectedCategory(cat.id)}
                className={`btn shrink-0 mr-1 ${selectedCategory === cat.id ? 'btn-tab-active' : 'btn-tab'}`}
              >
                {cat.label}
              </button>
            ))}
          </div>
        </div>

        {/* Main Content with Sidebar */}
        <div className="px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex flex-col lg:flex-row gap-6">
            {/* Sidebar Filters — price/sort pills on mobile, vertical on desktop */}
            <aside className="lg:w-48 flex-shrink-0 lg:border-r lg:border-[var(--border)] lg:pr-5">
              {/* Mobile/Tablet: Price + Sort pill row */}
              <div className="flex gap-1.5 lg:hidden mb-4 overflow-x-auto scrollbar-none pb-1">
                {/* Price Dropdown */}
                <div className="relative">
                  <button
                    onClick={() => {
                      setShowMobilePriceDropdown(!showMobilePriceDropdown);
                      setShowMobileCategoryDropdown(false);
                      setShowMobileSortDropdown(false);
                    }}
                    className={`btn ${pricingFilter !== 'all' ? 'btn-active' : ''}`}
                  >
                    {pricingOptions.find((o) => o.id === pricingFilter)?.label || 'Price'}
                    <CaretDown size={10} />
                  </button>
                  {showMobilePriceDropdown && (
                    <>
                      <div className="fixed inset-0 z-40" onClick={() => setShowMobilePriceDropdown(false)} />
                      <div className="absolute left-0 top-full mt-1 py-1 rounded-[var(--radius-medium)] border border-[var(--border-hover)] shadow-xl z-50 min-w-[140px] bg-[var(--surface)]">
                        {pricingOptions.map((opt) => (
                          <button
                            key={opt.id}
                            onClick={() => {
                              setPricingFilter(opt.id);
                              setShowMobilePriceDropdown(false);
                            }}
                            className={`
                              w-full px-3 py-1.5 text-left text-xs transition-colors
                              ${pricingFilter === opt.id
                                ? 'bg-[var(--surface-hover)] text-[var(--text)] font-medium'
                                : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
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
                    className="btn"
                  >
                    {sortOptions.find((o) => o.id === sortBy)?.label || 'Sort'}
                    <CaretDown size={10} />
                  </button>
                  {showMobileSortDropdown && (
                    <>
                      <div className="fixed inset-0 z-40" onClick={() => setShowMobileSortDropdown(false)} />
                      <div className="absolute left-0 top-full mt-1 py-1 rounded-[var(--radius-medium)] border border-[var(--border-hover)] shadow-xl z-50 min-w-[180px] bg-[var(--surface)]">
                        {sortOptions.map((opt) => (
                          <button
                            key={opt.id}
                            onClick={() => {
                              setSortBy(opt.id);
                              setShowMobileSortDropdown(false);
                            }}
                            className={`
                              w-full px-3 py-1.5 text-left text-xs transition-colors
                              ${sortBy === opt.id
                                ? 'bg-[var(--surface-hover)] text-[var(--text)] font-medium'
                                : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
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

              {/* Desktop: Sidebar filters (price + sort only, categories in tab row) */}
              <div className="hidden lg:block space-y-6">
                {/* Price Filter */}
                <div>
                  <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-2 text-[var(--text-subtle)]">
                    Price
                  </h3>
                  <div className="space-y-1">
                    {pricingOptions.map((opt) => (
                      <button
                        key={opt.id}
                        onClick={() => setPricingFilter(opt.id)}
                        className={`
                        w-full text-left px-2.5 py-1.5 rounded-[var(--radius-small)] text-xs transition-colors
                        ${
                          pricingFilter === opt.id
                            ? 'bg-[var(--surface-hover)] text-[var(--text)] font-medium'
                            : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
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
                  <h3 className="text-[10px] font-semibold uppercase tracking-wider mb-2 text-[var(--text-subtle)]">
                    Sort By
                  </h3>
                  <div className="space-y-1">
                    {sortOptions.map((opt) => (
                      <button
                        key={opt.id}
                        onClick={() => setSortBy(opt.id)}
                        className={`
                        w-full text-left px-2.5 py-1.5 rounded-[var(--radius-small)] text-xs transition-colors
                        ${
                          sortBy === opt.id
                            ? 'bg-[var(--surface-hover)] text-[var(--text)] font-medium'
                            : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
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
                    className="btn btn-danger w-full"
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
                <div className="text-center py-16 rounded-[var(--radius)] bg-[var(--surface)]">
                  <Package
                    size={48}
                    className="mx-auto mb-4 text-[var(--text-subtle)]"
                  />
                  <p className="text-[var(--text-subtle)]">
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
                      className="btn btn-filled mt-4"
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
