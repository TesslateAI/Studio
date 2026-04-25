# Builder UX refresh + sidebar tree + platform stability

Two days of work on `wip/sidebar-tree-and-attachment-fix` (forked from `develop` at `b39c5b01`). Started as a sidebar tree + attachment-drop fix; grew into a full builder-shell refresh, a borderless theme system rolled across ~60 files, and four platform-stability fixes (project_files race, compute spec drift, config drift on warm-start, agent SSE saturation). Submodule `packages/tesslate-agent` is bumped one commit (`4053d4cf` → `1fd65c1c`) for the attachment-rendering fix.

## TL;DR

- **Sidebar:** the old "Recent" list is replaced with a live two-level project tree (`SidebarTree`) backed by a single `GET /api/sidebar/tree` round-trip. Per-chat / per-folder / global running-agent spinners surface concurrent agent work across the whole workspace.
- **Builder shell:** `/project/:slug` now lives inside `DashboardLayout` and shares one `NavigationSidebar` instance with the dashboard via the new `BuilderShellContext`. `ProjectPage`'s four floating panels (GitHub / Notes / Settings / Timeline) are gone; they're now first-class dock tabs in `ToolTabsPanel`. One UX pattern instead of two.
- **Theme:** new `borderless` flag on the theme schema; when true the frontend sets every border CSS variable to transparent and `[data-borderless="true"]` on `<html>`. Default light/dark themes ship with `borderless: true`. New `--card-hover` token replaces the old border-glow + lift + shadow card-hover combo with a flat surface tint.
- **Concurrent agents:** `AgentRunsContext.tsx` is split into `agentRunsContext.ts` / `useAgentRuns.ts` / `AgentRunsProvider.tsx`. Provider now multiplexes via a single project-level SSE stream once parallel runs exceed 5, dodging the browser's ~6-per-origin EventSource cap. LRU eviction on the per-task path keeps unfocused chats from starving the focused one.
- **Stability:** atomic `INSERT … ON CONFLICT` upsert for `project_files` + dedupe migration `0072` (fixes design-bridge duplicate-row crash); spec-hash drift detection on warm-starts (config edits no longer get silently ignored); `ensure_config_synced()` reads `.tesslate/config.json` before every start/restart so `start_all` is always config-authoritative; attachment size caps at the API boundary; auto-title fork-session rewrite so chats stop getting stuck "Untitled".

## Scope at a glance

| Area | What changed |
|------|--------------|
| Sidebar / navigation | New `SidebarTree` + `/api/sidebar/tree` router; `NavigationSidebar` rewritten |
| Builder shell | `BuilderShellContext`; project routes moved into `DashboardLayout`; floating panels → dock tabs |
| Theme system | `borderless` flag end-to-end; `--card-hover` token; ~60-file design-token sweep |
| Concurrent agents | `AgentRunsProvider` rename + SSE multiplex + LRU; sidebar/folder/chat spinners |
| Attachments | API size caps + submodule bump that actually renders attachments in the user turn |
| Auto-title | Fork-session, attachment-aware seed, truncation fallback, never stays "Untitled" |
| Project files race | `services/project_files.upsert_project_file()` + migration `0072_dedupe_project_files` |
| Compute drift | `tesslate.io/spec-hash` annotation + drift detection in `compute_manager._start_environment_inner` |
| Config sync | `services/config_sync.ensure_config_synced()` called before every start/restart |
| Surgical fixes | iframe `colorScheme: 'normal'`, tooltip jitter, dock drag-and-drop, `useToolDock` activeTabId |
| Seeds | "Simplify" skill removed; two skill URL 404s fixed; default themes flipped to borderless |

---

## 1. Sidebar tree — "Projects ARE folders"

Replaces the old Recent list with a two-level tree: root chats + project folders that expand to their chats. Zero schema migration (`Chat.project_id` is already nullable).

**New backend — `orchestrator/app/routers/sidebar.py`:**
- `GET /api/sidebar/tree` returns `{ rootChats, projects: [{ …, chats }] }` in one round-trip.
- Per-project chat batching uses a single windowed `ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY updated_at DESC NULLS LAST, created_at DESC)` query — Postgres + SQLite ≥ 3.25 compatible.
- Auth mirrors `/api/projects/` exactly: admins of `default_team_id` see all team projects; regular members see `visibility == "team"` plus explicit `ProjectMembership`. App-instance projects are filtered out via `exclude_app_instances_clause()`. Hidden statuses: `archived`, `deleted`.
- Sort by `max(project.updated_at, max_chat_updated_at, project.created_at)` desc — done in Python because SQLite has no `GREATEST()`. Limits: `project_limit` 1–100 (default 30), `root_chat_limit` 1–200 (default 50), `chats_per_project` 1–100 (default 20).
- Wired in `main.py`; prefix lives on the router.

