# Marketplace Browse Pages

## Overview

The marketplace browse pages provide advanced filtering, search, and discovery capabilities for marketplace items. There are two main browse pages:

1. **MarketplaceBrowse** (`/marketplace/browse/:itemType`) - Browse all items of a specific type (agents, bases, tools, integrations)
2. **MarketplaceCategory** (`/marketplace/category/:category`) - Browse agents within a specific category (builder, frontend, fullstack, etc.)

Both pages share common patterns for infinite scroll, search debouncing, request cancellation, and SEO integration.

---

## MarketplaceBrowse (`MarketplaceBrowse.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/MarketplaceBrowse.tsx`
**Route**: `/marketplace/browse/:itemType`
**Item Types**: `agent`, `base`, `tool`, `integration`

### Purpose

Browse all marketplace items of a specific type with comprehensive filtering, sorting, and search capabilities. Supports both server-side pagination (agents) and client-side filtering (bases).

### Features

- **Item Type Filtering**: View agents, bases, tools, or integrations
- **Category Filtering**: Filter by category (builder, frontend, fullstack, backend, data, devops, mobile)
- **Price Filtering**: All, Free, or Paid items
- **Sorting**: Popular, Highest Rated, Recently Added, Name A-Z, Price Low-High, Price High-Low
- **Search**: Full-text search with debouncing and "/" keyboard shortcut
- **Infinite Scroll**: Load more items as user scrolls
- **URL State Persistence**: Filters sync to URL query params
- **Responsive Layout**: Sidebar on desktop, horizontal filters on mobile/tablet
- **User Info Dropdown**: Shows credits and subscription tier when authenticated

### State Management

```typescript
// URL Parameters
const { itemType: itemTypeParam } = useParams<{ itemType: string }>();
const [searchParams, setSearchParams] = useSearchParams();

// Filter State
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

// Data State
const [items, setItems] = useState<MarketplaceItem[]>([]);
const [basesCache, setBasesCache] = useState<MarketplaceItem[]>([]); // Client-side cache for bases
const [page, setPage] = useState(1);
const [hasMore, setHasMore] = useState(true);
const [totalCount, setTotalCount] = useState<number | null>(null);

// Loading State
const [initialLoading, setInitialLoading] = useState(true);
const [loadingMore, setLoadingMore] = useState(false);
const [filtering, setFiltering] = useState(false);

// User State (for dropdown)
const [userName, setUserName] = useState<string>('');
const [userCredits, setUserCredits] = useState<number>(0);
const [userTier, setUserTier] = useState<string>('free');
```

### Type Definitions

```typescript
type ItemType = 'agent' | 'base' | 'tool' | 'integration';
type SortOption = 'featured' | 'popular' | 'newest' | 'name' | 'rating' | 'price_asc' | 'price_desc';
type PricingFilter = 'all' | 'free' | 'paid';

const ITEMS_PER_PAGE = 20;

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
```

---

## MarketplaceCategory (`MarketplaceCategory.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/MarketplaceCategory.tsx`
**Route**: `/marketplace/category/:category`
**Categories**: `builder`, `frontend`, `fullstack`, `backend`, `data`, `devops`, `mobile`

### Purpose

Focused browsing of agents within a specific category. Simpler UI than MarketplaceBrowse since category is fixed.

### Features

- **Category-Specific**: Title and description from category metadata
- **Price Filtering**: Dropdown for All/Free/Paid
- **Sorting**: Dropdown for sort options
- **Search**: Full-text search within category
- **Infinite Scroll**: Load more items as user scrolls
- **User Info Dropdown**: Shows credits and subscription tier when authenticated

### Category Metadata

```typescript
const categoryMeta: Record<string, { label: string; description: string }> = {
  builder: { label: 'Builder', description: 'General-purpose AI coding assistants for any project' },
  frontend: { label: 'Frontend', description: 'Build beautiful user interfaces with modern frameworks' },
  fullstack: { label: 'Fullstack', description: 'End-to-end web application development' },
  backend: { label: 'Backend', description: 'APIs, databases, and server-side logic' },
  data: { label: 'Data', description: 'Data analysis, visualization, and machine learning' },
  devops: { label: 'DevOps', description: 'CI/CD, infrastructure, and deployment automation' },
  mobile: { label: 'Mobile', description: 'iOS, Android, and cross-platform mobile apps' },
};
```

