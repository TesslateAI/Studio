// Shared types for the Tesslate Apps embed SDK.
// Canonical protocol reference: docs/specs/app-manifest-2025-01.md (postMessage section)

export type EnvelopeKind = "request" | "response" | "event";

export interface EmbedEnvelope<T = unknown> {
  /** Envelope protocol version. */
  v: 1;
  kind: EnvelopeKind;
  /** UUID used to correlate request<->response. */
  id: string;
  /** Dotted topic, e.g. "runtime.begin_session", "billing.record_spend". */
  topic: string;
  payload: T;
  error?: { code: string; message: string };
}

export interface EmbedClientOptions {
  /** Expected Studio shell origin; enforced on every inbound and outbound postMessage. */
  targetOrigin: string;
  /** Default timeout for request() in milliseconds. Defaults to 10_000. */
  timeoutMs?: number;
  /** Injectable for tests — defaults to `window`. */
  win?: Window;
  /** Injectable for tests — defaults to `window.parent`. */
  parentWin?: Window;
}
