# Apps - Tesslate Apps UI

Components for publishing, installing, forking, and running Tesslate Apps in `app/src/components/apps/`.

## File Index

| File | Purpose |
|------|---------|
| `apps/AppDetailsDrawer.tsx` | Right-side drawer for a single `AppInstance`. Tabs: Overview (manifest summary, update policy), Containers (runtime status per service), Schedules (cron triggers), Logs (WebSocket log stream via `createLogStreamWebSocket`). Drives start/stop/uninstall actions |
| `apps/AppInstallWizard.tsx` | Multi-step modal to install an `AppVersion`: pick team/project target, review manifest permissions, show `CompatReport` warnings, choose `UpdatePolicy` (auto/manual/pinned), confirm wallet spend. Consumes `AppsContext` + `TeamContext` |
| `apps/BundleInstallWizard.tsx` | Bulk-install flow for an `AppBundle` (e.g., "Tesslate Starter Pack"). Iterates `appBundlesApi.install` and displays per-app success/failure with CheckCircle/XCircle |
| `apps/ForkModal.tsx` | Fork an existing app into a new `MarketplaceApp` under the current team. Prompts for new slug/name with regex validation (`/^[a-z0-9]+(-[a-z0-9]+)*$/`), calls `marketplaceAppsApi.fork`. Navigates to the fork's creator page |
| `apps/IframeAppHost.tsx` | Sandboxed iframe host implementing the shell<->app postMessage protocol v1. Envelope: `{v:1, kind:'request'/'response'/'event', id, topic, payload}`. Allowed request topics: `runtime.end_session`, `runtime.begin_invocation`, `runtime.end_invocation`. Enforces same-origin for security |
| `apps/WorkspaceSurface.tsx` | Renders a single `Surface` (ui/chat/scheduled/triggered/mcp-tool) of an installed app inside a `CardSurface` wrapper. Delegates UI surfaces to `IframeAppHost`, chat surfaces to the in-app chat component |

## Surface Kinds

| Kind | Renders |
|------|---------|
| `ui` | `IframeAppHost` with the surface's `entrypoint` URL |
| `chat` | Chat panel scoped to this app instance |
| `scheduled` | Read-only card listing cron triggers |
| `triggered` | Read-only card listing webhook triggers |
| `mcp-tool` | Tool signature card with test-invoke button |

## Install Saga (Client Side)

1. User selects target from `AppInstallWizard` step 1.
2. `appVersionsApi.getCompatReport(versionId, targetProjectId)` -> show warnings in step 2.
3. User chooses update policy in step 3.
4. `appInstallsApi.install({ app_version_id, project_id, wallet_mix, update_policy })` -> saga kicks off.
5. Client polls via `AppsContext.refresh()` until the new install appears with status `running`.
6. On failure, saga rolls back and wizard surfaces the error.

## Related Docs

- `docs/apps/CLAUDE.md` – Tesslate Apps backend pipeline
- `docs/app/contexts/CLAUDE.md` – `AppsContext`, `WalletContext`
- `docs/app/pages/CLAUDE.md` – `AppDetailPage`, `AppWorkspacePage`, `AppsMarketplacePage`, `MyAppsPage`, `ForkPage`