**New frontend — `app/src/components/ui/SidebarTree.tsx`:**
- Polls `sidebarApi.getTree()` every 4s, pauses when the tab is hidden.
- Folder expand/collapse persisted to `localStorage` under `sidebarTree.expandedProjects`. Folders open by default; folder icon is the click-target, no caret.
- Active project hoists to the top; "Untitled"/empty chats hidden.
- `+` button opens `CreateProjectModal` directly.
- Concurrent-agent spinners: running chats render a `Loader2` + bold title; project folders with active children show a count badge; collapsed sidebar overlays a tiny spinner on the folder icon.
- Clicking a project chat deep-links to `/project/{slug}/builder` with `state.sessionId` so it preselects in the builder rather than opening the standalone `/chat`.

**Modified — `app/src/components/ui/NavigationSidebar.tsx`:** dropped ~200 lines of the old Recent section; now just renders `<SidebarTree/>`.

**API client — `app/src/lib/api.ts`:** new `sidebarApi.getTree(opts)` + `SidebarChat`, `SidebarProject`, `SidebarTreeResponse` interfaces.

## 2. Builder shell — one sidebar, dock-based panels

**Old:** `/project/:slug` was a separate route outside `DashboardLayout`, mounted its own `NavigationSidebar` (lost expansion state on dashboard ↔ project nav), and rendered four `FloatingPanel`s (GitHub / Notes / Settings / Timeline) toggled with Cmd+Shift+G/N/S. Two parallel UX patterns: tabs and floating panels.

**New:**
- `App.tsx` moves `/project/:slug` and `/project/:slug/builder` *inside* `DashboardLayout`'s `<Route>` so the same `NavigationSidebar` instance survives the transition.
- New `app/src/contexts/BuilderShellContext.tsx` lets pages register a `builderSection` render-prop via `useRegisterBuilderSection(...)`; `DashboardLayout` passes it into the sidebar. ProjectPage registers `undefined` — the builder sidebar is intentionally identical to the dashboard sidebar; users navigate back via the breadcrumb.
- Floating panels gone. The four panel `ToolType`s (`'volume' | 'notes' | 'settings'` plus the existing `'repository'`) open as tabs in the existing `ToolTabsPanel` dock. Cmd+Shift+G/N/S now `dock.openTool(...)`. `FloatingPanel` and `MobileWarning` imports removed.
- `ProjectPage.tsx` shrinks ~600 lines net.

## 3. Borderless theme system + ~60-file design-token sweep

**Backend (`schemas_theme.py`, `routers/themes.py`):** `ThemeJsonSchema` and `ThemeResponse` gain optional top-level `borderless: bool = False`. Three theme endpoints (`list_themes_full`, `get_theme`, `get_default_theme`) populate from `theme_json.get("borderless", False)`. `ThemeJsonSchema.model_config["extra"]` is still `"forbid"`.

**Seeds (`seeds/themes.py`, default-dark.json, default-light.json):** seed loader persists `borderless` from JSON; both bundled defaults flip to `"borderless": true`.

**Frontend (`themePresets.ts`):**
- New `Theme.borderless?: boolean` field.
- `applyThemePreset()` forces every border var (`--border`, `--border-hover`, `--sidebar-border`, `--input-border`, `--input-border-focus`, `--code-block-border`) to `transparent` when set, and stamps `[data-borderless="true"]` on `<html>`.
- New `--card-hover` token (8% white-mix in dark, 5% muted-mix in light).
- `ThemesPage` editor adds a "Borders: Hidden / Visible" toggle that writes `theme_json.borderless`.

**Card-hover behavior change** in `CardSurface`, `CardHeader`, `MarketplaceSidebar`, `AgentCard`, `ThemeCard`, `FeaturedCard`: removed `hover:border-[primary]/25` + `hover:shadow-[0_8px_30px_…]` + `hover:text-primary`, replaced with flat `hover:bg-[var(--card-hover)]`. Hover lift bumped 3px → 4px. `h-full` added so cards in a grid rise together.

