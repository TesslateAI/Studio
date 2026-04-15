import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { EmbedClient, EmbedRemoteError } from "./index.js";
import type { EmbedEnvelope } from "./types.js";

const ORIGIN = "https://your-domain.com";

describe("EmbedClient", () => {
  let parentWin: { postMessage: ReturnType<typeof vi.fn> };
  let client: EmbedClient;

  beforeEach(() => {
    parentWin = { postMessage: vi.fn() };
    client = new EmbedClient({
      targetOrigin: ORIGIN,
      timeoutMs: 100,
      win: window,
      parentWin: parentWin as unknown as Window,
    });
  });

  afterEach(() => {
    client.dispose();
  });

  function deliver(env: EmbedEnvelope, origin: string = ORIGIN): void {
    window.dispatchEvent(new MessageEvent("message", { data: env, origin }));
  }

  it("request/response roundtrip resolves with payload", async () => {
    const p = client.request<{ x: number }, { y: number }>("math.double", { x: 21 });
    // grab the id the client sent
    expect(parentWin.postMessage).toHaveBeenCalledTimes(1);
    const sent = parentWin.postMessage.mock.calls[0][0] as EmbedEnvelope;
    expect(parentWin.postMessage.mock.calls[0][1]).toBe(ORIGIN);
    expect(sent.kind).toBe("request");
    expect(sent.topic).toBe("math.double");

    deliver({ v: 1, kind: "response", id: sent.id, topic: sent.topic, payload: { y: 42 } });
    await expect(p).resolves.toEqual({ y: 42 });
  });

  it("request rejects on timeout", async () => {
    const p = client.request("slow.topic", {});
    await expect(p).rejects.toThrow(/timed out/);
  });

  it("drops messages from a mismatched origin", async () => {
    const handler = vi.fn();
    client.on("evt.ping", handler);
    deliver(
      { v: 1, kind: "event", id: "e1", topic: "evt.ping", payload: { a: 1 } },
      "https://evil.example",
    );
    // also should not resolve any pending request
    const p = client.request("unrelated", {});
    const sent = parentWin.postMessage.mock.calls.at(-1)![0] as EmbedEnvelope;
    deliver(
      { v: 1, kind: "response", id: sent.id, topic: sent.topic, payload: "nope" },
      "https://evil.example",
    );
    await expect(p).rejects.toThrow(/timed out/);
    expect(handler).not.toHaveBeenCalled();
  });

  it("error envelope rejects with EmbedRemoteError", async () => {
    const p = client.request("bad.topic", {});
    const sent = parentWin.postMessage.mock.calls[0][0] as EmbedEnvelope;
    deliver({
      v: 1,
      kind: "response",
      id: sent.id,
      topic: sent.topic,
      payload: null,
      error: { code: "NOT_FOUND", message: "missing" },
    });
    await expect(p).rejects.toBeInstanceOf(EmbedRemoteError);
    await expect(p).rejects.toMatchObject({ code: "NOT_FOUND" });
  });

  it("unsubscribe stops delivery", () => {
    const handler = vi.fn();
    const off = client.on("evt.ping", handler);
    deliver({ v: 1, kind: "event", id: "e1", topic: "evt.ping", payload: 1 });
    expect(handler).toHaveBeenCalledTimes(1);
    off();
    deliver({ v: 1, kind: "event", id: "e2", topic: "evt.ping", payload: 2 });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("dispose removes the window listener and rejects pending", async () => {
    const p = client.request("pending", {});
    client.dispose();
    await expect(p).rejects.toThrow(/disposed/);
    // Subsequent messages are ignored (no throw).
    const handler = vi.fn();
    client.on("evt", handler);
    deliver({ v: 1, kind: "event", id: "e", topic: "evt", payload: 1 });
    expect(handler).not.toHaveBeenCalled();
  });

  it("rejects wildcard targetOrigin", () => {
    expect(() => new EmbedClient({ targetOrigin: "*" })).toThrow();
  });
});
