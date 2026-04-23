# Frontend Development Context

**Purpose**: Guidance for developing and modifying the OpenSail React frontend in `app/src/`.

## When to Load This Context

Load when:
- Modifying UI components or pages
- Adding routes, contexts, hooks, or API methods
- Working on agent chat, streaming, or WebSocket flows
- Building Tesslate Apps UI (install, fork, workspace surfaces)
- Working on the design engineer canvas or architecture canvas
- Implementing admin, billing, or marketplace features

## Entry Points

| File | Purpose |
|------|---------|
| `app/src/main.tsx` | App bootstrap, PostHog init, ASCII easter egg |
| `app/src/App.tsx` | Router, providers (Theme, Auth, Team, Apps, Wallet, Admin, Command, FeatureFlag, ChatPosition), toast config |
| `app/src/config.ts` | Runtime env config (`window._env_` injected by nginx, falls back to `import.meta.env`) |
| `app/src/vite-env.d.ts` | Vite type declarations |

## Core Documentation Index

| Area | Doc |
|------|-----|
| Contexts (Auth, Team, Apps, Wallet, Admin, Command, FeatureFlag, ChatPosition, MarketplaceAuth, NodeConfigPending) | `docs/app/contexts/CLAUDE.md` |
| Custom hooks | `docs/app/hooks/CLAUDE.md` |
| Types (`types/*.ts`) | `docs/app/types/CLAUDE.md` |
| Utils (`utils/*.ts`) | `docs/app/utils/CLAUDE.md` |
| Theme system | `docs/app/state/CLAUDE.md` |
| SEO | `docs/app/seo/CLAUDE.md` |
| Keyboard shortcuts / command palette | `docs/app/keyboard-shortcuts/CLAUDE.md` |
| Layouts | `docs/app/layouts/CLAUDE.md` |
| Pages (top-level, settings, library, admin) | `docs/app/pages/CLAUDE.md` |
| Components (root + feature folders) | `docs/app/components/CLAUDE.md` |
| Chat | `docs/app/components/chat/CLAUDE.md` |
| Design engineer canvas | `docs/app/components/views/CLAUDE.md` |
| Architecture canvas | `docs/app/components/graph/CLAUDE.md` |
| Panels | `docs/app/components/panels/CLAUDE.md` |
| Modals | `docs/app/components/modals/CLAUDE.md` |
| Marketplace cards | `docs/app/components/marketplace/CLAUDE.md` |
| Apps (Tesslate Apps UI) | `docs/app/components/apps/CLAUDE.md` |
| Admin UI | `docs/app/components/admin/CLAUDE.md` |
| Connectors (MCP OAuth) | `docs/app/components/connectors/CLAUDE.md` |
| Cards | `docs/app/components/cards/CLAUDE.md` |
| Edges | `docs/app/components/edges/CLAUDE.md` |
| Canvas (hosted agent nodes) | `docs/app/components/canvas/CLAUDE.md` |
| Git components | `docs/app/components/git/CLAUDE.md` |
| Desktop shell | `docs/app/components/desktop/CLAUDE.md` |
| Project composition | `docs/app/components/project/CLAUDE.md` |
| UI primitives | `docs/app/components/ui/CLAUDE.md` |
| Billing | `docs/app/components/billing/CLAUDE.md` |
| Settings components | `docs/app/components/settings.md` |
| `lib/*` API + helpers | `docs/app/api/CLAUDE.md` |
| `services/taskService.ts` | `docs/app/state/task-service.md` |

## Provider Tree (App.tsx)

```
ThemeProvider
  AuthProvider
    ChatPositionProvider
      FeatureFlagProvider
        TeamProvider
          AppsProvider
            WalletProvider
              AdminProvider
                CommandProvider
                  BrowserRouter
                    TitleBar (desktop only)
                    Routes
```

## Common Patterns

Full pattern documentation (API calls, WebSocket streaming, file events, themes, auth, cancellable requests, command palette, SEO, validation, keyboard shortcuts, settings, marketplace filtering, analytics, skeletons, help menu, multi-session chat) lives at the bottom of this file. The short version:

- **API calls**: `import { projectsApi, chatApi, ... } from '../lib/api'`. Axios instance adds JWT + CSRF and redirects on 401 (except task polling).
- **WebSocket**: `createWebSocket()` returns the shared URL. Agent events flow Worker -> Redis Stream -> API pod -> WS.
- **Cancellable requests**: `useCancellableRequest()` for lifecycle-safe fetches; `isCanceledError()` for manual `AbortController` patterns.
- **Auth**: `useAuth()` from `contexts/AuthContext`, not a duplicate implementation.
- **Command palette**: Register handlers with `useCommandHandlers({ switchView, togglePanel, ... })`; execute via `executeCommand('id', args)`.
- **Theme**: `useTheme()` gives `{ theme, toggleTheme, themePreset, availablePresets, setThemePreset, isReady }`.
- **SEO**: `<SEO title="" description="" url="" structuredData={...} />`.
- **Keyboard**: `lib/keyboard-registry.ts` is the single source of truth. Use `modKey`, `altKey`, `shiftKey` from that module, never raw `'Ctrl'`.

## Route Protection

Guards live in `components/RouteGuards.tsx`:

| Guard | Behavior |
|-------|----------|
| `PrivateRoute` | Redirects to `/login` if not authenticated, preserves intended destination |
| `PublicOnlyRoute` | Redirects authenticated users to `/dashboard` |
| None (public) | Always accessible (marketplace, forgot-password, magic-link) |

Add new routes to both `App.tsx` and the `ROUTE_CONFIG` array in `RouteGuards.test.tsx`.

## Deployment-Specific Concerns

- **Desktop**: `TitleBar` component renders only when running inside Tauri. Uses platform detection on `navigator.userAgent`.
- **Runtime config**: `config.ts` reads `window._env_` first (injected by nginx from ConfigMap), then `import.meta.env` (dev). Allows a single Docker image across all environments.

## File Naming

- Pages and components: `PascalCase.tsx`
- Hooks, utils, lib, services: `camelCase.ts`
- CSS: `kebab-case.css`

## Dev Workflow

```bash
cd app
npm install
npm run dev        # Vite dev server on :5173
npm run build
npm run preview
npm run test
npm run lint
npm run format
```
