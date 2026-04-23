# SEO

Declarative SEO tag management for OpenSail's public pages.

## File Index

| File | Purpose |
|------|---------|
| `app/src/lib/seo-manager.ts` | Singleton that tracks active SEO tags (title, meta description, og:*, twitter:*, canonical, structured data). Handles add/remove on mount/unmount to prevent stale tags across route changes |
| `app/src/components/SEO.tsx` | Declarative component. Props: `title`, `description`, `url`, `image`, `type`, `structuredData`. Also exports helpers: `generateProductStructuredData`, `generateOrganizationStructuredData`, `generateBreadcrumbStructuredData` |

## Usage

```tsx
<SEO
  title={agent.name}
  description={agent.description}
  url={`https://tesslate.com/marketplace/${agent.slug}`}
  image={agent.og_image_url}
  structuredData={generateProductStructuredData({
    name: agent.name,
    description: agent.description,
    slug: agent.slug,
    price: agent.price,
    rating: agent.average_rating,
  })}
/>
```

## When to Use

- Every marketplace route (agents, bases, skills, MCP servers, authors, themes)
- Landing and `/home` pages
- Public app detail pages
- Any page you want to be indexable

Private routes (`/dashboard`, `/project/*`, `/settings/*`) do not need `<SEO>` since they are not indexed.

## Structured Data Helpers

- `generateProductStructuredData({ name, description, slug, price, rating })` emits schema.org `Product` + `AggregateRating`
- `generateOrganizationStructuredData()` emits `Organization` for Tesslate
- `generateBreadcrumbStructuredData(items)` emits `BreadcrumbList`

## Cleanup

`SEOManager` automatically removes tags set by a component when it unmounts. No manual cleanup required.

## Related Docs

- `docs/app/CLAUDE.md` – frontend overview
- `docs/app/pages/CLAUDE.md` – pages that set SEO
