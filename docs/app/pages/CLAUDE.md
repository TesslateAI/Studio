# Pages

Every route-level component in `app/src/pages/` and sub-directories.

## Top-Level Pages

| File | Route | Purpose |
|------|-------|---------|
| `Home.tsx` | `/home` | Landing for authenticated users: recent projects, quick actions, import, onboarding prompts. `/` always redirects here (post-landing-deletion) |
| `Dashboard.tsx` | `/dashboard` | Projects grid, create, import from git providers, delete with confirmation, task polling for setup, user profile dropdown |
| `ProjectSetup.tsx` | `/project/:slug/setup` | Setup wizard with agent (AI analysis) and manual (`ServiceConfigForm`) tabs for `.tesslate/config.json` |
| `ProjectPage.tsx` | `/project/:slug/builder` | Main builder: editor, chat, preview, design, panels, floating tool dock. Switches between view modes via `CommandContext` |
| `ProjectOverview.tsx` | `/project/:slug` | Project hub with tabs (Idea, Build, Launch, etc.), quick status, compute tier management. Navigation root for a project |
| `Marketplace.tsx` | `/marketplace` | Marketplace home: featured + category carousels for agents, bases, skills, MCP servers |
| `MarketplaceBrowse.tsx` | `/marketplace/browse/:type` | Filterable paginated browse with server-side filtering (agents) or client-side (bases); includes skills and MCP servers |
| `MarketplaceDetail.tsx` | `/marketplace/:slug` | Detail page for a marketplace item: description, reviews, install/purchase button |
| `MarketplaceAuthor.tsx` | `/marketplace/author/:username` | Creator profile with their marketplace listings |
| `MarketplaceSuccess.tsx` | `/marketplace/success` | Stripe post-checkout landing; verifies purchase via `session_id` + `agent` query params |
| `Library.tsx` | `/library` | User's purchased items across tabs: agents, bases, skills, MCP servers, themes, models. Agent edit modal includes advanced config (compaction_model, context_window, thinking_effort) |
| `Chat.tsx` | `/chat` | Standalone chat (not scoped to a project). Uses `useChatSessions` + `useAgentChat` hooks with `ChatSessionSidebar` + `ChatTopBar` + `ChatMessageList` + `ChatInput` |
| `Feedback.tsx` | `/feedback` | Public feedback board: submit bugs/ideas, browse submissions |
| `Referrals.tsx` | `/referrals` | Affiliate/referral dashboard: referral code, referred users, earnings |
| `UserProfile.tsx` | `/@:username` | Username-based public profile resolver |
| `Login.tsx` | `/login` | JWT login + email 2FA + OAuth (Google, GitHub). Calls `checkAuth({ force: true })` after 2FA |
| `Register.tsx` | `/register` | User registration with optional referrer from sessionStorage |
| `ForgotPassword.tsx` | `/forgot-password` | Request password-reset email (always shows success to prevent user enumeration) |
| `ResetPassword.tsx` | `/reset-password` | Set new password using token from `?token=` query param |
| `MagicLinkConsume.tsx` | `/auth/magic` | Magic-link consumer with manual click-through to prevent email safelink auto-consumption (Gmail Safelinks, Outlook ATP, Slack unfurl) |
| `Logout.tsx` | `/logout` | Clears state and redirects to login |
| `AuthCallback.tsx` | `/auth/github/callback` | GitHub OAuth callback for git operations |
| `OAuthLoginCallback.tsx` | `/auth/:provider/callback` | OAuth login callback for Google/GitHub |
| `ImportRedirect.tsx` | `/import?repo=...` | Deep-link entry for external "Edit in Tesslate" buttons. Auth-aware redirect to `/dashboard?import_repo=...` or `/login` preserving the deep link |
| `InviteAcceptPage.tsx` | `/invite/:token` | Team invitation acceptance with team preview, role, inviter |
| `AdminDashboard.tsx` | `/admin` | Overview of platform metrics (users, projects, revenue, health). Gated by `is_superuser` |
| `AdminMarketplaceReviewPage.tsx` | `/admin/marketplace` | Tabbed admin UI for marketplace: Submissions, Yank Queue, Stats, Monitoring, Reputation |
| `AdminSubmissionWorkbenchPage.tsx` | `/admin/marketplace/submissions/:submissionId` | Detail + decision UI for a single `AppSubmission`. Left: manifest preview. Right: per-stage checks + advance/reject. Client `VALID_TRANSITIONS` mirrors `submissions.py` |
| `AdminYankCenterPage.tsx` | `/admin/marketplace/yanks` | Yank moderation table. Critical yanks require second admin (`needs_second_admin: true`) |
| `AdminAdversarialSuitePage.tsx` | `/admin/marketplace/adversarial` | Adversarial-run submission form + session-local recent runs |
| `AdminCreatorReputationPage.tsx` | `/admin/marketplace/reputation` | Signed-delta reputation adjustment by user_id |
| `AppsMarketplacePage.tsx` | `/apps` | Marketplace of `MarketplaceApp`s with search, category filter, pagination (page size 20), install wizard |
| `AppDetailPage.tsx` | `/apps/:appId` | App details with version list, install wizard, fork modal |
| `AppSourceBrowserPage.tsx` | `/apps/:appId/source` | Monaco-based source browser for apps. Visibility: public / installers-only / private |
| `AppWorkspacePage.tsx` | `/apps/:appId/workspace` | Run an installed app: session lifecycle (begin/end), invocation control, live iframe surface |
| `MyAppsPage.tsx` | `/apps/my` | Installed apps list with start/stop/uninstall; `AppDetailsDrawer` for details |
| `BundleDetailPage.tsx` | `/apps/bundles/:bundleId` | App bundle details + `BundleInstallWizard` |
| `ForkPage.tsx` | `/apps/:appId/fork` | Fork an app version into a new marketplace app under the current team |
| `CreatorStudioPage.tsx` | `/creator` | Creator dashboard with tabs: apps, drafts, submissions, billing |
| `CreatorAppPublishPage.tsx` | `/creator/publish` | Publish a project as a new app version (manifest editor, compatibility check, publish action) |
| `CreatorBillingPage.tsx` | `/creator/billing` | Creator wallet + ledger; exports `CreatorBillingPanel` reused by `CreatorStudioPage` |

