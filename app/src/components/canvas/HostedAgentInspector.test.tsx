/**
 * HostedAgentInspector — field change calls onUpdate with the patched spec.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { HostedAgentInspector } from './HostedAgentInspector';

describe('HostedAgentInspector', () => {
  it('calls onUpdate when model_pref changes', () => {
    const onUpdate = vi.fn();
    render(
      <HostedAgentInspector
        spec={{ id: 'agent-a', model_pref: 'claude-opus' }}
        onUpdate={onUpdate}
      />
    );

    const input = screen.getByTestId('field-model-pref') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'claude-sonnet' } });

    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'agent-a', model_pref: 'claude-sonnet' })
    );
  });

  it('parses comma-separated tools_ref into an array', () => {
    const onUpdate = vi.fn();
    render(
      <HostedAgentInspector spec={{ id: 'a' }} onUpdate={onUpdate} />
    );

    fireEvent.change(screen.getByTestId('field-tools-ref'), {
      target: { value: 'fetch, search, bash' },
    });

    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ tools_ref: ['fetch', 'search', 'bash'] })
    );
  });

  it('parses warm_pool_size as number', () => {
    const onUpdate = vi.fn();
    render(<HostedAgentInspector spec={{ id: 'a' }} onUpdate={onUpdate} />);

    fireEvent.change(screen.getByTestId('field-warm-pool-size'), {
      target: { value: '3' },
    });

    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ warm_pool_size: 3 })
    );
  });
});
