// Tests for ConnectorProxy. We pass a vi-mocked fetch via the constructor
// so no real network I/O happens, and assert the SDK builds the expected
// URL/headers/body for each provider sugar method.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ConnectorProxy, ConnectorProxyHttpError } from "../index.js";

const BASE = "http://opensail-runtime:8400";
const TOKEN = "instance.nonce.deadbeef";

interface Call {
  url: string;
  init: RequestInit;
}

function mockFetch(
  status: number,
  body: unknown,
): { fetchImpl: typeof fetch; calls: Call[] } {
  const calls: Call[] = [];
  const fetchImpl = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    // 204/205/304 forbid a body in the Response constructor.
    const bodyless = status === 204 || status === 205 || status === 304;
    const text = bodyless || body === undefined
      ? null
      : typeof body === "string"
        ? body
        : JSON.stringify(body);
    return new Response(text, {
      status,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;
  return { fetchImpl, calls };
}

function makeProxy(fetchImpl: typeof fetch): ConnectorProxy {
  return new ConnectorProxy({ baseUrl: BASE, token: TOKEN, fetch: fetchImpl });
}

describe("ConnectorProxy construction", () => {
  const ORIGINAL_ENV = { ...process.env };

  beforeEach(() => {
    delete process.env.OPENSAIL_RUNTIME_URL;
    delete process.env.OPENSAIL_APPINSTANCE_TOKEN;
  });

  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  it("reads env defaults when args omitted", () => {
    process.env.OPENSAIL_RUNTIME_URL = "http://envurl:9000/";
    process.env.OPENSAIL_APPINSTANCE_TOKEN = "envtoken";
    // Provide fetch so construction doesn't fail in this test env.
    const proxy = new ConnectorProxy({ fetch: globalThis.fetch });
    // base URL trailing slash stripped
    expect((proxy as unknown as { baseUrl: string }).baseUrl).toBe("http://envurl:9000");
  });

  it("throws when neither arg nor env is set", () => {
    expect(() => new ConnectorProxy({ fetch: globalThis.fetch })).toThrow(
      /OPENSAIL_RUNTIME_URL/,
    );
  });
});

// ---- Slack -----------------------------------------------------------------

describe("Slack", () => {
  it("chat.postMessage POSTs to .../chat.postMessage with header + body", async () => {
    const { fetchImpl, calls } = mockFetch(200, { ok: true, ts: "1700000000.000100" });
    const proxy = makeProxy(fetchImpl);
    const res = await proxy.slack.chat.postMessage({
      channel: "C123",
      text: "hi",
      thread_ts: "999.111",
    });
    expect((res as { ts: string }).ts).toBe("1700000000.000100");
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`${BASE}/connectors/slack/chat.postMessage`);
    expect(calls[0].init.method).toBe("POST");
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers["X-OpenSail-AppInstance"]).toBe(TOKEN);
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({
      channel: "C123",
      text: "hi",
      thread_ts: "999.111",
    });
  });

  it("conversations.list serializes booleans to query string", async () => {
    const { fetchImpl, calls } = mockFetch(200, { ok: true, channels: [] });
    const proxy = makeProxy(fetchImpl);
    await proxy.slack.conversations.list({
      limit: 20,
      exclude_archived: true,
      types: "public_channel",
    });
    const url = new URL(calls[0].url);
    expect(url.pathname).toBe("/connectors/slack/conversations.list");
    expect(url.searchParams.get("limit")).toBe("20");
    expect(url.searchParams.get("exclude_archived")).toBe("true");
    expect(url.searchParams.get("types")).toBe("public_channel");
    expect(calls[0].init.method).toBe("GET");
  });

  it("users.lookupByEmail puts email in query string", async () => {
    const { fetchImpl, calls } = mockFetch(200, { ok: true });
    const proxy = makeProxy(fetchImpl);
    await proxy.slack.users.lookupByEmail({ email: "a@b.com" });
    const url = new URL(calls[0].url);
    expect(url.searchParams.get("email")).toBe("a@b.com");
  });
});

// ---- GitHub ----------------------------------------------------------------

describe("GitHub", () => {
  it("repos.getCommits builds pathed URL + query", async () => {
    const { fetchImpl, calls } = mockFetch(200, [{ sha: "abc" }, { sha: "def" }]);
    const proxy = makeProxy(fetchImpl);
    const commits = await proxy.github.repos.getCommits({
      owner: "oct",
      repo: "hello",
      per_page: 5,
      sha: "main",
    });
    expect((commits as Array<{ sha: string }>).map((c) => c.sha)).toEqual(["abc", "def"]);
    const url = new URL(calls[0].url);
    expect(url.pathname).toBe("/connectors/github/repos/oct/hello/commits");
    expect(url.searchParams.get("per_page")).toBe("5");
    expect(url.searchParams.get("sha")).toBe("main");
  });

  it("issues.create posts JSON body and strips owner/repo", async () => {
    const { fetchImpl, calls } = mockFetch(201, { number: 42, title: "found a bug" });
    const proxy = makeProxy(fetchImpl);
    const issue = await proxy.github.issues.create({
      owner: "oct",
      repo: "hello",
      title: "found a bug",
      body: "repro steps...",
      labels: ["bug"],
    });
    expect((issue as { number: number }).number).toBe(42);
    expect(calls[0].url).toBe(`${BASE}/connectors/github/repos/oct/hello/issues`);
    const sent = JSON.parse(calls[0].init.body as string);
    expect(sent).toEqual({
      title: "found a bug",
      body: "repro steps...",
      labels: ["bug"],
    });
    // owner/repo must NOT have leaked into the body
    expect(sent.owner).toBeUndefined();
    expect(sent.repo).toBeUndefined();
  });
});