## Settings Pages (`pages/settings/`)

| File | Route | Purpose |
|------|-------|---------|
| `ProfileSettings.tsx` | `/settings/profile` | Name, email, avatar, bio, social links (Twitter, GitHub, website) |
| `PreferencesSettings.tsx` | `/settings/preferences` | Theme preset, diagram model, chat position |
| `SecuritySettings.tsx` | `/settings/security` | Password change, 2FA status, active sessions |
| `DeploymentSettings.tsx` | `/settings/deployment` | Provider credentials (Vercel, Netlify, Cloudflare, Amplify, custom S3) merged from old ApiKeysSettings |
| `BillingSettings.tsx` | `/settings/billing` | Subscription overview, credit balance, transactions, credit history, `PlanSelectionModal` (inline since `SubscriptionPlans.tsx` was removed) |
| `ApiKeysSettings.tsx` | `/settings/api-keys` | External Agent API keys: create, copy-once, list, revoke. SHA-256 hashed server-side |
| `ConnectionsSettings.tsx` | `/settings/connections` | Gateway platform connections (Telegram, Slack, Discord, WhatsApp, Signal, CLI): connect, disconnect, status |
| `ChannelsSettings.tsx` | `/settings/channels` | Per-channel configuration: agent routing, project binding, encrypted credentials |
| `SchedulesSettings.tsx` | `/settings/schedules` | Agent cron schedules: create, pause, resume, trigger, delete |
| `TeamSettingsPage.tsx` | `/settings/team` | Team general settings: name, avatar, leave, delete |
| `TeamMembersPage.tsx` | `/settings/team/members` | Member list, invite by email or shareable link, role management, remove |
| `TeamBillingPage.tsx` | `/settings/team/billing` | Team subscription, credits, usage (admin-scoped) |
| `AuditLogPage.tsx` | `/settings/team/audit` | Team-scoped audit trail with filters (actor, action, resource, date), paginated |

## Library Pages (`pages/library/`)

| File | Route | Purpose |
|------|-------|---------|
| `library/AgentsPage.tsx` | `/library?tab=agents` | Purchased and custom agents with enable/disable, edit (name, icon, model, compaction_model, context_window, thinking_effort), delete |
| `library/BasesPage.tsx` | `/library?tab=bases` | User-submitted bases with visibility toggle, edit, soft-delete, download count. "Submit Base" opens `SubmitBaseModal` |
| `library/SkillsPage.tsx` | `/library?tab=skills` | Purchased marketplace skills filtered from `marketplaceApi.getAllSkills()` |
| `library/ConnectorsPage.tsx` | `/library?tab=connectors` | Installed MCP connectors (per-user and per-project); OAuth reconnect, tool permissions drawer, uninstall |
| `library/ModelsPage.tsx` | `/library?tab=models` | Available LLM models with pricing, BYOK key management |
| `library/ThemesPage.tsx` | `/library?tab=themes` | User's themes (purchased + custom); enable, create from scratch, delete |
| `library/types.ts` | – | Local types: `LibraryAgent`, `LibraryBase`, `LibrarySkill`, `InstalledMcpServer`, `Model` |

## Common Patterns

Covered in detail elsewhere:
- Data loading / polling: `docs/app/hooks/CLAUDE.md`
- URL params + searchParams for tabs/filters: `docs/app/pages/settings.md`
- Modal management: `docs/app/components/modals/CLAUDE.md`
- Command palette integration: `docs/app/keyboard-shortcuts/CLAUDE.md`

## Route Guards

Every authenticated page is wrapped in `<PrivateRoute>` from `components/RouteGuards.tsx`. Public pages (marketplace, forgot-password, magic-link) are unwrapped or wrapped in `<PublicOnlyRoute>` where appropriate. Adding a new route requires updating `ROUTE_CONFIG` in `RouteGuards.test.tsx`.

## Related Docs

- `docs/app/pages/*.md` – per-page deep dives (dashboard, project-setup, project-builder, project-graph, marketplace, marketplace-browse, settings, billing, auth)
- `docs/app/CLAUDE.md` – frontend overview
- `docs/app/components/CLAUDE.md` – components that pages compose
