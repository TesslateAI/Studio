# Components - Top Level

Top-level components in `app/src/components/` plus an index of every subdirectory.

## Root-Level Components

| File | Purpose |
|------|---------|
| `components/Layout.tsx` | Generic page shell wrapper with header slot |
| `components/DashboardLayout.tsx` | Authenticated dashboard layout: NavigationSidebar + content outlet + MobileMenu + Walkthrough + IdleWarningBanner + VolumeHealthBanner |
| `components/RouteGuards.tsx` | `PrivateRoute` (redirect to /login) and `PublicOnlyRoute` (redirect to /dashboard) React Router guards. Changes to routes require matching updates in `RouteGuards.test.tsx` |
| `components/AgentMessage.tsx` | Renders a full agent response with ordered `AgentStep`s, markdown, tool-call details, thinking blocks |
| `components/AgentStep.tsx` | Single agent-iteration card: tool name, parameters, result, duration, expandable detail |
| `components/AgentDebugPanel.tsx` | Developer panel for inspecting agent internals (raw messages, context window usage, timing) |
| `components/ToolCallDisplay.tsx` | Visualizes a single tool invocation with syntax-highlighted params, success/failure badge, duration |
| `components/ToolManagement.tsx` | Per-project tool-catalog editor: enable/disable tools, scope, test-invoke |
| `components/toolCallHelpers.ts` | Helper functions to format tool names, extract previews, detect tool categories |
| `components/CodeEditor.tsx` | Monaco editor wrapper with file tree, tab bar, auto-language detection, Design-view integration (`showSidebar`, `externalOpenFile`, `onEditorRef`, `onTabsChange`, `onSelectedFileChange`) |
| `components/Preview.tsx` | Legacy iframe preview used by older routes (superseded by `project/PreviewPane.tsx`) |
| `components/BrowserPreviewNode.tsx` | XYFlow preview node: resizable iframe with mini-browser bar |
| `components/ContainerNode.tsx` | Primary XYFlow service-container node |
| `components/ContainerPropertiesPanel.tsx` | Right-pane container editor (name, image, port, envs, startup command) |
| `components/ContainerSelector.tsx` | Dropdown for selecting one of many containers in a project |
| `components/ContainerLoadingOverlay.tsx` | Full-screen container-startup feedback with pulsing grid spinner, progress bar, terminal logs, error state, `HEALTH_CHECK_TIMEOUT:` agent-assist UX, optional `onAskAgent` hook |
| `components/StartupLogViewer.tsx` | Scrollable terminal-style log viewer with ANSI color parsing (`lib/ansi.tsx`), auto-scroll, copy, clear |
| `components/DeploymentTargetNode.tsx` | XYFlow deployment-target node (Vercel/Netlify/Cloudflare/Amplify) |
| `components/DeploymentsDropdown.tsx` | Quick deployment actions dropdown (deploy, redeploy, view URL, rollback) |
| `components/GraphCanvas.tsx` | XYFlow wrapper with theme-aware controls, background, lock toggle |
| `components/MarketplaceSidebar.tsx` | Drag-drop palette of marketplace items for the architecture canvas |
| `components/ExternalServiceCredentialModal.tsx` | Inline credential-capture modal for external services (e.g. Vercel API token) |
| `components/ServiceConfigForm.tsx` | Reusable form for `.tesslate/config.json` (apps, infrastructure, env vars). Infra catalog: postgres, redis, mysql, mongo, minio |
| `components/PreviewPortPicker.tsx` | Dropdown for switching preview between multiple previewable containers (renders only when >=2 containers) |
| `components/ImageUpload.tsx` | Image-upload dropzone with preview, validation, axios-based upload |
| `components/TeamSwitcher.tsx` | Active-team selector for the NavigationSidebar; create team option |
| `components/TemplateCard.tsx` | Marketplace base-template card (variant used on the Dashboard "Start from template" grid) |
| `components/CommandPalette.tsx` | Cmd+K palette built on `cmdk`. Recent items prefixed with `recent-` to avoid double-highlight |
| `components/KeyboardShortcutsModal.tsx` | "?" help modal listing all shortcuts grouped by context. Uses `createPortal` to escape transform ancestors |
| `components/SEO.tsx` | Declarative SEO component with `title`, `description`, `url`, `image`, `structuredData` props |
| `components/DottedSurface.tsx` | Animated dotted background pattern |
| `components/PulsingGridSpinner.tsx` | Loading spinner component (exports `LoadingSpinner` alias used widely) |
| `components/MiniAsteroids.tsx` | Easter-egg asteroids game (triggered via konami or dev-only route) |
| `components/MobileWarning.tsx` | Banner shown on small viewports explaining desktop-only features |
| `components/DiscordSupport.tsx` | Floating Discord support link |
| `components/Walkthrough.tsx` | Onboarding tour with step highlights |
| `components/IdleWarningBanner.tsx` | Shown before auto-hibernate when the active compute pod is idle |
| `components/VolumeHealthBanner.tsx` | Shown when the active project's volume cache node is unhealthy or syncing |
| `components/NoComputePlaceholder.tsx` | Empty state when `ComputeTier === 'none'` – explains upgrade path |

