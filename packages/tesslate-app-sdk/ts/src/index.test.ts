import { describe, it, expect, vi } from "vitest";
import { AppClient, ManifestBuilder, AppSdkHttpError } from "./index.js";

const API_KEY = "tsk_test_key_abc123";
const BASE = "https://your-domain.com";

function mockFetch(
  status: number,
  body: unknown,
): { fetchImpl: typeof fetch; calls: Array<{ url: string; init: RequestInit }> } {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const fetchImpl = vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    const text = body === undefined ? "" : typeof body === "string" ? body : JSON.stringify(body);
    return new Response(text, { status, headers: { "content-type": "application/json" } });
  }) as unknown as typeof fetch;
  return { fetchImpl, calls };
}

describe("AppClient", () => {
  it("rejects non-tsk_ api keys", () => {
    expect(() => new AppClient({ baseUrl: BASE, apiKey: "bad" })).toThrow(/tsk_/);
  });

  it("publishVersion posts correct body + headers", async () => {
    const { fetchImpl, calls } = mockFetch(201, {
      app_id: "a",
      app_version_id: "v",
      version: "1.0.0",
      bundle_hash: "bh",
      manifest_hash: "mh",
      submission_id: "s",
    });
    const c = new AppClient({ baseUrl: BASE, apiKey: API_KEY, fetch: fetchImpl });
    const res = await c.publishVersion({
      projectId: "proj-1",
      manifest: { manifest_schema_version: "2025-01" } as any,
    });
    expect(res.app_id).toBe("a");
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`${BASE}/api/app-versions/publish`);
    expect(calls[0].init.method).toBe("POST");
    const h = calls[0].init.headers as Record<string, string>;
    expect(h["Authorization"]).toBe(`Bearer ${API_KEY}`);
    expect(h["Content-Type"]).toBe("application/json");
    const body = JSON.parse(calls[0].init.body as string);
    expect(body.project_id).toBe("proj-1");
    expect(body.manifest.manifest_schema_version).toBe("2025-01");
  });

  it("beginSession parses response and throws on non-2xx", async () => {
    {
      const { fetchImpl } = mockFetch(201, {
        session_id: "s",
        app_instance_id: "a",
        litellm_key_id: "lk",
        api_key: "sk-...",
        budget_usd: 1.0,
        ttl_seconds: 3600,
      });
      const c = new AppClient({ baseUrl: BASE, apiKey: API_KEY, fetch: fetchImpl });
      const r = await c.beginSession({ appInstanceId: "a" });
      expect(r.session_id).toBe("s");
      expect(r.api_key).toBe("sk-...");
    }
    {
      const { fetchImpl } = mockFetch(409, { detail: "not runnable" });
      const c = new AppClient({ baseUrl: BASE, apiKey: API_KEY, fetch: fetchImpl });
      await expect(c.beginSession({ appInstanceId: "a" })).rejects.toBeInstanceOf(AppSdkHttpError);
    }
  });

  it("getVersionInfo hits GET /api/version", async () => {
    const { fetchImpl, calls } = mockFetch(200, {
      build_sha: "abc",
      schema_versions: { manifest: ["2025-01"] },
      features: ["apps.v1"],
      feature_set_hash: "h",
      runtime_api_supported: ["2025-01"],
    });
    const c = new AppClient({ baseUrl: BASE, apiKey: API_KEY, fetch: fetchImpl });
    const v = await c.getVersionInfo();
    expect(v.build_sha).toBe("abc");
    expect(calls[0].init.method).toBe("GET");
    expect(calls[0].url).toBe(`${BASE}/api/version`);
  });

  it("checkCompat posts to /api/version/check-compat", async () => {
    const { fetchImpl, calls } = mockFetch(200, {
      compatible: true,
      missing: [],
      manifest_schema_supported: ["2025-01"],
      upgrade_required: false,
      feature_set_hash: "h",
    });
    const c = new AppClient({ baseUrl: BASE, apiKey: API_KEY, fetch: fetchImpl });
    const r = await c.checkCompat({ required_features: ["apps.v1"], manifest_schema: "2025-01" });
    expect(r.compatible).toBe(true);
    expect(calls[0].url).toBe(`${BASE}/api/version/check-compat`);
    expect(calls[0].init.method).toBe("POST");
    const body = JSON.parse(calls[0].init.body as string);
    expect(body.manifest_schema).toBe("2025-01");
  });

  it("endSession issues DELETE", async () => {
    const { fetchImpl, calls } = mockFetch(204, undefined);
    const c = new AppClient({ baseUrl: BASE, apiKey: API_KEY, fetch: fetchImpl });
    await c.endSession("sess-1");
    expect(calls[0].init.method).toBe("DELETE");
    expect(calls[0].url).toBe(`${BASE}/api/apps/runtime/sessions/sess-1`);
  });
});

describe("ManifestBuilder", () => {
  it("produces a schema-valid shape", () => {
    const m = new ManifestBuilder()
      .app({ slug: "foo", name: "Foo", version: "0.1.0" })
      .surface({ kind: "iframe", entry: "index.html" })
      .billing({ model: "wallet-mix", default_budget_usd: 0.5 })
      .requireFeatures(["apps.v1"])
      .build();
    expect(m.manifest_schema_version).toBe("2025-01");
    expect(m.app.slug).toBe("foo");
    expect(m.surface?.kind).toBe("iframe");
    expect(m.billing?.model).toBe("wallet-mix");
    expect(m.compatibility?.manifest_schema).toBe("2025-01");
    expect(m.compatibility?.required_features).toEqual(["apps.v1"]);
  });

  it("throws without .app()", () => {
    expect(() => new ManifestBuilder().build()).toThrow();
  });
});
