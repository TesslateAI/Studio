# Frontend Contexts

Cross-cutting React contexts for OpenSail. Each context owns a slice of
app-wide state plus the mutations that keep it fresh. Providers are composed
at the root (see `App.tsx` / `main.tsx`).

## Existing contexts

- **AuthContext** — Current user, session state, token refresh, OAuth flow.
- **TeamContext** — Active team, team switching, role-based `can(...)` UX gate.
- **MarketplaceAuthContext** — Marketplace-specific auth scope.
- **CommandContext** — Command palette / keyboard shortcut registry.
- **ChatPositionContext** — Chat dock layout state.

## Tesslate Apps contexts (Wave 4)

### AppsContext (`AppsContext.tsx`)

Installed-app state for the current user, plus `installApp`, `uninstallApp`,
`publishVersion` mutations. On mount it calls `appInstallsApi.listMine()` and
caches the envelope. Mutations automatically `refresh()` to keep the list in
sync. Mount above any UI that displays or acts on the user's installed apps.

### WalletContext (`WalletContext.tsx`)

Installer + creator wallet snapshots and the 20 most recent ledger entries.
The creator wallet endpoint returns 403 for non-creators — we absorb that
silently and leave `creatorWallet` at `null`. Mount near any billing-aware
UI (apps marketplace, settings, usage dashboards).

### AdminContext (`AdminContext.tsx`)

Marketplace moderation state: submission queue, yank queue, aggregate stats,
plus `advanceSubmission`, `approveYank`, `rejectYank` mutations. Only fetches
data when `user.is_superuser === true`; otherwise `useAdmin()` returns `null`
and admin pages should redirect. Use `useRequiredAdmin()` after you've already
gated the route.

## Patterns

- All mutations go through `src/lib/api.ts` axios client, which attaches
  Bearer tokens and (for cookie sessions) the `X-CSRF-Token` header via the
  shared request interceptor — do not reimplement auth/CSRF in contexts.
- Errors are captured into an `error` state field; callers show them in a
  toast or inline, and `refresh()` retries.
- Providers no-op for unauthenticated users instead of throwing.