**Hardcoded color drops** (literal Tailwind palettes → CSS vars) across `AgentMessage`, `AgentStep`, `ToolCallDisplay`, `Preview`, `CommandPalette`, `KeyboardShortcutsModal`, `ContainerSelector`, `GitHubPanel`, `TimelinePanel`, `ChatSessionSidebar`, `ReviewCard`, `KanbanPanel`, `AssetsPanel`, `DeploymentsPanel`, `MarketplacePanel`, `RepositoryPanel`, snapshots board, library pages. `green-500`/`red-500` → `var(--status-success/error)`; `bg-white/10` → `bg-[var(--surface-hover)]`; old `isDark ? 'white/10' : 'black/10'` branches removed entirely. `KeyboardShortcutsModal` no longer needs `useTheme()` at all.

**Home page:** Tesslate logo replaced with `Welcome to OpenSail, {firstName}` (from `AuthContext`); border classes stripped from action cards, recent project list, connectors card.

## 4. Concurrent agents — SSE multiplex + spinners

`AgentRunsContext.tsx` is **deleted**, replaced by:
- `agentRunsContext.ts` — Context + types.
- `useAgentRuns.ts` — hook.
- `AgentRunsProvider.tsx` — provider, **with new behavior**:
  - Per-task `EventSource` for ≤5 active runs in a project.
  - At >5, switches to a single `chatApi.subscribeToProject()` mux stream. Avoids the browser's ~6-per-origin SSE cap.
  - LRU eviction on per-task subscriptions so background chats don't starve the focused one.

Sidebar tree consumes the live counts to render per-chat / per-folder / sidebar-level spinners.

## 5. Attachment pipeline — API caps + submodule render fix

**Symptom:** paste a big block of text into chat → agent replies "Task completed" without doing anything.

**Root cause:** attachments flowed UI → API → DB → `AgentTaskPayload` → worker → agent context fine, then got dropped at `tesslate-agent` because the agent loop never read `context["attachments"]`.

**Submodule bump (`packages/tesslate-agent` `4053d4cf` → `1fd65c1c`, +215/-7, 4 files, single commit `feat(agent): render chat attachments in user turn`):**
- New `_build_user_turn` helper inlines `pasted_text` / `file_reference` as labeled text blocks; renders `image` attachments as OpenAI vision content-parts.
- 126 new lines of pytest in `tests/agent/test_tesslate_agent.py` (text-only / pasted-text / file-reference / image).

**Orchestrator (`schemas.py`):** `ChatAttachmentSchema` adds two `ClassVar` size caps + `model_validator`:
- `MAX_PASTED_TEXT_CHARS = 100_000`
- `MAX_IMAGE_BASE64_CHARS = 20_000_000` (~15 MB raw)
Rejected at the API boundary so nothing oversized hits Redis/DB.

## 6. Auto-title — fork-session, attachment-aware, never "Untitled"

`orchestrator/app/worker.py` (+141):
- New `_seed_text_for_title(user_message, attachments)` returns first non-empty option from message → `pasted_text` (prefixed with label) → `file_reference` path → `image` label.
- New `_fallback_title(seed)` — first non-blank line, trimmed to 60 chars, falls back to `"New chat"`.
- `_auto_title_chat` rewritten to take `attachments` and `assistant_response`. Builds a fork message list — system prompt → seed_user (cap 500) → assistant_response (cap 1000) → synthetic `"Generate a title for this chat session."`. The titling LLM now has the agent's first reply as context, so a bare "hiii" doesn't poison the title.
- LLM failure logs and falls back to `_fallback_title`; commit failure logs but doesn't raise. Title is set even on LLM failure.
- `execute_agent_task` now passes `payload.attachments` and `final_response` into the helper.

## 7. Project files race — atomic upsert + dedupe migration

**Symptom:** design-bridge installer fired two writes back-to-back at view mount; check-then-insert (`select` → `if exists update else add`) raced under concurrent agent writes; `scalar_one_or_none()` then crashed for every later save to that path. Surfaced as duplicate `public/__tesslate-design-bridge.js` rows in `fire-7tw0qy`.

**Fix — new `orchestrator/app/services/project_files.py` (72 lines):**
- Single `upsert_project_file(...)` entry point.
- Dialect-aware `INSERT … ON CONFLICT (project_id, file_path) DO UPDATE` via `sqlalchemy.dialects.postgresql.insert` for cloud / `sqlalchemy.dialects.sqlite.insert` for desktop. `NotImplementedError` for any other dialect.
- Caller owns `commit()`.

**Migration — `orchestrator/alembic/versions/0072_dedupe_project_files.py`:**
- Down-revision `0071_scrub_git_remote_url_tokens`.
- Step 1 (destructive, irreversible): `DELETE FROM project_files` keeping the newest per `(project_id, file_path)` via `ROW_NUMBER() OVER (PARTITION BY …)` — newest by `COALESCE(updated_at, created_at) DESC`, ties by `id DESC`.
- Step 2: `op.batch_alter_table` adds `uq_project_files_project_path` unique constraint (SQLite-safe rebuild).
- `downgrade()` only drops the constraint; deleted rows are not recoverable. Acceptable because duplicates were always invariant violations.

