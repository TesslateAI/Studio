# lib/ - API Client and Helpers

All HTTP, WebSocket, and client-side helpers used across the app live in `app/src/lib/`.

## File Index

| File | Purpose |
|------|---------|
| `lib/api.ts` | ~4400-line axios client. Holds the shared axios instance, auth interceptors, WebSocket factory, feature-flag prefetch, and every typed API object |
| `lib/git-api.ts` | Legacy `gitApi` for git operations on a project (status, stage, commit, push, pull, branches, diff, history) |
| `lib/github-api.ts` | Legacy GitHub-only helpers (OAuth connect, user repos, import) |
| `lib/git-providers-api.ts` | Unified `gitProvidersApi` covering GitHub, GitLab, Bitbucket with `resolveRepo`, `listBranches`, `listRepos` |
| `lib/keyboard-registry.ts` | Single source of truth for keyboard shortcuts (platform-aware keys, context filtering, shortcut groups) |
| `lib/posthog.ts` | PostHog singleton with DNT respect, safe `capture()` helper that never throws |
| `lib/seo-manager.ts` | SEO tag registry singleton used by the `<SEO>` component |
| `lib/url-validation.ts` | `isSafeOAuthRedirect`, `loadAllowedDomains` – prevents open-redirect vulnerabilities |
| `lib/deployment-providers.ts` | `DEPLOYMENT_PROVIDERS` catalog, `PROVIDER_CREDENTIAL_HELP`, icon/color/display-name metadata |
| `lib/ansi.tsx` | ANSI escape-code -> styled React spans; supports 16/256/RGB colors, bold, italic, underline |
| `lib/utils.ts` | `cn(...classnames)` tailwind-merge helper; `isCanceledError(err)` for AbortError + Axios CanceledError |

## api.ts Structure

`lib/api.ts` is intentionally monolithic so imports stay typed (`import { projectsApi, chatApi } from '../lib/api'`). Internal organization:

| Section | Contents |
|---------|----------|
| Axios setup | Shared instance, JWT + CSRF interceptors, 401 redirect (except task polling) |
| WebSocket helpers | `createWebSocket()`, `createLogStreamWebSocket(id)`, `createTerminalWebSocket()`, `getAuthHeaders()` for fetch-based calls |
| Type exports | Response shapes for every entity (User, Project, Chat, Message, Agent, Theme, App, Team, etc.) |
| Auth APIs | `authApi`: login, register, verify2fa, OAuth, forgot/reset password, magic link |
| User APIs | `usersApi`, `billingApi`, `creditsApi`, `referralsApi` |
| Project APIs | `projectsApi` (CRUD, start/stop, containers, connections, files, snapshots, timeline), `setupApi` (`.tesslate/config.json`), `nodeConfigApi` (agent-driven config) |
| Chat APIs | `chatApi` (sessions, messages, steps, undo, approvals) |
| Marketplace | `marketplaceApi` (agents, bases, skills, MCP servers, themes, reviews, categories) |
| Apps | `marketplaceAppsApi`, `appVersionsApi`, `appInstallsApi`, `appBundlesApi`, `appSubmissionsApi`, `appYanksApi`, `appRuntimeApi`, `appRuntimeStatusApi`, `appBillingApi` |
| Admin | `adminMarketplaceApi`, various `getAuthHeaders`-based fetch calls |
| Teams | `teamsApi` (teams, memberships, invites, audit log, billing) |
| Deployment | `deploymentsApi`, `deploymentCredentialsApi` |
| Integrations | `featureFlagsApi`, `mcpApi`, `channelsApi`, `schedulesApi`, `themesApi`, `adminMcpApi` |
| Design | `designApi` (index, apply-diff) |

## WebSocket Channels

| Factory | Endpoint | Purpose |
|---------|----------|---------|
| `createWebSocket()` | `/ws?token=...` | Main agent event stream |
| `createLogStreamWebSocket(containerId)` | `/ws/logs/:id` | Container startup logs |
| `createTerminalWebSocket(target)` | `/ws/shell/:target` | xterm.js -> backend shell |

## Auth Flow

1. Axios request -> interceptor attaches `Authorization: Bearer <localStorage.token>` and `X-CSRF-Token` cookie.
2. If 401 and not a task-polling URL, interceptor fires `logout` + redirects to `/login`.
3. OAuth uses `withCredentials: true` cookies; `AuthContext` reconciles both.

## Related Docs

- `docs/app/api/chat-api.md`, `core-api.md`, `git-api.md`, `projects-api.md`, `setup-api.md` – per-domain walkthroughs
- `docs/app/keyboard-shortcuts/CLAUDE.md` – `keyboard-registry.ts`
- `docs/app/seo/CLAUDE.md` – `seo-manager.ts` + SEO component
