# SEO Management Documentation

**Purpose**: This context documents the SEO system in OpenSail, including the SEOManager singleton and SEO component patterns.

## When to Load This Context

Load this context when:
- Adding SEO to new pages
- Working with meta tags or Open Graph
- Implementing structured data (JSON-LD)
- Debugging duplicate meta tag issues
- Understanding SEO cleanup on navigation

## Key Files

| File | Purpose |
|------|---------|
| `app/src/lib/seo-manager.ts` | Singleton SEO tag registry |
| `app/src/components/SEO.tsx` | React component wrapper |

## Related Contexts

- **`docs/app/CLAUDE.md`**: Frontend overview
- **`docs/app/pages/CLAUDE.md`**: Page-level documentation

## Architecture

### The Problem

Without proper management, dynamically adding meta tags causes issues:
- **Duplicate tags**: Navigating between pages adds new tags without removing old ones
- **No cleanup**: Tags persist after component unmounts
- **Original values lost**: Modifying existing tags loses their original values

### The Solution: Tag Registry Pattern

`SEOManager` tracks:
1. Which tags were originally in the HTML
2. Which tags were dynamically added
3. Original values before modification

On cleanup, it:
- Restores modified tags to original values
- Removes dynamically added tags
- Leaves pre-existing tags untouched

## SEOManager API

### Setting Meta Tags

```typescript
import { getSEOManager } from '../lib/seo-manager';

const manager = getSEOManager();

// Basic meta tags (name attribute)
manager.setMeta('description', 'Page description here');
manager.setMeta('keywords', 'react, typescript, tesslate');
manager.setMeta('author', 'Tesslate');

// Open Graph (property attribute)
manager.setMeta('og:title', 'Page Title', true); // true = use property
manager.setMeta('og:description', 'Description', true);
manager.setMeta('og:image', 'https://example.com/image.png', true);
manager.setMeta('og:type', 'website', true);

// Twitter Cards
manager.setMeta('twitter:card', 'summary_large_image');
manager.setMeta('twitter:title', 'Page Title');
```

### Setting Link Tags

```typescript
// Canonical URL
manager.setLink('canonical', 'https://tesslate.com/marketplace/agent-slug');
```

### Setting Document Title

```typescript
manager.setTitle('Agent Name | Tesslate Marketplace');

// Restore original title
manager.restoreTitle();
```

### Structured Data (JSON-LD)

```typescript
manager.setStructuredData({
  '@context': 'https://schema.org',
  '@type': 'SoftwareApplication',
  name: 'My Agent',
  description: 'Agent description',
  applicationCategory: 'DeveloperApplication',
}, 'product-data'); // Optional ID for multiple scripts

// Remove structured data
manager.removeStructuredData('product-data');
```

### Cleanup

```typescript
// Remove specific meta keys
manager.cleanupKeys(['description', 'og:title', 'og:description']);

// Full cleanup (all managed tags + restore title)
manager.cleanup();
```

## SEO Component

The `<SEO>` component wraps SEOManager for declarative usage:

### Basic Usage

```typescript
import { SEO } from '../components/SEO';

function AgentDetailPage() {
  return (
    <>
      <SEO
        title="Advanced Fullstack Agent"
        description="AI-powered agent for building full-stack applications"
        url="https://tesslate.com/marketplace/advanced-fullstack"
        image="https://tesslate.com/images/agent-og.png"
      />
      <div>Page content...</div>
    </>
  );
}
```

### All Props

```typescript
interface SEOProps {
  title: string;           // Page title (auto-appends " | Tesslate Marketplace")
  description: string;     // Meta description
  keywords?: string[];     // Meta keywords
  image?: string;          // Open Graph image URL
  url?: string;            // Canonical URL
  type?: 'website' | 'article' | 'product';  // OG type
  author?: string;         // Author meta tag
  publishedTime?: string;  // Article published time (ISO 8601)
  modifiedTime?: string;   // Article modified time (ISO 8601)
  structuredData?: Record<string, unknown>;  // JSON-LD data
}
```

### With Structured Data

```typescript
import { SEO, generateProductStructuredData } from '../components/SEO';

function AgentDetailPage({ agent }) {
  const structuredData = generateProductStructuredData({
    name: agent.name,
    description: agent.description,
    slug: agent.slug,
    price: agent.price,
    rating: agent.average_rating,
    review_count: agent.review_count,
    creator_name: agent.creator_name,
  });

  return (
    <SEO
      title={agent.name}
      description={agent.description}
      structuredData={structuredData}
    />
  );
}
```

## Helper Functions

### generateProductStructuredData

For marketplace items (agents, bases):

