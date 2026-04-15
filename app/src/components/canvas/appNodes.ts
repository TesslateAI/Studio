/**
 * Barrel module for Tesslate Apps canvas extensions. Consumers (notably
 * ArchitectureView) can spread these maps into the existing XYFlow
 * `nodeTypes` / `edgeTypes` dicts so the renderer picks up hosted-agent
 * nodes and agent_invokes edges without further wiring.
 *
 * Example integration in ArchitectureView.tsx:
 *
 *   import { appsCanvasNodeTypes, appsCanvasEdgeTypes } from '../canvas/appNodes';
 *   const nodeTypes: NodeTypes = { ...base, ...appsCanvasNodeTypes };
 *   const edgeTypes = { ...base, ...appsCanvasEdgeTypes };
 */
import { HostedAgentNode } from './HostedAgentNode';
import { AgentInvokesEdge } from './AgentInvokesEdge';

export const appsCanvasNodeTypes = {
  hostedAgentNode: HostedAgentNode,
} as const;

export const appsCanvasEdgeTypes = {
  agent_invokes: AgentInvokesEdge,
} as const;

export { HostedAgentNode } from './HostedAgentNode';
export { AgentInvokesEdge } from './AgentInvokesEdge';
export { HostedAgentInspector } from './HostedAgentInspector';
export type { HostedAgentNodeData, HostedAgentNodeType } from './HostedAgentNode';
export type { HostedAgentInspectorProps } from './HostedAgentInspector';
