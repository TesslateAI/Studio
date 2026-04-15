// Tesslate Apps embed SDK — postMessage client for iframe-hosted apps.
//
// The SDK lives inside an iframe rendered by the Studio shell. All traffic
// is JSON envelopes (see ./types.ts) exchanged with `window.parent` via
// postMessage. Origin is strictly enforced on both send and receive.

import type { EmbedClientOptions, EmbedEnvelope, EnvelopeKind } from "./types.js";

export type { EmbedClientOptions, EmbedEnvelope, EnvelopeKind } from "./types.js";

type PendingEntry = {
  resolve: (value: unknown) => void;
  reject: (err: unknown) => void;
  timer: ReturnType<typeof setTimeout>;
};

const DEFAULT_TIMEOUT_MS = 10_000;

export class EmbedClient {
  private readonly targetOrigin: string;
  private readonly timeoutMs: number;
  private readonly win: Window;
  private readonly parentWin: Window;
  private readonly pending = new Map<string, PendingEntry>();
  private readonly handlers = new Map<string, Set<(payload: unknown) => void>>();
  private listener: ((e: MessageEvent) => void) | null = null;
  private disposed = false;

  constructor(opts: EmbedClientOptions) {
    if (!opts.targetOrigin || opts.targetOrigin === "*") {
      throw new Error("EmbedClient: targetOrigin must be an explicit origin (wildcard disallowed)");
    }
    this.targetOrigin = opts.targetOrigin;
    this.timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.win = opts.win ?? (globalThis as unknown as { window: Window }).window;
    this.parentWin = opts.parentWin ?? this.win.parent;

    this.listener = (e: MessageEvent) => this.onMessage(e);
    this.win.addEventListener("message", this.listener);
  }

  /**
   * Send a typed request to the Studio shell and await a response envelope.
   * Rejects on timeout or when the shell returns an `error` field.
   */
  request<TReq, TRes>(topic: string, payload: TReq): Promise<TRes> {
    if (this.disposed) {
      return Promise.reject(new Error("EmbedClient: disposed"));
    }
    const id = this.newId();
    const env: EmbedEnvelope<TReq> = { v: 1, kind: "request", id, topic, payload };

    return new Promise<TRes>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`EmbedClient: request "${topic}" timed out after ${this.timeoutMs}ms`));
      }, this.timeoutMs);

      this.pending.set(id, {
        resolve: resolve as (v: unknown) => void,
        reject,
        timer,
      });

      try {
        this.parentWin.postMessage(env, this.targetOrigin);
      } catch (err) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(err);
      }
    });
  }

  /**
   * Subscribe to a named event topic (kind === "event"). Returns an
   * unsubscribe function.
   */
  on<T>(event: string, handler: (payload: T) => void): () => void {
    let set = this.handlers.get(event);
    if (!set) {
      set = new Set();
      this.handlers.set(event, set);
    }
    const wrapped = handler as (payload: unknown) => void;
    set.add(wrapped);
    return () => {
      const s = this.handlers.get(event);
      if (!s) return;
      s.delete(wrapped);
      if (s.size === 0) this.handlers.delete(event);
    };
  }

  /** Stop listening and reject any in-flight requests. */
  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.listener) {
      this.win.removeEventListener("message", this.listener);
      this.listener = null;
    }
    for (const [id, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.reject(new Error("EmbedClient: disposed"));
      this.pending.delete(id);
    }
    this.handlers.clear();
  }

  // ---- internals ----

  private onMessage(e: MessageEvent): void {
    if (e.origin !== this.targetOrigin) return;
    const env = e.data as EmbedEnvelope | undefined;
    if (!env || typeof env !== "object" || env.v !== 1 || typeof env.id !== "string") {
      return;
    }

    if (env.kind === "response") {
      const entry = this.pending.get(env.id);
      if (!entry) return;
      clearTimeout(entry.timer);
      this.pending.delete(env.id);
      if (env.error) {
        entry.reject(new EmbedRemoteError(env.error.code, env.error.message));
      } else {
        entry.resolve(env.payload);
      }
      return;
    }

    if (env.kind === "event") {
      const set = this.handlers.get(env.topic);
      if (!set) return;
      for (const h of set) {
        try {
          h(env.payload);
        } catch {
          // handlers are user code; swallow so one bad subscriber can't kill others
        }
      }
    }
  }

  private newId(): string {
    const c = (globalThis as unknown as { crypto?: Crypto }).crypto;
    if (c && typeof c.randomUUID === "function") return c.randomUUID();
    // Fallback (jsdom may not expose randomUUID on older engines).
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (ch) => {
      const r = (Math.random() * 16) | 0;
      const v = ch === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }
}

export class EmbedRemoteError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "EmbedRemoteError";
    this.code = code;
  }
}

export function createEmbedClient(opts: EmbedClientOptions): EmbedClient {
  return new EmbedClient(opts);
}
