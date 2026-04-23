# Edges - XYFlow Custom Edges

Custom edge renderers for the architecture canvas in `app/src/components/edges/`. Each edge type has a distinct visual style and sometimes an animated flow indicator.

## File Index

| File | Purpose |
|------|---------|
| `edges/index.ts` | Barrel export of all edges |
| `edges/HttpApiEdge.tsx` | Orange solid smooth-step edge for REST/HTTP connections. Animated flow dots |
| `edges/DatabaseEdge.tsx` | Green solid edge for DB connections (Postgres, MySQL, Mongo) |
| `edges/CacheEdge.tsx` | Blue solid edge for Redis / Memcached connections |
| `edges/EnvInjectionEdge.tsx` | Dotted gray edge for environment variable injection between containers |
| `edges/BrowserPreviewEdge.tsx` | Edge connecting a container to a BrowserPreviewNode (routes preview traffic) |
| `edges/DeploymentEdge.tsx` | Rocket-styled edge from a container to a `DeploymentTargetNode` showing deployment state (pending/success/failure) |
| `edges/EdgeDeleteButton.tsx` | Small "x" label rendered at the midpoint of any selected edge via `EdgeLabelRenderer`; calls `onDelete(edgeId)` |

## Edge Type Registration

```tsx
const edgeTypes = {
  http_api: HttpApiEdge,
  database: DatabaseEdge,
  cache: CacheEdge,
  env_injection: EnvInjectionEdge,
  browserPreview: BrowserPreviewEdge,
  deployment: DeploymentEdge,
};
```

## Edge Style Conventions

| Kind | Stroke | Width | Dash | Animation |
|------|--------|-------|------|-----------|
| http_api | `#f89521` | 2 | solid | Flow dots |
| database | `#22c55e` | 2 | solid | None |
| cache | `#3b82f6` | 2 | solid | None |
| env_injection | `#6b7280` | 1.5 | `4 4` | None |
| agent_invokes | `#a855f7` | 2 | `6 4` | None |

## Related Docs

- `docs/app/components/graph/CLAUDE.md` – how edges compose in the canvas
- `docs/app/components/canvas/CLAUDE.md` – `AgentInvokesEdge` from Apps
