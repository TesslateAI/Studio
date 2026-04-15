import { render, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../../config', () => ({ config: { API_URL: 'http://test' } }));

vi.mock('../../lib/api', () => ({
  appRuntimeApi: {
    createInvocation: vi.fn(),
    deleteInvocation: vi.fn(),
    deleteSession: vi.fn(),
  },
  appBillingApi: {
    getSpendSummary: vi.fn(async () => ({
      total_usd_30d: 1,
      total_usd_7d: 0,
      total_usd_24h: 0,
      total_settled_usd: 0,
      total_unsettled_usd: 0,
      per_dimension: {},
      per_app: [],
    })),
  },
}));

import IframeAppHost from './IframeAppHost';

describe('IframeAppHost', () => {
  it('drops messages from the wrong origin and dispatches correct-origin events', async () => {
    const onEvent = vi.fn();
    render(
      <IframeAppHost
        entrypoint="https://app.example.com/"
        appInstanceId="i1"
        sessionId="sess1"
        apiKey="secret"
        onEvent={onEvent}
      />
    );

    // Wrong-origin message: should be dropped.
    window.dispatchEvent(
      new MessageEvent('message', {
        data: { v: 1, kind: 'event', id: 'bad', topic: 'hello', payload: {} },
        origin: 'https://evil.com',
      })
    );

    // Correct-origin event message: should be dispatched to onEvent.
    window.dispatchEvent(
      new MessageEvent('message', {
        data: { v: 1, kind: 'event', id: 'good', topic: 'hello', payload: { a: 1 } },
        origin: 'https://app.example.com',
      })
    );

    await waitFor(() => expect(onEvent).toHaveBeenCalledTimes(1));
    const call = onEvent.mock.calls[0][0] as { id: string; topic: string };
    expect(call.id).toBe('good');
    expect(call.topic).toBe('hello');
  });

  it('ignores non-envelope messages even from the correct origin', async () => {
    const onEvent = vi.fn();
    render(
      <IframeAppHost
        entrypoint="https://app.example.com/"
        appInstanceId="i1"
        sessionId={null}
        apiKey={null}
        onEvent={onEvent}
      />
    );
    window.dispatchEvent(
      new MessageEvent('message', {
        data: { not: 'an envelope' },
        origin: 'https://app.example.com',
      })
    );
    // Nothing should fire.
    await new Promise((r) => setTimeout(r, 10));
    expect(onEvent).not.toHaveBeenCalled();
  });
});
