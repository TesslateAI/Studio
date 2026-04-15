/**
 * HostedAgentNode — renders with provided data props.
 */
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ReactFlowProvider } from '@xyflow/react';
import { HostedAgentNode, type HostedAgentNodeData } from './HostedAgentNode';

function renderNode(data: HostedAgentNodeData) {
  // XYFlow NodeProps includes many fields the component does not read; we
  // stub the minimum that TS requires via `as unknown` for test purposes.
  const props = {
    id: 'n1',
    type: 'hostedAgentNode',
    data,
    selected: false,
    dragging: false,
    isConnectable: true,
    xPos: 0,
    yPos: 0,
    zIndex: 0,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
    width: 200,
    height: 80,
    sourcePosition: 'right',
    targetPosition: 'left',
  } as unknown as Parameters<typeof HostedAgentNode>[0];

  return render(
    <ReactFlowProvider>
      <HostedAgentNode {...props} />
    </ReactFlowProvider>
  );
}

describe('HostedAgentNode', () => {
  it('renders id, model_pref, and count badges', () => {
    renderNode({
      id: 'researcher',
      model_pref: 'claude-opus',
      tools_ref: ['fetch', 'search'],
      mcps_ref: ['github'],
      warm_pool_size: 2,
    });

    expect(screen.getByText('researcher')).toBeInTheDocument();
    expect(screen.getByText('claude-opus')).toBeInTheDocument();
    expect(screen.getByTestId('warm-pool-badge')).toHaveTextContent('warm 2');
    expect(screen.getByTestId('tools-badge')).toHaveTextContent('2 tools');
    expect(screen.getByTestId('mcps-badge')).toHaveTextContent('1 mcp');
  });

  it('handles missing optional fields', () => {
    renderNode({ id: 'agent-x' });
    expect(screen.getByText('agent-x')).toBeInTheDocument();
    expect(screen.getByText('no model')).toBeInTheDocument();
    expect(screen.getByTestId('warm-pool-badge')).toHaveTextContent('warm 0');
    expect(screen.getByTestId('tools-badge')).toHaveTextContent('0 tools');
  });
});
