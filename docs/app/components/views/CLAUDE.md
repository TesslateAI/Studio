# Views - Design and Architecture

Top-level view components in `app/src/components/views/`. A "view" is a full-canvas mode the project builder switches into. Each view is self-contained and mounts/unmounts as the user navigates.

## File Index

| File | Purpose |
|------|---------|
| `views/ArchitectureView.tsx` | XYFlow-based architecture canvas: container nodes, connection edges, deployment targets, hosted agents. Orchestrates start/stop, drag-drop from `MarketplaceSidebar`, `ContainerPropertiesPanel`, credential modal |
| `views/DesignView.tsx` | Design engineer mode: resizable 3-panel layout (file tree, preview canvas + iframe bridge, inspector). Manages bridge install, undo/redo hotkeys, element selection, text-edit mode |

## Design Engineer Subsystem (`views/design/`)

The design engineer is a visual editor that inspects and mutates a running preview iframe via a script the orchestrator injects into the user's project (`__tesslate-design-bridge.js`). It mirrors Onlook's architecture to sidestep cross-origin iframe restrictions.

| File | Purpose |
|------|---------|
| `design/DesignBridge.ts` | `BRIDGE_SCRIPT_CONTENT` IIFE that runs inside the user's iframe. Defines `ElementData`, parent<->iframe message types (`design:inspect`, `design:update-style`, `design:insert-element`, `design:highlight`, `design:set-mode`, etc.), and `sendDesignMessage(iframe, msg)` helper |
| `design/bridgeInstaller.ts` | Writes `__tesslate-design-bridge.js` to the project's public dir and injects `<script data-tesslate-design src="...">` into the HTML entry point. Auto-detects Next.js/Vite/CRA/Vue/Svelte/Angular/Astro from the file tree |
| `design/designStore.ts` | Vanilla subscribe/notify store consumed via `useSyncExternalStore`. Holds design index (oid -> source metadata), pending CodeDiffRequests, undo/redo stack with 500ms style-edit coalescing, multi-select set. Exposes `pushStyleEdit`, `pushClassEdit`, `pushTextEdit`, `undo`, `redo`, `selectElement`, `clearSelection`, `deleteSelected`, `copySelection`, `pasteClipboard`, `groupSelected`, `askAIAboutElement` |
| `design/canvasStore.ts` | Pan/zoom state store mirroring Onlook's `CanvasManager` + `SnapManager`. Clamps scale (0.1-3) and position (±10000), pointer-anchored zoom, per-slug localStorage persistence (300ms debounce), snap-line registry, `adaptRectToCanvas` helper |
| `design/CanvasViewport.tsx` | Pan/zoom container wrapping the iframe. Ctrl/Cmd+wheel = pointer-anchored zoom, space+drag / middle-button drag = pan. Hosts `SnapOverlay` as non-interactive visual layer |
| `design/SnapOverlay.tsx` | SVG snap guidelines in world coordinates, transformed by the canvas matrix so they track the iframe under zoom/pan |
| `design/PreviewCanvas.tsx` | Iframe wrapper with bridge status indicator (`not-installed` / `connecting` / `ready` / `unavailable`). Dispatches messages to bridge and surfaces `ElementData` upward. Uses a fit size of 1440x900 and lets the canvas transform handle visual fit |
| `design/DesignToolbar.tsx` | Top toolbar: breakpoint switcher (fit/sm/md/lg/xl/2xl/mobile=375px), design mode pills (select/text/move), undo/redo, refresh, insert palette trigger |
| `design/InsertPalette.tsx` | Cmd palette for inserting elements. Detects framework (nextjs/vite/vue/nuxt/svelte/sveltekit/angular/astro/html) from file tree, offers pre-made snippet library grouped by category (layout, typography, forms, media, lists) |
| `design/InspectorPanel.tsx` | Right sidebar with VISUAL / INSPECTOR tabs. Visual = cursor-position Tailwind class editing. Inspector = full CSS property grid for selected element. Hosts `askAIAboutElement` button |
| `design/VisualTab.tsx` | Tailwind class editor – detects cursor classes via `classDetection.ts`, categorizes them, offers autocomplete from `COMMON_TAILWIND_CLASSES`, applies via `cn/clsx/twMerge`-aware edits |
| `design/InspectorTab.tsx` | CSS property grid with smart dropdowns (`CSS_VALUE_OPTIONS` for display/position/overflow/etc.), computed-value display, source-file jump-to-line |
| `design/FileTreePanel.tsx` | Left-sidebar file tree with create/rename/delete context menu, inline input for new files/folders, search filter. Uses `buildFileTree`/`filterFileTree` from `utils/` |

## Bridge Protocol Messages

**Parent -> iframe** (`DesignParentMessage`): `activate`, `deactivate`, `inspect`, `update-style`, `remove-style`, `update-classes`, `insert-element`, `highlight`, `clear-highlight`, `set-mode`, `start-text-edit`, `stop-text-edit`.

**Iframe -> parent** (`DesignBridgeMessage`): `bridge-ready`, `element-data`, `hover-data`, `style-applied`, `element-inserted`, `text-changed`, `element-moved`, `source-location`.

## Data Flow

1. User opens Design view -> `bridgeInstaller.installBridge(fileTree)` writes the IIFE to `public/__tesslate-design-bridge.js` and injects the `<script>` tag.
2. Iframe loads, bridge posts `bridge-ready`.
3. `rebuildDesignIndex(slug)` fetches `GET /design/index` which contains `oid -> { file, line, component }` entries (from backend source-map crawl).
4. User hovers/clicks -> bridge posts `element-data` with `ElementData.oid` matched against the index.
5. User edits a style -> `pushStyleEdit(oid, patch, inverse)` appends to history, debounces a `CodeDiffRequest` batch, flushes to `POST /design/apply-diff`.
6. Backend rewrites the source file; hot reload repaints the iframe; bridge re-sends `element-data` for the re-mounted element.
7. Undo/redo replays inverse patches via the same pipeline.

## Related Docs

- `docs/app/utils/CLAUDE.md` – `buildFileTree`, `classDetection`
- `docs/app/components/graph/CLAUDE.md` – ArchitectureView deep dive
- `docs/app/api/CLAUDE.md` – `designApi.getIndex`, `designApi.applyDiff`
