# What I Was Doing

Snapshot written 2026-04-24 so I can pick this back up. Safe to delete after resuming.

Branch: `wip/sidebar-tree-and-attachment-fix` (forked from `chore/gitignore-env-files`).
Submodule `packages/tesslate-agent` is on `wip/attachment-user-turn`.

## Three stacked work streams on this branch

Originally a gitignore tweak (`*.env` + `!*.env.example`), but two real features piled on top before it got committed.

### 1. Attachment pipeline fix — agent was silently dropping pastes

**Symptom:** paste a big block of text into chat, agent replies "Task completed" without doing anything.

**Root cause:** attachments flowed UI → API → DB → `AgentTaskPayload` → worker → agent context just fine, then got dropped at `packages/tesslate-agent/src/tesslate_agent/agent/tesslate_agent.py` because the agent loop never read `context["attachments"]`.

**Fix (in the submodule):**
- New `_build_user_turn` helper inlines `pasted_text` / `file_reference` as labeled text blocks and renders `image` attachments as OpenAI vision content-parts.
- 4 new pytest cases in `tests/agent/test_tesslate_agent.py`.

**Fix (in the orchestrator):**
- `ChatAttachmentSchema` now has size caps as `ClassVar`s + a `model_validator`:
  - `MAX_PASTED_TEXT_CHARS = 100_000`
  - `MAX_IMAGE_BASE64_CHARS = 20_000_000` (~15 MB raw)
- Rejected at the API boundary so nothing oversized hits Redis/DB.

### 2. Sidebar folder tree — "Projects ARE folders"

Replaces the old "Recent" list in the left sidebar with a two-level tree: root-level chats + project folders that expand to show their chats. Design decision was **Option C: projects = folders**, zero schema migration (since `Chat.project_id` is already nullable).

**New files:**
- `orchestrator/app/routers/sidebar.py` — `GET /api/sidebar/tree` returns `{rootChats, projects:[{..., chats}]}` in one call. Uses SQL window functions for Postgres + SQLite 3.25+ compatibility. Visibility matches the existing projects endpoint (team membership, admin vs member, excludes app-instance projects). Limits: 30 projects, 50 root chats, 20 chats/project.
- `app/src/components/ui/SidebarTree.tsx` — collapsible project folders, expand state persisted to `localStorage` under `sidebarTree.expandedProjects`. `+` button opens `CreateProjectModal`. Polls every 4s, pauses when tab hidden.

**Modified:**
- `app/src/components/ui/NavigationSidebar.tsx` — dropped ~200 lines of the old Recent section, renders `<SidebarTree/>` instead.
- `app/src/lib/api.ts` — added `sidebarApi.getTree()`.
- `orchestrator/app/main.py` — registered the sidebar router (prefix on the router itself, `/api/sidebar`).

**Concurrent-agent spinners:** running chats render a `Loader2` spinner + bold title; project folders with active children show a spinner + count badge; when the sidebar is collapsed, a tiny spinner overlays the folder icon.

### 3. Auto-title fix — chats were stuck "Untitled" forever

**Symptom:** especially when the user only pasted content with no typed text, `_auto_title_chat` leaned entirely on the LLM and silently fell through on empty results.

**Fix in `orchestrator/app/worker.py` (+147 lines):**
- Fork-session title generation after the first agent reply (not before).
- Attachment-aware seed (so pure-paste chats still get a meaningful title).
- Truncation fallback when the LLM returns nothing.
- Added observability logs.

## What's verified vs not

Verified via unit tests in the submodule (the 4 new pytest cases for attachment rendering).

**Not verified end-to-end on minikube yet** — the last session ended with "tell me what you see, I'll iterate on rough edges" and then wrapped. So before merging:

- [ ] Paste-only chat → agent actually responds (end-to-end).
- [ ] Sidebar tree renders correctly with multiple concurrent agents across several projects.
- [ ] Auto-title flips from "Untitled" after the first agent reply (both text-only and paste-only cases).
- [ ] Confirm `packages/tesslate-agent` submodule bump lands cleanly — it's on `wip/attachment-user-turn` locally; push that branch (or merge into `main` of the submodule repo) before this PR merges, or the pinned SHA won't resolve on other machines.

## Side issue spotted, not addressed

`db_event_dispatcher_cron` was piling up `redis.TimeoutError` retries in the logs. Called out in a previous session and deferred. Not related to this branch's work, but worth a separate investigation.

## Files at a glance

| File | Status | Purpose |
|------|--------|---------|
| `.gitignore` | M | `*.env` + `!*.env.example` (originating branch change) |
| `orchestrator/app/main.py` | M | Register sidebar router |
| `orchestrator/app/schemas.py` | M | `ChatAttachmentSchema` size caps |
| `orchestrator/app/worker.py` | M | Auto-title fork-session rewrite |
| `orchestrator/app/routers/sidebar.py` | A | `GET /api/sidebar/tree` |
| `app/src/components/ui/NavigationSidebar.tsx` | M | Swap Recent → `<SidebarTree/>` |
| `app/src/components/ui/SidebarTree.tsx` | A | Two-level collapsible tree |
| `app/src/lib/api.ts` | M | `sidebarApi.getTree()` |
| `packages/tesslate-agent` | M | Submodule bump: `_build_user_turn` + tests + docs |