### State Management

```typescript
const { category } = useParams<{ category: string }>();
const meta = category ? categoryMeta[category] : null;

// Filter State
const [searchQuery, setSearchQuery] = useState('');
const [sortBy, setSortBy] = useState<SortOption>('popular');
const [pricingFilter, setPricingFilter] = useState<PricingFilter>('all');
const [showSortDropdown, setShowSortDropdown] = useState(false);
const [showPriceDropdown, setShowPriceDropdown] = useState(false);

// Data State
const [items, setItems] = useState<MarketplaceItem[]>([]);
const [page, setPage] = useState(1);
const [hasMore, setHasMore] = useState(true);
const [totalCount, setTotalCount] = useState<number | null>(null);
```

---

## Filtering Strategy

### Server-Side Filtering (Agents)

Agents use server-side filtering via the `getAllAgents` API endpoint. This is efficient for large datasets:

```typescript
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
```

**API Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `category` | string | Filter by category (optional) |
| `pricing_type` | 'free' \| 'paid' | Filter by pricing (optional) |
| `search` | string | Full-text search query (optional) |
| `sort` | string | Sort order (popular, newest, name, rating, price_asc, price_desc) |
| `page` | number | Page number (1-indexed) |
| `limit` | number | Items per page (default 20) |

### Client-Side Filtering (Bases)

Bases are loaded once and filtered client-side. This is suitable for smaller datasets:

```typescript
// Cache all bases on first load
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
```

**Client-Side Filter Function**:

```typescript
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

  // Search filter (name, description, tags)
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

  // Sorting
  switch (filters.sort) {
    case 'popular':
      filtered.sort((a, b) => (b.downloads || b.usage_count || 0) - (a.downloads || a.usage_count || 0));
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
```

---

## Infinite Scroll Implementation

Both pages use `react-intersection-observer` for infinite scroll:

```typescript
import { useInView } from 'react-intersection-observer';

// Setup intersection observer
const { ref: loadMoreRef, inView } = useInView({
  threshold: 0,
  rootMargin: '100px', // Start loading 100px before reaching the element
});

// Trigger load when element comes into view
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
      append: true, // Append to existing items
    });
  }
}, [inView, hasMore, loadingMore, initialLoading, filtering]);

// Render trigger element at the bottom
{hasMore && !loadingMore && <div ref={loadMoreRef} className="h-10 mt-4" />}
```

**Key Implementation Details**:
- `threshold: 0` - Trigger as soon as element enters viewport
- `rootMargin: '100px'` - Start loading 100px before element is visible (preloading)
- Guard conditions prevent multiple simultaneous requests
- `hasMore` tracks if there are more items to load (based on whether last response returned `ITEMS_PER_PAGE` items)

---

## Search Functionality

### Debouncing

Search input uses `lodash.debounce` to prevent excessive API calls:

```typescript
import { debounce } from 'lodash';

// Create memoized debounced function
const debouncedLoadItems = useMemo(
  () =>
    debounce(
      (params: { category: string; search: string; sort: SortOption; pricing: PricingFilter }) => {
        setPage(1);
        loadItems({ ...params, pageNum: 1 });
      },
      300 // 300ms debounce delay
    ),
  [loadItems]
);

// Cleanup debounced function on unmount
useEffect(() => {
  return () => {
    debouncedLoadItems.cancel();
    abortControllerRef.current?.abort();
  };
}, [debouncedLoadItems]);

// Handle filter changes
useEffect(() => {
  if (initialLoading) return;

  if (searchQuery) {
    // Use debounced version for search
    debouncedLoadItems({
      category: selectedCategory,
      search: searchQuery,
      sort: sortBy,
      pricing: pricingFilter,
    });
  } else {
    // Cancel debounce and load immediately for non-search changes
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
}, [selectedCategory, searchQuery, sortBy, pricingFilter]);
```

