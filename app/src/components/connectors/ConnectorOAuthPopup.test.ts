/**
 * Tests for runOAuthPopup — the postMessage + status-poll fallback flow.
 *
 * We mock window.open and window.addEventListener/removeEventListener to
 * simulate a child popup posting a message back to the opener.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { runOAuthPopup, type StatusPoller } from './ConnectorOAuthPopup';

type MessageListener = (ev: MessageEvent) => void;

describe('runOAuthPopup', () => {
  const originalOpen = window.open;
  let listeners: MessageListener[] = [];

  beforeEach(() => {
    listeners = [];
    vi.useFakeTimers();

    window.addEventListener = vi.fn(
      (type: string, cb: EventListenerOrEventListenerObject) => {
        if (type === 'message') listeners.push(cb as MessageListener);
      },
    ) as unknown as typeof window.addEventListener;
    window.removeEventListener = vi.fn(
      (type: string, cb: EventListenerOrEventListenerObject) => {
        if (type === 'message') listeners = listeners.filter((l) => l !== cb);
      },
    ) as unknown as typeof window.removeEventListener;

    (window as unknown as { open: typeof window.open }).open = vi.fn(
      () => ({ closed: false, close: vi.fn() }) as unknown as Window,
    );
  });

  afterEach(() => {
    (window as unknown as { open: typeof window.open }).open = originalOpen;
    vi.useRealTimers();
  });

  it('resolves success when a postMessage with matching origin arrives', async () => {
    const p = runOAuthPopup('https://auth.example.com/authorize', 'flow-123');

    // Simulate provider postMessage → opener.
    const ev = new MessageEvent('message', {
      origin: window.location.origin,
      data: { type: 'mcp-oauth', status: 'success', config_id: 'abc' },
    });
    listeners.forEach((l) => l(ev));

    const result = await p;
    expect(result.status).toBe('success');
    expect(result.configId).toBe('abc');
  });

  it('ignores messages from other origins', async () => {
    const p = runOAuthPopup('https://auth.example.com/authorize', 'flow-123');

    const cross = new MessageEvent('message', {
      origin: 'https://evil.example.com',
      data: { type: 'mcp-oauth', status: 'success' },
    });
    listeners.forEach((l) => l(cross));

    // Should not yet resolve. Deliver a correct-origin message.
    const good = new MessageEvent('message', {
      origin: window.location.origin,
      data: { type: 'mcp-oauth', status: 'error', message: 'denied' },
    });
    listeners.forEach((l) => l(good));

    const result = await p;
    expect(result.status).toBe('error');
    expect(result.message).toBe('denied');
  });

  it('falls back to statusPoller when no postMessage arrives', async () => {
    const poller: StatusPoller = vi
      .fn()
      .mockResolvedValueOnce({ status: 'pending' })
      .mockResolvedValueOnce({ status: 'success', config_id: 'xyz' });

    const p = runOAuthPopup('https://auth.example.com/authorize', 'flow-999', poller);

    // Trigger two poller iterations.
    await vi.advanceTimersByTimeAsync(1500);
    await vi.advanceTimersByTimeAsync(1500);

    const result = await p;
    expect(result.status).toBe('success');
    expect(result.configId).toBe('xyz');
    expect(poller).toHaveBeenCalledTimes(2);
  });
});
