# Architecture Canvas

XYFlow-based architecture visualization in `app/src/components/`. Consists of `ArchitectureView` plus custom nodes, edges (`edges/`), and apps extensions (`canvas/`).

## Core Files

| File | Purpose |
|------|---------|
| `components/views/ArchitectureView.tsx` | Top-level view. Loads containers + connections, wires nodeTypes/edgeTypes, handles start/stop/drag/drop, mounts `MarketplaceSidebar`, `ContainerPropertiesPanel`, `ExternalServiceCredentialModal`, `NodeConfigPanel` |
| `components/GraphCanvas.tsx` | XYFlow wrapper with controls (zoom, fit, lock), background pattern, theme-aware styling, keyboard shortcuts, auto-pan toggle |
| `components/ContainerNode.tsx` | Primary node: service name, image, status dot (running/stopped/starting/error), port, envs count, edit/start/stop actions. Handles on all four sides for flexible connection |
| `components/BrowserPreviewNode.tsx` | Resizable iframe preview node. Embeds a mini browser bar (back/forward/refresh), drag-to-resize handles, "open in tab" button. Shows placeholder when no container connected |
| `components/DeploymentTargetNode.tsx` | Deployment target card: provider (Vercel/Netlify/Cloudflare/Amplify), environment, status (pending/success/failure), credential picker, retry button, live URL link |
| `components/ContainerPropertiesPanel.tsx` | Right-side panel that opens when a container node is selected. Edits name, image, port, env vars, startup command; persists via `projectsApi.updateContainer` |
| `components/ContainerSelector.tsx` | Dropdown for picking a container when multiple exist (used inside modals and `PreviewPortPicker`) |
| `components/MarketplaceSidebar.tsx` | Drag-drop palette of marketplace items (containers, agents, skills, MCP). Drags create new nodes via React Flow's `setData('application/reactflow', ...)` |
| `components/ExternalServiceCredentialModal.tsx` | Paired with `DeploymentTargetNode` to supply missing API keys (Vercel token, etc.) |

## Edges (`components/edges/`)

See `docs/app/components/edges/CLAUDE.md`. Types: `http_api`, `database`, `cache`, `env_injection`, `browserPreview`, `deployment`.

## Apps Canvas Extensions (`components/canvas/`)

See `docs/app/components/canvas/CLAUDE.md`. Adds `HostedAgentNode`, `HostedAgentInspector`, `AgentInvokesEdge`.

## Node Type Registration

```tsx
const nodeTypes: NodeTypes = {
  containerNode: ContainerNode,
  browserPreview: BrowserPreviewNode,
  deploymentTarget: DeploymentTargetNode,
  hostedAgentNode: HostedAgentNode,
};
```

## Auto-Layout

`getLayoutedElements(nodes, edges, { direction: 'LR' })` from `utils/autoLayout.ts` applies Dagre layout. Called on initial load and on the "Auto Layout" button. Handles different node sizes (container 180x100, browser preview 320x280).

## Connection Rules

- Containers can connect to containers (http_api / database / cache), to browser previews, and to deployment targets.
- Browser preview nodes accept at most one incoming connection (enforced in `isValidConnection`).
- Deployment targets accept only static-site and server containers.
- Hosted agent nodes use `agent_invokes` edges to reach services.

## Memoization

All node/edge components use `memo` with custom `arePropsEqual` to avoid re-rendering all nodes on a single node update. `nodeTypes` and `edgeTypes` must be memoized at the parent (`useMemo`) or XYFlow will warn about unstable references.

## Related Docs

- `docs/app/components/edges/CLAUDE.md` – edge styles and types
- `docs/app/components/canvas/CLAUDE.md` – hosted agent nodes (Apps)
- `docs/app/utils/CLAUDE.md` – `autoLayout`, `connectionEvents`
- `docs/app/pages/project-graph.md` – full architecture page deep dive
