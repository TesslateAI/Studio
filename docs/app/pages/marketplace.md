# Marketplace Pages

## Marketplace Browse (`Marketplace.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/Marketplace.tsx`
**Route**: `/marketplace`
**Layout**: DashboardLayout

### Purpose
Browse and discover AI agents, project bases, tools, and integrations available for purchase or free use.

### Features
- **Filter by Type**: Agents, Bases, Tools, Integrations
- **Search**: Name, description, tags
- **Sort**: Featured, Popular, Newest, Name A-Z
- **Featured Carousel**: Highlighted items
- **Purchase Flow**: One-click install/purchase

### State
```typescript
const [items, setItems] = useState<MarketplaceItem[]>([]);
const [filteredItems, setFilteredItems] = useState<MarketplaceItem[]>([]);
const [selectedItemType, setSelectedItemType] = useState<'agent' | 'base' | 'tool' | 'integration'>('agent');
const [searchQuery, setSearchQuery] = useState('');
const [sortBy, setSortBy] = useState<'featured' | 'popular' | 'newest' | 'name'>('featured');
```

### Data Flow
```typescript
// Load all items
const [agentsData, basesData] = await Promise.all([
  marketplaceApi.getAllAgents(),
  marketplaceApi.getAllBases()
]);

// Filter and sort
let filtered = items.filter(item => item.item_type === selectedItemType);

if (searchQuery) {
  filtered = filtered.filter(item =>
    item.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    item.description.toLowerCase().includes(searchQuery.toLowerCase())
  );
}

switch (sortBy) {
  case 'featured':
    filtered.sort((a, b) => (b.is_featured ? 1 : 0) - (a.is_featured ? 1 : 0));
    break;
  case 'popular':
    filtered.sort((a, b) => (b.downloads || 0) - (a.downloads || 0));
    break;
  // ... other sorts
}
```

### Purchase Flow
```typescript
const handleInstall = async (item: MarketplaceItem) => {
  if (item.is_purchased) {
    toast.success(`${item.name} already in your library`);
    return;
  }

  if (item.pricing_type === 'free') {
    // Free item - instant add
    await marketplaceApi.purchaseAgent(item.slug);
    toast.success('Added to your library');
  } else if (item.pricing_type === 'credits') {
    // Check credit balance
    const user = await authApi.getCurrentUser();
    if (user.credits_balance < item.price) {
      toast.error('Insufficient credits');
      navigate('/billing/plans');
      return;
    }

    // Purchase with credits
    await marketplaceApi.purchaseAgent(item.slug);
    toast.success(`Purchased with ${item.price} credits`);
  } else {
    // Paid item - redirect to detail page
    navigate(`/marketplace/${item.slug}`);
  }
};
```

---

## Marketplace Detail (`MarketplaceDetail.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/MarketplaceDetail.tsx`
**Route**: `/marketplace/:slug`
**Layout**: DashboardLayout

### Purpose
Detailed view of a marketplace item with description, features, reviews, and purchase button.

### Features
- **Full Description**: Markdown support
- **Feature List**: Bullet points
- **Screenshots**: Image gallery
- **Pricing**: Free, credits, or subscription
- **Reviews**: Star ratings and comments
- **Creator Info**: Link to creator profile
- **Related Items**: Suggestions

### State
```typescript
const [item, setItem] = useState<MarketplaceItem | null>(null);
const [reviews, setReviews] = useState<Review[]>([]);
const [userReview, setUserReview] = useState<Review | null>(null);
const [showReviewModal, setShowReviewModal] = useState(false);
```

### Data Flow
```typescript
const { slug } = useParams<{ slug: string }>();

useEffect(() => {
  loadItem();
  loadReviews();
}, [slug]);

const loadItem = async () => {
  const data = await marketplaceApi.getAgentBySlug(slug);
  setItem(data);
};

const loadReviews = async () => {
  const data = await marketplaceApi.getReviews(slug);
  setReviews(data.reviews);
  setUserReview(data.user_review); // User's own review if exists
};
```

### Purchase Button
```typescript
<AgentPurchaseButton
  item={item}
  onPurchaseComplete={() => {
    toast.success('Added to your library!');
    navigate('/library');
  }}
/>
```

### Review System
```typescript
const handleSubmitReview = async (rating: number, comment: string) => {
  try {
    await marketplaceApi.createReview(slug, { rating, comment });
    toast.success('Review submitted');
    loadReviews();
  } catch (error) {
    toast.error('Failed to submit review');
  }
};

const handleUpdateReview = async (reviewId: string, rating: number, comment: string) => {
  try {
    await marketplaceApi.updateReview(reviewId, { rating, comment });
    toast.success('Review updated');
    loadReviews();
  } catch (error) {
    toast.error('Failed to update review');
  }
};
```

---

## Marketplace Author (`MarketplaceAuthor.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/MarketplaceAuthor.tsx`
**Route**: `/marketplace/creator/:userId`
**Layout**: DashboardLayout

### Purpose
Creator profile showing all items published by a specific user.

### Features
- **Creator Bio**: Name, avatar, description
- **Published Items**: All agents/bases by creator
- **Stats**: Total downloads, average rating
- **Follow Button**: (Future feature)

### State
```typescript
const [creator, setCreator] = useState<User | null>(null);
const [items, setItems] = useState<MarketplaceItem[]>([]);
```

### Data Flow
```typescript
const { userId } = useParams<{ userId: string }>();

useEffect(() => {
  loadCreator();
  loadItems();
}, [userId]);

const loadCreator = async () => {
  const data = await usersApi.getPublicProfile(userId);
  setCreator(data);
};

const loadItems = async () => {
  const data = await marketplaceApi.getItemsByCreator(userId);
  setItems(data);
};
```

