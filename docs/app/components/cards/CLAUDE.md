# Cards - Reusable Card Primitives

Generic card building blocks in `app/src/components/cards/`. Used across marketplace, library, project list, apps, and bundle pages.

## File Index

| File | Purpose |
|------|---------|
| `cards/CardSurface.tsx` | Framer-motion wrapper. Variants: `standard` (compact list card) and `featured` (hero gradient card). Handles hover lift, entrance animation via `cardEntrance`, forwards refs. `cva`-based variants |
| `cards/CardHeader.tsx` | Icon + title + description row. Icon sizes `sm` / `md` / `lg` with responsive sizing |
| `cards/CardActions.tsx` | Footer action row, flex-gap aligned; children are typically `Button` components |
| `cards/Badge.tsx` | `cva`-based pill. Intent: `success` / `info` / `warning` / `error` / `neutral`. Uses `--status-*` CSS variables |
| `cards/StatusDot.tsx` | Top-right positioned circle indicating `active` state; green with checkmark when active, muted ring otherwise |
| `cards/StatCard.tsx` | Centered big-number + label card used on dashboards. Animates in with `cardSpring` (stiffness 400, damping 30), optional `index` prop for staggered entrance |
| `cards/motion.ts` | Shared Framer Motion variants: `cardSpring`, `cardEntrance`, `featuredEntrance` |
| `cards/index.ts` | Barrel export |

## Usage

```tsx
import { CardSurface, CardHeader, CardActions, Badge, StatusDot } from '../cards';

<CardSurface variant="standard" onClick={open}>
  <StatusDot active={isRunning} />
  <CardHeader icon={<Rocket />} title="My Project" description="Production app" />
  <Badge intent="success">Live</Badge>
  <CardActions>
    <Button>Open</Button>
  </CardActions>
</CardSurface>
```

## Design Rules

1. Always use `CardSurface` as the outer wrapper so entrance animations + hover states are consistent.
2. Use `StatusDot` for binary on/off state, `Badge` for multi-state status.
3. `StatCard` is for dashboard metrics only; do not use for clickable navigation cards (use `CardSurface` for those).

## Related Docs

- `docs/app/components/CLAUDE.md` – component-level conventions
- `docs/app/components/marketplace/CLAUDE.md` – marketplace cards built on these primitives