### "/" Key Focus Shortcut

Both pages implement a keyboard shortcut to focus the search input:

```typescript
const searchInputRef = useRef<HTMLInputElement>(null);

// "/" keyboard shortcut to focus search (like GitHub, Slack, etc.)
useEffect(() => {
  const handleSlashKey = (e: KeyboardEvent) => {
    // Ignore if user is already typing in an input
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
```

**Search Input with Clear Button**:

```tsx
<input
  ref={searchInputRef}
  type="text"
  placeholder="Search... (press /)"
  value={searchQuery}
  onChange={(e) => setSearchQuery(e.target.value)}
  className="flex-1 bg-transparent outline-none text-sm"
/>
{searchQuery && (
  <button
    onClick={() => setSearchQuery('')}
    aria-label="Clear search"
  >
    <X size={14} />
  </button>
)}
```

---

## AbortController for Request Cancellation

Both pages use `AbortController` to cancel in-flight requests when new requests are made:

```typescript
import { isCanceledError } from '../lib/utils';

const abortControllerRef = useRef<AbortController | null>(null);

const loadItems = useCallback(async (params) => {
  // Cancel any in-flight request
  abortControllerRef.current?.abort();
  abortControllerRef.current = new AbortController();

  try {
    const result = await marketplaceApi.getAllAgents(
      { /* params */ },
      { signal: abortControllerRef.current.signal } // Pass signal to fetch
    );
    // Process result...
  } catch (err) {
    // Silently ignore cancelled requests (both native AbortError and Axios CanceledError)
    if (isCanceledError(err)) {
      return;
    }
    console.error('Failed to load:', err);
    toast.error('Failed to load items');
  }
}, [/* dependencies */]);

// Cleanup on unmount
useEffect(() => {
  return () => {
    abortControllerRef.current?.abort();
  };
}, []);
```

**Important**: Always use `isCanceledError()` instead of `err.name === 'AbortError'`:
- Native fetch throws `AbortError` with `name: 'AbortError'`
- Axios throws `CanceledError` with `code: 'ERR_CANCELED'`
- `isCanceledError()` handles both cases

**Why This Matters**:
- Prevents race conditions when filters change rapidly
- Saves bandwidth by not completing outdated requests
- Prevents stale data from overwriting newer results
- Required for proper cleanup on component unmount

---

## SEO Integration

Both pages include SEO meta tags and structured data:

```typescript
import { SEO, generateBreadcrumbStructuredData } from '../components/SEO';

// Generate breadcrumb structured data
const baseUrl = typeof window !== 'undefined' ? window.location.origin : 'https://tesslate.com';
const itemTypeLabel = itemTypeLabels[itemType]; // e.g., "Agents"
const breadcrumbData = generateBreadcrumbStructuredData([
  { name: 'Marketplace', url: `${baseUrl}/marketplace` },
  { name: itemTypeLabel, url: `${baseUrl}/marketplace/browse/${itemType}` },
]);

// Render SEO component
<SEO
  title={`Browse All ${itemTypeLabel} - Tesslate Marketplace`}
  description={`Discover and browse all ${itemTypeLabel.toLowerCase()} available on Tesslate Marketplace. Filter by category, price, and more to find the perfect AI-powered tools for your projects.`}
  keywords={[itemTypeLabel, 'AI agents', 'coding agents', 'project templates', 'developer tools', 'Tesslate', 'browse marketplace']}
  url={`${baseUrl}/marketplace/browse/${itemType}`}
  structuredData={breadcrumbData}
/>
```

**MarketplaceCategory SEO**:

```typescript
const breadcrumbData = generateBreadcrumbStructuredData([
  { name: 'Marketplace', url: `${baseUrl}/marketplace` },
  { name: meta.label, url: `${baseUrl}/marketplace/category/${category}` },
]);

<SEO
  title={`${meta.label} AI Agents & Templates`}
  description={`${meta.description}. Discover the best ${meta.label.toLowerCase()} AI agents and templates on Tesslate Marketplace.`}
  keywords={[meta.label, `${meta.label.toLowerCase()} agents`, 'AI agents', 'coding agents', 'project templates', 'Tesslate']}
  url={`${baseUrl}/marketplace/category/${category}`}
  structuredData={breadcrumbData}
/>
```