---

## Marketplace Success (`MarketplaceSuccess.tsx`)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/MarketplaceSuccess.tsx`
**Route**: `/marketplace/success`
**Layout**: DashboardLayout

### Purpose
Confirmation page after successful purchase, redirected from Stripe checkout.

### Features
- **Success Message**: "Purchase successful!"
- **Item Details**: What was purchased
- **Next Steps**: "View in Library" button

### State
```typescript
const [searchParams] = useSearchParams();
const itemSlug = searchParams.get('item');
const [item, setItem] = useState<MarketplaceItem | null>(null);
```

### Data Flow
```typescript
useEffect(() => {
  if (itemSlug) {
    loadItem(itemSlug);
  }
}, [itemSlug]);

const loadItem = async (slug: string) => {
  const data = await marketplaceApi.getAgentBySlug(slug);
  setItem(data);
};
```

---

## Shared Components

### AgentCard
```typescript
interface AgentCardProps {
  agent: MarketplaceItem;
  onClick: (slug: string) => void;
  onInstall?: (agent: MarketplaceItem) => void;
}

export function AgentCard({ agent, onClick, onInstall }: AgentCardProps) {
  return (
    <div className="agent-card" onClick={() => onClick(agent.slug)}>
      <div className="card-header">
        <img src={agent.avatar_url || agent.icon} alt={agent.name} />
        <h3>{agent.name}</h3>
      </div>

      <p className="description">{agent.description}</p>

      <div className="tags">
        {agent.tags?.map(tag => (
          <span key={tag} className="tag">{tag}</span>
        ))}
      </div>

      <div className="card-footer">
        <div className="stats">
          <span>{agent.downloads || 0} downloads</span>
          <span>★ {agent.average_rating || 0}</span>
        </div>

        <div className="pricing">
          {agent.pricing_type === 'free' ? (
            <span className="free">Free</span>
          ) : (
            <span className="price">{agent.price} credits</span>
          )}
        </div>
      </div>

      {onInstall && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onInstall(agent);
          }}
        >
          {agent.is_purchased ? 'Installed' : 'Install'}
        </button>
      )}
    </div>
  );
}
```

### FeaturedCard
Larger card for featured items with background image:

```typescript
export function FeaturedCard({ item }: { item: MarketplaceItem }) {
  return (
    <div
      className="featured-card"
      style={{ backgroundImage: `url(${item.banner_image})` }}
    >
      <div className="card-overlay">
        <h2>{item.name}</h2>
        <p>{item.description}</p>
        <button onClick={() => navigate(`/marketplace/${item.slug}`)}>
          Learn More
        </button>
      </div>
    </div>
  );
}
```

### ReviewCard
```typescript
export function ReviewCard({ review }: { review: Review }) {
  return (
    <div className="review-card">
      <div className="review-header">
        <div className="user-info">
          <img src={review.user.avatar_url} alt={review.user.name} />
          <span>{review.user.name}</span>
        </div>
        <div className="rating">
          {'★'.repeat(review.rating)}{'☆'.repeat(5 - review.rating)}
        </div>
      </div>

      <p className="comment">{review.comment}</p>

      <span className="timestamp">
        {formatDate(review.created_at)}
      </span>
    </div>
  );
}
```

### StatsBar
```typescript
export function StatsBar({ item }: { item: MarketplaceItem }) {
  return (
    <div className="stats-bar">
      <div className="stat">
        <span className="label">Downloads</span>
        <span className="value">{item.downloads || 0}</span>
      </div>
      <div className="stat">
        <span className="label">Rating</span>
        <span className="value">★ {item.average_rating?.toFixed(1) || 'N/A'}</span>
      </div>
      <div className="stat">
        <span className="label">Reviews</span>
        <span className="value">{item.review_count || 0}</span>
      </div>
      <div className="stat">
        <span className="label">Category</span>
        <span className="value">{item.category}</span>
      </div>
    </div>
  );
}
```

## API Endpoints

```typescript
// Get all agents
GET /api/marketplace/agents

// Get all bases
GET /api/marketplace/bases

// Get agent by slug
GET /api/marketplace/agents/{slug}

// Purchase agent (free or credits)
POST /api/marketplace/agents/{slug}/purchase

// Create Stripe checkout session (paid items)
POST /api/marketplace/agents/{slug}/checkout

// Get reviews
GET /api/marketplace/agents/{slug}/reviews

// Create review
POST /api/marketplace/agents/{slug}/reviews
{ rating: number, comment: string }

// Update review
PUT /api/marketplace/reviews/{review_id}
{ rating: number, comment: string }

// Get items by creator
GET /api/marketplace/creator/{user_id}/items

// Get public profile
GET /api/users/{user_id}/public
```

## Best Practices

### 1. Lazy Load Images
```typescript
<img
  src={item.avatar_url}
  alt={item.name}
  loading="lazy"
/>
```

### 2. Cache API Responses
```typescript
const itemCache = new Map();

const loadItem = async (slug: string) => {
  if (itemCache.has(slug)) {
    return itemCache.get(slug);
  }

  const data = await marketplaceApi.getAgentBySlug(slug);
  itemCache.set(slug, data);
  return data;
};
```

### 3. Debounce Search
```typescript
const debouncedSearch = useCallback(
  debounce((query: string) => {
    setSearchQuery(query);
  }, 300),
  []
);
```

## Troubleshooting

**Issue**: Purchase not working
- Check credit balance
- Verify item is active
- Check Stripe configuration (for paid items)

**Issue**: Reviews not loading
- Verify review endpoint
- Check authentication

**Issue**: Images not loading
- Check CORS settings
- Verify image URLs are valid
- Use fallback images
