# React Contexts

Every cross-cutting state provider in OpenSail lives under `app/src/contexts/`. The provider tree is mounted in `App.tsx`.

## File Index

| File | Purpose |
|------|---------|
| `contexts/AuthContext.tsx` | Centralized auth state (JWT + OAuth cookie + cross-tab sync); exposes `status`, `user`, `login`, `logout`, `checkAuth`, `clearError` |
| `contexts/auth/types.ts` | `AuthenticationError` class and `AuthErrorCode` union (NETWORK_ERROR, INVALID_CREDENTIALS, SESSION_EXPIRED, TOKEN_INVALID, UNAUTHORIZED, FORBIDDEN, SERVER_ERROR, UNKNOWN) |
| `contexts/TeamContext.tsx` | Active team, memberships, role, permission map (`can()`), `refreshTeams()`; mirrors backend `ROLE_PERMISSIONS` |
| `contexts/AppsContext.tsx` | Tesslate Apps install state: `myInstalls`, `install()`, `uninstall()`, `publish()`, `refresh()` |
| `contexts/WalletContext.tsx` | Installer + creator wallet snapshots, recent ledger entries; creator wallet is lazy (403 surfaces as null) |
| `contexts/AdminContext.tsx` | Superuser-only marketplace admin state: submission queue, yank queue, aggregate stats, review mutations; value is `null` for non-superusers |
| `contexts/CommandContext.tsx` | Type-safe command dispatch replacing CustomEvent. `useCommandHandlers({...})` registers, `executeCommand(id, args)` fires, `isCommandAvailable(id)` checks |
| `contexts/FeatureFlagContext.tsx` | Prefetched feature flags from backend. Consumed via hooks in `useFeatureFlag.ts` |
| `contexts/featureFlagState.ts` | Context + types (split out for react-refresh compat) |
| `contexts/useFeatureFlag.ts` | `useFeatureFlag(name)` and `useFeatureFlags()` hooks |
| `contexts/ChatPositionContext.tsx` | User preference for chat panel position (`left` / `center` / `right`); optimistic updates with server persistence |
| `contexts/MarketplaceAuthContext.tsx` | Lightweight optional auth for marketplace pages; exposes `{ isAuthenticated, isLoading }`; provided by `MarketplaceLayout` |
| `contexts/NodeConfigPendingContext.tsx` | Tracks which architecture nodes currently have pending agent-driven config prompts (pulsing ring indicator) |

## Provider Order (App.tsx)

```
Theme -> Auth -> ChatPosition -> FeatureFlag -> Team -> Apps -> Wallet -> Admin -> Command -> Router
```

Theme is outermost so CSS variables are ready before any child mounts. Auth is next because every other provider may call authenticated APIs. Command wraps the Router so pages can register handlers.

## Usage Rules

1. Do not duplicate auth state. Always use `useAuth()` from `AuthContext`, never roll your own `/api/users/me` fetch.
2. `useCommandHandlers` auto-cleans on unmount. Manual `registerHandlers` requires an `useEffect` cleanup.
3. Admin pages must check `useAuth().user?.is_superuser` AND call `useRequiredAdmin()` for defense in depth.
4. Marketplace pages use `useMarketplaceAuth()` (optional), NOT `useAuth()` (which would block public view rendering).
5. `NodeConfigPendingContext` only lives inside the architecture view, not app-wide.

## Adding a New Context

1. Create `contexts/MyContext.tsx` with provider component + hook (`useMyContext`).
2. Throw in the hook if used outside the provider (`throw new Error('useMyContext must be used within MyProvider')`).
3. Mount in `App.tsx` at the correct depth (after any providers it depends on).
4. If the context is consumed across route groups, mount ABOVE the `BrowserRouter`.

## Related Docs

- `docs/app/CLAUDE.md` – frontend overview
- `docs/app/hooks/CLAUDE.md` – hooks that consume contexts
- `docs/app/layouts/CLAUDE.md` – layouts that provide scoped contexts
