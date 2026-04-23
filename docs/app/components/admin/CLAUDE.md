# Admin Components

Platform-administration UI in `app/src/components/admin/`. Accessed through `pages/AdminDashboard.tsx` and the marketplace-admin page group. All are gated on `useAuth().user?.is_superuser` with redirect-on-failure for defense in depth.

## File Index

| File | Purpose |
|------|---------|
| `admin/AgentRunViewer.tsx` | Inspect a single agent task run: ordered steps, tool calls with parameters/results, thinking blocks, messages, timing, errors. Used for debugging production agent failures |
| `admin/AuditLogViewer.tsx` | Paginated audit-log browser: search, filters (actor, action, resource, date range), CSV export, event detail drawer |
| `admin/BaseManagement.tsx` | Marketplace base-template administration: list, rebuild image (`POST /api/admin/bases/:id/rebuild`), toggle visibility, delete |
| `admin/BillingAdmin.tsx` | Platform billing overview: subscription MRR, credit revenue, marketplace revenue, totals; per-tier subscriber counts; recent transactions |
| `admin/DeploymentMonitor.tsx` | Cross-user deployment watchlist with status, provider, external URL, logs link, retry/cancel controls |
| `admin/ProjectAdmin.tsx` | Project catalog with search, pause (stop all containers), delete, reassign owner, compute tier management |
| `admin/SystemHealth.tsx` | Live-refresh platform health: API uptime, Redis, Postgres, storage (btrfs CSI), volume hub, per-pod status, cronjob last-run times |
| `admin/TokenAnalytics.tsx` | Token usage analytics per model and per user: tokens in/out, cost, request count, alerts for anomalies |
| `admin/UserManagement.tsx` | User directory: search, view details, ban/unban, adjust credits, impersonate, export, soft-delete |

## Pattern Notes

1. All admin components use `getAuthHeaders()` from `lib/api.ts` directly (fetch-based) rather than the axios instance so they can handle non-standard admin endpoints.
2. Pagination is always server-side with `page` + `limit` query params.
3. Actions that mutate user-facing data require a `ConfirmDialog` before firing.
4. Real-time panels (SystemHealth, DeploymentMonitor) poll every 10-30s and show a stale indicator if the last refresh failed.

## Related Docs

- `docs/app/pages/CLAUDE.md` – admin pages (AdminDashboard, AdminMarketplaceReviewPage, AdminSubmissionWorkbenchPage, AdminYankCenterPage, AdminAdversarialSuitePage, AdminCreatorReputationPage)
- `docs/app/contexts/CLAUDE.md` – `AdminContext` for marketplace review queues
