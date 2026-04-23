# Panels - Project Builder Floating Panels

Modular panels used in the project builder and tool dock, in `app/src/components/panels/`. Each panel is self-contained and mounts inside a `FloatingPanel` or tool-dock tab.

## File Index

| File | Purpose |
|------|---------|
| `panels/index.ts` | Barrel export |
| `panels/GitHubPanel.tsx` | Git status + actions: branch, stage, commit, push, pull, fetch, link-to-GitHub. Shows uncommitted changes count |
| `panels/AssetsPanel.tsx` | Assets browser: grid/list views, search, upload (drag-drop via `AssetUploadZone`), folder navigation via `DirectoryTree`, per-asset actions (copy URL, rename, delete) |
| `panels/KanbanPanel.tsx` | Task board: columns, drag-reorder cards, create via `+`, inline edit, due date, assignee, labels, comments. Integrates with agent via the kanban tool |
| `panels/NotesPanel.tsx` | TipTap-based rich-text editor for project notes. Extensions: StarterKit, Placeholder, Underline, TextAlign, Link. Note: CSS selector must use `.tiptap-editor.ProseMirror` (same element, not descendant) |
| `panels/DeploymentsPanel.tsx` | Deployment history: status, provider, live URL, logs, retry/cancel. Polls status until terminal |
| `panels/SettingsPanel.tsx` | Project settings: name, visibility, sync toggle, chat position, runtime info, provider credentials, delete project |
| `panels/TerminalPanel.tsx` | xterm.js terminal connecting via `createTerminalWebSocket(target)`. Addons: fit, weblinks, search. Theme-aware colors |
| `panels/MarketplacePanel.tsx` | In-project marketplace browser (lock toggle prevents accidental installs while drag-dropping) |
| `panels/TimelinePanel.tsx` | Project snapshot timeline: list snapshots, save-now, restore, delete. Shows sync status per snapshot |
| `panels/NodeConfigPanel.tsx` | Agent-driven config form for a single container. Renders `FormSchema` from `nodeConfigApi` with per-field validation, password fields, sensitive env var masking (Eye/EyeSlash), info/warning callouts |

## Assets Sub-components (`panels/assets/`)

| File | Purpose |
|------|---------|
| `assets/AssetComponents.tsx` | `AssetCard` renderer with MIME-type icon, badge, copy URL, rename, delete, folder-open actions |
| `assets/AssetUploadZone.tsx` | Drag-drop dropzone with file validation (`validateFile` from `types/assets.ts`), progress, preview |
| `assets/DirectoryTree.tsx` | Tree view of asset folders with create-folder inline input, expand/collapse |

## Panel Communication

Panels receive `projectSlug` (sometimes `projectId`) plus feature-specific props. For events that affect the canvas (e.g. container added from Marketplace), panels emit via `connectionEvents` / `nodeConfigEvents` buses and ArchitectureView subscribes.

## Related Docs

- `docs/app/components/project/CLAUDE.md` – ToolTabsPanel that hosts these in the dock
- `docs/app/components/views/CLAUDE.md` – views that work alongside panels
- `docs/app/utils/CLAUDE.md` – `nodeConfigEvents` wiring
