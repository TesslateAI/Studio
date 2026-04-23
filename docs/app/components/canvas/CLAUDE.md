# Canvas - Hosted Agent Nodes

Tesslate Apps extensions to the architecture canvas in `app/src/components/canvas/`. These nodes/edges are merged into the main `ArchitectureView` via `appsCanvasNodeTypes` / `appsCanvasEdgeTypes`.

## File Index

| File | Purpose |
|------|---------|
| `canvas/HostedAgentNode.tsx` | XYFlow custom node for a hosted agent. Shows id, system_prompt_ref, model_pref, temperature, max_tokens, thinking_effort, warm_pool_size, tool count, MCP count. Left/right handles so it wires into other nodes |
| `canvas/HostedAgentInspector.tsx` | Right-pane inspector for a selected `HostedAgentNode`. Edits id / model / temperature / max_tokens / thinking_effort (none/low/medium/high) / warm_pool_size / tools[] / mcps[]. Debounces via `onUpdate` so the caller can persist to `.tesslate/config.json` |
| `canvas/AgentInvokesEdge.tsx` | XYFlow custom edge: dashed purple line labeled "invokes" for agent -> target invocation links. Visually distinct from solid HTTP API edges |
| `canvas/appNodes.ts` | Barrel export: `appsCanvasNodeTypes = { hostedAgentNode: HostedAgentNode }`, `appsCanvasEdgeTypes = { agent_invokes: AgentInvokesEdge }`. Import and spread into ArchitectureView's node/edge maps |

## Integration Example

```tsx
// In ArchitectureView.tsx
import { appsCanvasNodeTypes, appsCanvasEdgeTypes } from '../canvas/appNodes';

const nodeTypes: NodeTypes = {
  containerNode: ContainerNode,
  browserPreview: BrowserPreviewNode,
  deploymentTarget: DeploymentTargetNode,
  ...appsCanvasNodeTypes,
};
const edgeTypes = {
  http_api: HttpApiEdge,
  database: DatabaseEdge,
  cache: CacheEdge,
  env_injection: EnvInjectionEdge,
  browserPreview: BrowserPreviewEdge,
  ...appsCanvasEdgeTypes,
};
```

## Data Shape

`HostedAgentNodeData`:

```ts
interface HostedAgentNodeData {
  id: string;
  system_prompt_ref?: string;
  model_pref?: string;
  tools_ref?: string[];
  mcps_ref?: string[];
  temperature?: number;
  max_tokens?: number;
  thinking_effort?: 'none' | 'low' | 'medium' | 'high';
  warm_pool_size?: number;
}
```

## Related Docs

- `docs/app/components/graph/CLAUDE.md` – base architecture canvas
- `docs/app/components/edges/CLAUDE.md` – standard edge types
- `docs/apps/CLAUDE.md` – Tesslate Apps backend contract
