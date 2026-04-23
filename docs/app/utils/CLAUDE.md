# Utils

Pure helper modules in `app/src/utils/`. None of these hold React state.

## File Index

| File | Purpose |
|------|---------|
| `utils/autoLayout.ts` | `getLayoutedElements(nodes, edges, { direction, nodeSep, rankSep })` applies Dagre layout; handles differently-sized node types (container 180x100, browser preview 320x280); converts Dagre center positions to React Flow top-left |
| `utils/buildFileTree.ts` | `buildFileTree(files)` converts flat file list to nested `FileNode` tree; `filterFileTree(tree, query)` filters by path substring; `FileTreeEntry` type consumed by Design view's `detectEntryFile` and `InsertPalette` |
| `utils/classDetection.ts` | Monaco cursor -> CSS className detection for Design VISUAL tab; `detectClassesAtCursor` supports `className="..."`, `class="..."`, `className={\`...\`}`, `cn(...)`, `clsx(...)`, `twMerge(...)`; `categorizeTailwindClass` and `getActiveCategories` bucket classes by layout/spacing/color/typography/etc. |
| `utils/connectionEvents.ts` | `ConnectionEventBus` singleton for `connection-created` / `connection-deleted` events between XYFlow and container panels |
| `utils/fileEvents.ts` | `fileEvents.emit('fileUpdated', { filePath, content })` / `fileEvents.on(...)` / `fileEvents.off(...)`; cross-component notification for file saves |
| `utils/nodeConfigEvents.ts` | Event bus for agent-driven node-config events (`OpenConfigTabRequest`, `UserInputRequiredEvent`, `NodeConfigCancelledEvent`, `NodeConfigResumedEvent`); decouples `useAgentChat` from dock UI |

## Usage Notes

- **`autoLayout`**: Call after loading containers/connections from backend. Layout is idempotent – safe to re-run when edges change.
- **`buildFileTree`**: File paths use forward slashes regardless of OS. Handles root files, nested directories, and multiple levels.
- **`classDetection`**: Only works on lines that explicitly set `class` or `className`. For Tailwind autocomplete, combine with `COMMON_TAILWIND_CLASSES` in `VisualTab.tsx`.
- **`fileEvents` / `connectionEvents` / `nodeConfigEvents`**: Always clean up listeners in `useEffect` return to avoid stale refs.

## Related Docs

- `docs/app/components/views/CLAUDE.md` – Design view consumes `buildFileTree` and `classDetection`
- `docs/app/components/graph/CLAUDE.md` – Architecture view consumes `autoLayout` and `connectionEvents`
- `docs/app/pages/project-builder.md` – project page wires `nodeConfigEvents` to the tool dock