---

## User Info Dropdown

When authenticated, both pages show a user dropdown with credits and tier:

```typescript
import { UserDropdown } from '../components/ui';
import { useMarketplaceAuth } from '../contexts/MarketplaceAuthContext';

const { isAuthenticated } = useMarketplaceAuth();
const [userName, setUserName] = useState<string>('');
const [userCredits, setUserCredits] = useState<number>(0);
const [userTier, setUserTier] = useState<string>('free');

// Fetch user data when authenticated
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

// Render dropdown only when authenticated
{isAuthenticated && (
  <UserDropdown
    userName={userName}
    userCredits={userCredits}
    userTier={userTier}
  />
)}
```

---

## Key Patterns and Code Examples

### Loading States

Three distinct loading states provide better UX:

```typescript
// Initial page load
const [initialLoading, setInitialLoading] = useState(true);

// Loading more items (infinite scroll)
const [loadingMore, setLoadingMore] = useState(false);

// Filtering (show dimmed content)
const [filtering, setFiltering] = useState(false);

// Set appropriate loading state based on action
if (pageNum === 1 && !append) {
  if (initialLoading) {
    // Keep initial loading
  } else {
    setFiltering(true); // Show dimmed content while filtering
  }
} else {
  setLoadingMore(true); // Show loading skeletons at bottom
}
```

**Rendering Based on State**:

```tsx
// Initial loading: full skeleton grid
{initialLoading ? (
  <div className="grid grid-cols-3 gap-4">
    {Array.from({ length: 9 }).map((_, i) => <SkeletonCard key={i} />)}
  </div>
) : items.length > 0 || loadingMore ? (
  <>
    {/* Dim content while filtering */}
    <div className={`${filtering ? 'opacity-60' : ''} transition-opacity`}>
      {items.map((item) => <AgentCard key={item.id} item={item} />)}
      {/* Loading more: skeleton cards at bottom */}
      {loadingMore && Array.from({ length: 3 }).map((_, i) => <SkeletonCard key={`loading-${i}`} />)}
    </div>
  </>
) : (
  <EmptyState />
)}
```

### URL State Synchronization

MarketplaceBrowse syncs filters to URL for shareable links:

```typescript
// Update URL params when filters change
useEffect(() => {
  if (initialLoading) return;

  const params = new URLSearchParams();
  if (selectedCategory !== 'all') params.set('category', selectedCategory);
  if (searchQuery) params.set('search', searchQuery);
  if (sortBy !== 'popular') params.set('sort', sortBy);
  if (pricingFilter !== 'all') params.set('pricing', pricingFilter);

  setSearchParams(params, { replace: true }); // Replace to avoid history pollution
}, [selectedCategory, searchQuery, sortBy, pricingFilter]);
```

**Example URLs**:
- `/marketplace/browse/agent?category=frontend&search=react&sort=popular`
- `/marketplace/browse/base?pricing=free&sort=newest`

### Purchase Flow

```typescript
const handleInstall = async (item: MarketplaceItem) => {
  // Already purchased
  if (item.is_purchased) {
    toast.success(`${item.name} already in your library`);
    return;
  }

  // Item not active
  if (!item.is_active) {
    return;
  }

  try {
    const data =
      item.item_type === 'base'
        ? await marketplaceApi.purchaseBase(item.id)
        : await marketplaceApi.purchaseAgent(item.id);

    if (data.checkout_url) {
      // Paid item: redirect to Stripe checkout
      window.location.href = data.checkout_url;
    } else {
      // Free item: added directly
      toast.success(`${item.name} added to your library!`);
      // Update local state to reflect purchase
      setItems((prev) => prev.map((i) =>
        i.id === item.id ? { ...i, is_purchased: true } : i
      ));
    }
  } catch (error) {
    console.error('Failed to install:', error);
    toast.error('Failed to add to library');
  }
};
```