```typescript
import { generateProductStructuredData } from '../components/SEO';

const data = generateProductStructuredData({
  name: 'Agent Name',
  description: 'Agent description',
  slug: 'agent-slug',
  price: 19.99,              // Optional
  pricing_type: 'paid',      // Optional
  rating: 4.8,               // Optional
  review_count: 42,          // Optional
  creator_name: 'Developer', // Optional
  avatar_url: 'https://...',// Optional
  category: 'AI Assistant',  // Optional
});
```

### generateBreadcrumbStructuredData

For navigation breadcrumbs:

```typescript
import { generateBreadcrumbStructuredData } from '../components/SEO';

const breadcrumbs = generateBreadcrumbStructuredData([
  { name: 'Marketplace', url: 'https://tesslate.com/marketplace' },
  { name: 'Agents', url: 'https://tesslate.com/marketplace/agents' },
  { name: 'Advanced Fullstack', url: 'https://tesslate.com/marketplace/advanced-fullstack' },
]);
```

### generateMarketplaceStructuredData

For the marketplace homepage:

```typescript
import { generateMarketplaceStructuredData } from '../components/SEO';

const data = generateMarketplaceStructuredData();
// Returns WebSite schema with SearchAction
```

## Best Practices

### 1. One SEO Component Per Page

```typescript
// Good: Single SEO at page level
function MarketplacePage() {
  return (
    <>
      <SEO title="Marketplace" description="..." />
      <Header />
      <Content />
    </>
  );
}

// Bad: Multiple SEO components
function MarketplacePage() {
  return (
    <>
      <SEO title="Marketplace" />
      <Header>
        <SEO description="..." /> {/* Conflict! */}
      </Header>
    </>
  );
}
```

### 2. Dynamic SEO Based on Data

```typescript
function AgentPage() {
  const { agent, loading } = useAgent();

  // Don't render SEO until data is ready
  if (loading) return <Spinner />;

  return (
    <>
      <SEO
        title={agent.name}
        description={agent.description}
        image={agent.og_image_url}
      />
      <AgentContent agent={agent} />
    </>
  );
}
```

### 3. Fallback for Missing Data

```typescript
<SEO
  title={agent?.name || 'Agent'}
  description={agent?.description || 'Discover AI agents on Tesslate'}
  image={agent?.og_image_url} // undefined = won't set
/>
```

### 4. Canonical URLs

Always set canonical URLs to prevent duplicate content:

```typescript
<SEO
  title="Agent Name"
  description="..."
  url={`https://tesslate.com/marketplace/${agent.slug}`}
/>
```

## Common Issues

### Issue: Duplicate Meta Tags

**Symptom**: Multiple `<meta name="description">` tags in HTML

**Cause**: Not using SEOManager, or multiple SEO components

**Solution**: Use the `<SEO>` component which properly manages tags via SEOManager

### Issue: Tags Not Updating on Navigation

**Symptom**: Old page's meta tags showing on new page

**Cause**: Missing cleanup on component unmount

**Solution**: `<SEO>` component handles cleanup automatically. If using SEOManager directly, call cleanup in useEffect return.

### Issue: Structured Data Validation Errors

**Symptom**: Google Search Console shows schema errors

**Solution**: Validate with Google's Rich Results Test:
```typescript
// Ensure all required fields are present
const data = {
  '@context': 'https://schema.org',  // Required
  '@type': 'SoftwareApplication',     // Required
  name: agent.name,                   // Required
  // ...
};
```

### Issue: Title Not Including Brand

**Symptom**: Page title shows just "Agent Name" without "Tesslate"

**Solution**: The SEO component auto-appends unless title already includes "Tesslate":
```typescript
// Input: "Agent Name"
// Output: "Agent Name | Tesslate Marketplace"

// Input: "Tesslate - AI Agent Builder"
// Output: "Tesslate - AI Agent Builder" (unchanged)
```

## Integration with SSR/SSG

For server-side rendering, the SEOManager checks for `document` availability:

```typescript
// Safe for SSR - returns early if no document
if (typeof document === 'undefined') return;
```

For static site generation, consider using a head management library like `react-helmet-async` alongside SEOManager.

## File Organization

```
app/src/
├── lib/
│   └── seo-manager.ts    # Singleton tag registry
└── components/
    └── SEO.tsx           # React component + helpers
```

## Testing SEO

### Manual Testing

1. Open Chrome DevTools → Elements
2. Search for `<meta` in the `<head>`
3. Navigate between pages
4. Verify tags update correctly and don't duplicate

### Programmatic Testing

```typescript
// In test file
const manager = getSEOManager();
manager.setMeta('description', 'Test');

const meta = document.querySelector('meta[name="description"]');
expect(meta?.content).toBe('Test');

manager.removeMeta('description');
// Verify original or removed
```