## Subdirectory Index

| Directory | Focus | Doc |
|-----------|-------|-----|
| `admin/` | Superuser platform admin | `docs/app/components/admin/CLAUDE.md` |
| `apps/` | Tesslate Apps UI | `docs/app/components/apps/CLAUDE.md` |
| `billing/` | Subscriptions, credits, upgrade | `docs/app/components/billing/CLAUDE.md` |
| `canvas/` | Hosted agent nodes (Apps canvas) | `docs/app/components/canvas/CLAUDE.md` |
| `cards/` | Reusable card primitives | `docs/app/components/cards/CLAUDE.md` |
| `chat/` | AI chat interface | `docs/app/components/chat/CLAUDE.md` |
| `connectors/` | MCP OAuth UI | `docs/app/components/connectors/CLAUDE.md` |
| `desktop/` | Tauri shell chrome | `docs/app/components/desktop/CLAUDE.md` |
| `edges/` | XYFlow custom edges | `docs/app/components/edges/CLAUDE.md` |
| `git/` | Git history viewer | `docs/app/components/git/CLAUDE.md` |
| `marketplace/` | Marketplace item cards | `docs/app/components/marketplace/CLAUDE.md` |
| `modals/` | Dialog modals | `docs/app/components/modals/CLAUDE.md` |
| `panels/` | Project-builder panels | `docs/app/components/panels/CLAUDE.md` |
| `project/` | Project builder composition (PreviewPane, ToolTabsPanel) | `docs/app/components/project/CLAUDE.md` |
| `settings/` | Settings primitives | `docs/app/components/settings.md` |
| `ui/` | Shared UI primitives | `docs/app/components/ui/CLAUDE.md` |
| `views/` | Full-canvas views (Design, Architecture) + design subsystem | `docs/app/components/views/CLAUDE.md` |

## Conventions

1. **TypeScript-first**: every component has a typed props interface.
2. **Hooks composition**: prefer custom hooks (`useCancellableRequest`, `useContainerStartup`) over raw effects.
3. **Memoization**: XYFlow nodes/edges and high-frequency chat components use `memo` with `arePropsEqual`.
4. **Theme variables**: use `var(--surface)`, `var(--text)`, etc. not raw Tailwind colors.
5. **Portal pattern**: tooltips, dropdowns, modals inside framer-motion parents must use `createPortal` to escape transform containing blocks.
6. **Route updates**: any new route in `App.tsx` must be added to `ROUTE_CONFIG` in `RouteGuards.test.tsx` and wrapped in the right guard.

## Related Docs

- `docs/app/CLAUDE.md` – frontend overview
- `docs/app/pages/CLAUDE.md` – pages that compose these components