**Models (`models.py` +10):** `ProjectFile.__table_args__ = (UniqueConstraint("project_id", "file_path", name="uq_project_files_project_path"),)`. Comment block mandates routing all writes through `services.project_files.upsert_project_file()`.

**Routers:** `routers/chat.py::save_file` and `routers/projects.py::save_project_file` both rewritten to call `upsert_project_file(...)` instead of the check-then-insert pattern.

**Frontend (`app/src/components/views/design/bridgeInstaller.ts`):** added an 8-line scope docblock listing supported project types (Next.js / Vite / CRA / Vue / Svelte / Astro / Angular / plain HTML); install short-circuits on backend-only/native projects so they no longer noisily fail.

**Verified end-to-end on minikube:** pre-migration showed 2 rows for `public/__tesslate-design-bridge.js` in `fire-7tw0qy`; post-rebuild + migrate: 1 row, constraint enforced.

## 8. Compute spec-hash drift detection

**Symptom:** edits to `.tesslate/config.json` (image swap, port change, startup command, env) were silently ignored on warm-start because `_start_environment_inner` scaled 0→1 without re-rendering the manifest from the `Container` model — new args never reached the live Deployment.

**Fix — `orchestrator/app/services/compute_manager.py` (+167):**
- New constant `SPEC_HASH_ANNOTATION = "tesslate.io/spec-hash"`.
- New `compute_dev_container_spec_hash(...)` — SHA-256 truncated to 16 chars over `(startup_command, image, port, working_directory, sorted env)`.
- New `_compute_expected_spec_hashes(...)` mirrors the deploy-loop's exact input shaping (node_modules-fix prefix, sibling `*_URL` / `VITE_*_URL` env injection, registry prefix, `secret_manager_env.build_env_overrides`) so we can predict per-`container_directory` hashes the live cluster *should* have. Service containers excluded.
- New `_detect_spec_drift(...)` lists Deployments matching `_TIER2_DEV_LABEL_SELECTOR`, reads the annotation, compares against expected. Returns `True` on any mismatch (legacy Deployments without the annotation always count as drift, forcing one-time re-apply across upgraded clusters). On exception, returns `True` (safe fallback).
- Wired into `_start_environment_inner`: before warm-start of an `active` namespace, drift check runs; on drift it sets `ns_phase = None` to fall through to cold-render. The cold-render path passes the freshly computed `spec_hash` into `create_v2_dev_deployment(...)`.

**`services/orchestration/kubernetes/helpers.py` (+12):** `create_v2_dev_deployment(...)` gains optional `spec_hash: str | None = None`; when provided, sets `metadata.annotations = {"tesslate.io/spec-hash": spec_hash}`. Pure passthrough — no rendering changes.

## 9. Config sync — `start_all` reads from config

**Symptom:** edits to `.tesslate/config.json` on disk never propagated to the `Container` model unless `POST /api/projects/{id}/setup-config` was explicitly called.