// ---- Linear ----------------------------------------------------------------

describe("Linear", () => {
  it("issues.list issues a GraphQL POST with query + variables", async () => {
    const { fetchImpl, calls } = mockFetch(200, { data: { issues: { nodes: [] } } });
    const proxy = makeProxy(fetchImpl);
    const result = await proxy.linear.issues.list({ first: 10 });
    expect(result).toEqual({ data: { issues: { nodes: [] } } });
    expect(calls[0].url).toBe(`${BASE}/connectors/linear/graphql`);
    const sent = JSON.parse(calls[0].init.body as string);
    expect(sent.query).toContain("issues(");
    expect(sent.variables).toEqual({ first: 10 });
  });

  it("issues.create maps snake_case input to GraphQL camelCase variables", async () => {
    const { fetchImpl, calls } = mockFetch(200, {
      data: { issueCreate: { success: true, issue: { id: "iss-1", url: "https://lin/x" } } },
    });
    const proxy = makeProxy(fetchImpl);
    await proxy.linear.issues.create({
      team_id: "team-1",
      title: "t",
      description: "d",
      priority: 2,
    });
    const sent = JSON.parse(calls[0].init.body as string);
    expect(sent.variables.input).toEqual({
      teamId: "team-1",
      title: "t",
      description: "d",
      priority: 2,
    });
  });
});

// ---- Gmail -----------------------------------------------------------------

describe("Gmail", () => {
  it("messages.list defaults user_id to 'me'", async () => {
    const { fetchImpl, calls } = mockFetch(200, { messages: [{ id: "m1" }] });
    const proxy = makeProxy(fetchImpl);
    await proxy.gmail.messages.list({ q: "from:foo", max_results: 5 });
    const url = new URL(calls[0].url);
    expect(url.pathname).toBe("/connectors/gmail/gmail/v1/users/me/messages");
    expect(url.searchParams.get("q")).toBe("from:foo");
    expect(url.searchParams.get("maxResults")).toBe("5");
  });

  it("messages.send shorthand encodes a base64url RFC822 message", async () => {
    const { fetchImpl, calls } = mockFetch(200, { id: "msg-1" });
    const proxy = makeProxy(fetchImpl);
    await proxy.gmail.messages.send({
      to: "a@b.com",
      from: "me@me.com",
      subject: "hi",
      bodyText: "hello",
    });
    expect(calls[0].url).toBe(
      `${BASE}/connectors/gmail/gmail/v1/users/me/messages/send`,
    );
    const sent = JSON.parse(calls[0].init.body as string);
    expect(typeof sent.raw).toBe("string");
    // Decode base64url back to RFC822 and confirm headers + body landed.
    const b64 = sent.raw.replace(/-/g, "+").replace(/_/g, "/");
    const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
    const decoded = Buffer.from(padded, "base64").toString("utf-8");
    expect(decoded).toContain("To: a@b.com");
    expect(decoded).toContain("From: me@me.com");
    expect(decoded).toContain("Subject: hi");
    expect(decoded).toContain("hello");
  });

  it("messages.send rejects both raw and shorthand at once", () => {
    const { fetchImpl } = mockFetch(200, {});
    const proxy = makeProxy(fetchImpl);
    expect(() => proxy.gmail.messages.send({ raw: "abc", to: "a@b.com" })).toThrow(
      /raw.*OR.*shorthand/,
    );
  });
});

// ---- Errors ----------------------------------------------------------------

describe("Errors", () => {
  it("non-2xx throws ConnectorProxyHttpError with parsed body", async () => {
    const { fetchImpl } = mockFetch(403, { detail: "endpoint not allowed" });
    const proxy = makeProxy(fetchImpl);
    await expect(
      proxy.slack.chat.postMessage({ channel: "C", text: "t" }),
    ).rejects.toBeInstanceOf(ConnectorProxyHttpError);

    const { fetchImpl: f2 } = mockFetch(403, { detail: "endpoint not allowed" });
    const p2 = makeProxy(f2);
    try {
      await p2.slack.chat.postMessage({ channel: "C", text: "t" });
      throw new Error("should have thrown");
    } catch (err) {
      const e = err as ConnectorProxyHttpError;
      expect(e.status).toBe(403);
      expect(e.body).toEqual({ detail: "endpoint not allowed" });
    }
  });

  it("204 returns undefined", async () => {
    const { fetchImpl } = mockFetch(204, undefined);
    const proxy = makeProxy(fetchImpl);
    const result = await proxy.slack.chat.delete({ channel: "C", ts: "1.2" });
    expect(result).toBeUndefined();
  });
});
