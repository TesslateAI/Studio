# Project Composition Components

Components that structure the project builder page in `app/src/components/project/`.

## File Index

| File | Purpose |
|------|---------|
| `project/PreviewPane.tsx` | Browser-preview wrapper with navigation controls: back/forward, refresh, mobile/desktop toggle, lock URL, close. Hosts the iframe + `PreviewPortPicker` for multi-container projects. Forwards ref so parent can reload the iframe |
| `project/ToolTabsPanel.tsx` | Bottom tool-dock with tabs (Code, Design, Preview, Architecture, Terminal, Kanban, Assets, Settings). Tracks ephemeral vs pinned tabs; close button per tab. Icons from `@phosphor-icons/react` |

## Related Docs

- `docs/app/pages/project-builder.md` – how these compose with views and panels
- `docs/app/components/panels/CLAUDE.md` – right-side floating panels
- `docs/app/components/views/CLAUDE.md` – DesignView and ArchitectureView used within tool tabs
