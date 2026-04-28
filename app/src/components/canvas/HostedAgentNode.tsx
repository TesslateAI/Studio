/**
 * HostedAgentNode — XYFlow custom node for a hosted agent on the architecture
 * canvas. Rounded card with the agent id, model preference, warm-pool size,
 * tools count, and MCPs count.
 *
 * Registered via appsCanvasNodeTypes in ./appNodes.ts — see report for the
 * one-line integration in ArchitectureView.tsx.
 */
import { memo } from 'react';
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';

export interface HostedAgentNodeData extends Record<string, unknown> {
  id: string;
  system_prompt_ref?: string;
  model_pref?: string;
  tools_ref?: string[];
  mcps_ref?: string[];
  temperature?: number;
  max_tokens?: number;
  thinking_effort?: string;
  warm_pool_size?: number;
  // Phase 5 — Publish-as-App canvas annotations.
  // When ``expose_as_action`` is true the inspector auto-fills handler.kind
  // = ``hosted_agent`` and prefills ``billing.ai_compute.payer_default`` =
  // ``installer`` for the manifest emitted by the Publish Drawer.
  expose_as_action?: boolean;
  action_input_schema?: string;
  action_output_schema?: string;
}

export type HostedAgentNodeType = Node<HostedAgentNodeData, 'hostedAgentNode'>;

function HostedAgentNodeComponent({ data, selected }: NodeProps<HostedAgentNodeType>) {
  const toolCount = data.tools_ref?.length ?? 0;
  const mcpCount = data.mcps_ref?.length ?? 0;
  const warmPool = data.warm_pool_size ?? 0;

  return (
    <div
      data-testid="hosted-agent-node"
      className={`rounded-xl border bg-[var(--surface)] shadow-sm min-w-[200px] px-3 py-2 transition-colors ${
        selected
          ? 'border-[var(--primary)] ring-1 ring-[var(--primary)]/30'
          : 'border-[var(--border)]'
      }`}
    >
      <Handle type="target" position={Position.Left} />
      <div className="flex items-center gap-2">
        <div
          aria-hidden
          className="w-6 h-6 rounded-md bg-gradient-to-br from-purple-500 to-indigo-500 flex items-center justify-center text-white text-xs font-bold"
        >
          A
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-[var(--text)] truncate">
            {data.id}
          </div>
          <div className="text-[10px] text-[var(--text-muted)] truncate">
            {data.model_pref ?? 'no model'}
          </div>
        </div>
      </div>

      <div className="flex gap-1.5 mt-2 text-[10px]">
        <Badge label={`warm ${warmPool}`} tone="slate" testId="warm-pool-badge" />
        <Badge
          label={`${toolCount} tool${toolCount === 1 ? '' : 's'}`}
          tone="blue"
          testId="tools-badge"
        />
        <Badge
          label={`${mcpCount} mcp${mcpCount === 1 ? '' : 's'}`}
          tone="purple"
          testId="mcps-badge"
        />
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function Badge({
  label,
  tone,
  testId,
}: {
  label: string;
  tone: 'slate' | 'blue' | 'purple';
  testId?: string;
}) {
  const map = {
    slate: 'bg-slate-500/20 text-slate-300',
    blue: 'bg-blue-500/20 text-blue-300',
    purple: 'bg-purple-500/20 text-purple-300',
  } as const;
  return (
    <span
      data-testid={testId}
      className={`px-1.5 py-0.5 rounded font-medium ${map[tone]}`}
    >
      {label}
    </span>
  );
}

export const HostedAgentNode = memo(HostedAgentNodeComponent);
HostedAgentNode.displayName = 'HostedAgentNode';