### Responsive Layout

MarketplaceBrowse uses different layouts for different screen sizes:

```tsx
{/* Mobile/Tablet: Horizontal filter row */}
<div className="flex flex-wrap gap-2 lg:hidden mb-4">
  <select value={selectedCategory} onChange={(e) => setSelectedCategory(e.target.value)}>
    {categories.map((cat) => <option key={cat.id} value={cat.id}>{cat.label}</option>)}
  </select>
  {/* Price and Sort selects... */}
</div>

{/* Desktop: Sidebar filters */}
<div className="hidden lg:block space-y-6">
  {/* Categories */}
  <div>
    <h3>Category</h3>
    {categories.map((cat) => (
      <button
        key={cat.id}
        onClick={() => setSelectedCategory(cat.id)}
        className={selectedCategory === cat.id ? 'active' : ''}
      >
        {cat.label}
      </button>
    ))}
  </div>
  {/* Price Filter, Sort, Clear Filters... */}
</div>
```

---

## API Endpoints

### Get All Agents

```typescript
GET /api/marketplace/agents?category={category}&pricing_type={pricing}&search={search}&sort={sort}&page={page}&limit={limit}

// Response
{
  "agents": [
    {
      "id": "uuid",
      "name": "Agent Name",
      "description": "Agent description",
      "slug": "agent-slug",
      "category": "fullstack",
      "pricing_type": "free" | "paid",
      "price": 0,
      "downloads": 1234,
      "rating": 4.5,
      "is_featured": false,
      "is_active": true,
      "is_purchased": false,
      "avatar_url": "...",
      "tags": ["react", "typescript"],
      "author": { "id": "...", "name": "..." }
    }
  ],
  "total": 100
}
```

### Get All Bases

```typescript
GET /api/marketplace/bases?category={category}&pricing_type={pricing}&search={search}&sort={sort}&page={page}&limit={limit}

// Response
{
  "bases": [
    {
      "id": 1,
      "name": "Base Name",
      "description": "Base description",
      "slug": "base-slug",
      "category": "frontend",
      "pricing_type": "free",
      "price": 0,
      "downloads": 567,
      "rating": 4.2,
      "is_active": true,
      "is_purchased": false,
      "avatar_url": "...",
      "tags": ["next.js", "tailwind"]
    }
  ]
}
```

---

## Troubleshooting

### Issue: Search not working

**Solution**: Check debounce timing and AbortController:
```typescript
import { isCanceledError } from '../lib/utils';

// Ensure debounce is not cancelled prematurely
// Check that cancelled requests are being handled correctly
if (isCanceledError(err)) {
  return; // Don't show error for cancelled requests
}
```

### Issue: Infinite scroll loading multiple times

**Solution**: Add proper guard conditions:
```typescript
if (inView && hasMore && !loadingMore && !initialLoading && !filtering) {
  // Only load if all conditions are met
}
```

### Issue: Filters not persisting on refresh

**Solution**: Ensure URL params are being read on mount:
```typescript
const [selectedCategory, setSelectedCategory] = useState<string>(
  searchParams.get('category') || 'all' // Read from URL params
);
```

### Issue: Items not updating after purchase

**Solution**: Update local state after successful purchase:
```typescript
setItems((prev) => prev.map((i) =>
  i.id === item.id ? { ...i, is_purchased: true } : i
));
```

---

## Related Documentation

- **Main Marketplace Page**: `c:/Users/Smirk/Downloads/Tesslate-Studio/docs/app/pages/marketplace.md`
- **SEO Component**: `c:/Users/Smirk/Downloads/Tesslate-Studio/docs/app/seo/CLAUDE.md`
- **Marketplace API**: `c:/Users/Smirk/Downloads/Tesslate-Studio/docs/orchestrator/routers/marketplace.md`
- **AgentCard Component**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/marketplace/AgentCard.tsx`
- **SkeletonCard Component**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/marketplace/SkeletonCard.tsx`