**Fix — new `orchestrator/app/services/config_sync.py` (+79):**
- `ensure_config_synced(db, project, user_id)` reads `.tesslate/config.json` from disk (`get_project_fs_path`) when the project lives on local FS, or via the orchestrator (`orchestrator.read_file`) when it lives in a PVC. Parses through `parse_tesslate_config`, round-trips through `serialize_config_to_json` (so the payload exactly matches `TesslateConfigCreate`'s API-schema field aliases like `from`/`to`), then calls `sync_project_config(...)`.
- Non-blocking: any error (missing file, parse error, sync error) is logged and swallowed. Returns `True` only when a sync ran.
- Called from `start_all_containers`, `start_single_container`, and `_restart_container_background_task` in `routers/projects.py`. Restart path re-loads the `Container` row after the call since `sync_project_config` may have replaced it.

`.tesslate/config.json` is now authoritative without a separate `POST /setup-config`.

## 10. Surgical bug fixes

- **iframe color-scheme flash** (`BrowserPreviewNode`, `IframeAppHost`, `PreviewCanvas`, `project/PreviewPane`): added `style={{ colorScheme: 'normal' }}` to each iframe. When the parent declares `color-scheme: dark`, Chromium paints the iframe's default body white as dark grey before user CSS loads — fixed.
- **Tooltip jitter** (`Tooltip.tsx`): replaced the static `transform: getTransform()` with Framer's `transformTemplate={(_, generated) => `${getTransform()} ${generated}`}` so Framer's animated transform composes with the position transform instead of overwriting it.
- **Dock drag-and-drop regression** (`ToolTabsPanel.tsx`): JSX was overriding `role`/`onMouseDown`/`onClick` *after* spreading `dragHandleProps`, blocking `@hello-pangea/dnd` events. Now we don't override drag-handle props and suppress focus-click during `isDragging || isDropAnimating`.
- **Stale active tab** (`useToolDock.ts`): when restoring persisted dock state, seed `activeTabId` from `restored.tabs[0]?.id` instead of trusting the persisted active id (which could reference a tab that no longer exists, causing a blank dock).
- **Bridge installer scope** (`bridgeInstaller.ts`): new docblock spells out which project types are supported.

## 11. Container selector — project-level status

`ContainerSelector.tsx` (158-line diff): per-container emoji icons (▲, ⚡, ⚛, 🐘…) replaced with a single `Cube` icon. New `environmentStatus` prop renders a status dot on the trigger button driven by the project's environment status (`running | starting | provisioning | agent_active | stopping | files_ready | …`); the dropdown's status row uses the shared `STATUS_MAP`. `EnvironmentStatusBadge` removed from the top bar.

## 12. Seeds + library pages

**`orchestrator/app/seeds/skills.py`:** the **"Simplify"** skill (~52 lines, `roin-orca/skills` repo) is removed from `OPENSOURCE_SKILLS`. Two `github_raw_url` 404 fixes:
- `vercel-react-best-practices/SKILL.md` → `react-best-practices/SKILL.md`
- `remotion-best-practices/SKILL.md` → `remotion/SKILL.md`

`pages/Library.tsx` and the four `library/*Page.tsx` pages get the borderless + theme-token treatment; no behavior changes.

---

## Operational notes

- **Migration `0072` is destructive on duplicates by intent.** Downgrade only drops the constraint; deleted rows are not recoverable. Duplicates were always invariant violations, so this is acceptable.
- **Spec-hash drift on legacy Deployments:** every Deployment without the `tesslate.io/spec-hash` annotation will be cold-rendered on next start. One-time disruption per environment, produces correct config alignment.
- **`ensure_config_synced` may rewrite the `Container` graph mid-request** in start/restart paths. Restart code re-loads after; start paths only use `containers` after the call.
- **Attachment caps (100k chars text / 15 MB image base64) are hard 422s** — frontend should pre-validate to avoid surprises.
- **`borderless` defaults to `False`** on existing themes; only the seeded default light/dark flip on. Custom themes are not changed.

## Submodule

`packages/tesslate-agent`: `4053d4cf` → `1fd65c1c` (one commit, attachment rendering only). The previous parent commit `b39c5b01`'s message mentions "write fence + action-based plans" — that work is already in `4053d4cf` (the merge-base SHA). The only NEW submodule commit on this branch is the attachment fix. Push `wip/attachment-user-turn` (or merge to submodule `main`) before this PR merges or the pinned SHA won't resolve on other machines.

## Test plan

- [ ] Sidebar tree renders correctly with multiple concurrent agents across several projects (per-chat / per-folder / collapsed-sidebar spinner).
- [ ] Sidebar tree click on a project chat opens it inside `/project/{slug}/builder` with the chat preselected (not the standalone `/chat`).
- [ ] Cmd+Shift+G/N/S open GitHub / Notes / Settings as dock tabs (no floating panels).
- [ ] Borderless toggle in `ThemesPage` round-trips (UI → theme JSON → reload, borders gone).
- [ ] Paste-only chat → agent actually responds (end-to-end).
- [ ] Auto-title flips from "Untitled" after the first agent reply (text-only AND paste-only AND empty-LLM-response cases).
- [ ] Edit `.tesslate/config.json` (e.g., port change), hit "Start All" — drift detection re-renders the deployment, new port reaches the live pod.
- [ ] Concurrent design-bridge installs against the same project no longer crash later saves; migration `0072` collapses any pre-existing duplicates.
- [ ] >5 parallel agent runs in one project mux through one SSE stream (devtools should show at most one open EventSource for the project, not N).
- [ ] iframe previews don't flash dark on first paint (verify with a light project preset under a dark parent theme).
- [ ] Dock tab drag-reorder works and persists across reload.

## Side issue spotted, not addressed

`db_event_dispatcher_cron` was piling up `redis.TimeoutError` retries in the logs. Called out in a previous session and deferred. Not related to this branch's work; worth a separate investigation.
