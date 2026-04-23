# Marketplace Cards and Primitives

Marketplace-specific display components in `app/src/components/marketplace/`. Used by `Marketplace.tsx`, `MarketplaceBrowse.tsx`, `MarketplaceDetail.tsx`, and the `MarketplacePanel`.

## File Index

| File | Purpose |
|------|---------|
| `marketplace/index.ts` | Barrel export |
| `marketplace/AgentCard.tsx` | Standard marketplace item card: icon, name, description, creator, pricing (free/paid), rating, install count, tags, install button |
| `marketplace/FeaturedCard.tsx` | Hero variant for featured items with gradient, larger icon, detailed description, multiple CTAs |
| `marketplace/SkeletonCard.tsx` | Loading placeholder. Variants: `card` (standard), `featured` (hero). Rendered in grids while data loads |
| `marketplace/Pagination.tsx` | Accessible pagination control (`aria-label`, `aria-current`), ellipsis for large page ranges, disabled states, theme-aware styling |
| `marketplace/ReviewCard.tsx` | User review with stars, author, date, body text, helpful-count |
| `marketplace/RatingPicker.tsx` | Star-rating input (1-5) with hover preview, keyboard support |
| `marketplace/StatsBar.tsx` | Horizontal stats row: downloads, rating, active installs, version; icon + label + value |

## Layout Patterns

Grid layouts use Tailwind:

```tsx
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
  {loading
    ? Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} variant="card" />)
    : items.map(item => <AgentCard key={item.id} {...item} />)}
</div>
<Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
```

## Related Docs

- `docs/app/pages/marketplace.md` – marketplace page composition
- `docs/app/pages/marketplace-browse.md` – browse + filter page
- `docs/app/components/cards/CLAUDE.md` – lower-level card primitives these build on
