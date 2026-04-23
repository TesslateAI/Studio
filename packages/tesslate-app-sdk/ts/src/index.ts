// Tesslate Apps SDK (TypeScript) — author/publish/install/invoke apps
// against a OpenSail deployment using external API keys (`tsk_...`).
//
// Zero runtime deps: relies on global fetch. Inject a custom fetch in tests.
//
// Canonical manifest schema: docs/specs/app-manifest-2025-01.md

export interface AppSdkOptions {
  /** Base URL of the Studio deployment, e.g. https://opensail.tesslate.com (no trailing slash required). */
  baseUrl: string;
  /** External API key. Must begin with `tsk_`. */
  apiKey: string;
  /** Injectable fetch. Defaults to global fetch. */
  fetch?: typeof fetch;
}

// -----------------------------------------------------------------------------
// Manifest types (subset of app-manifest-2025-01.md)
//
// The authoritative schema lives in the docs; this interface mirrors only
// the fields required for typed authoring. Extra properties are permitted
// at the root via `[k: string]: unknown` so the SDK never blocks a
// well-formed manifest the server accepts.
// -----------------------------------------------------------------------------

export interface AppManifestApp {
  slug: string;
  name: string;
  version: string;
  summary?: string;
  icon?: string;
}

export interface AppManifestSurface {
  kind: "iframe" | "headless" | "chat";
  entry?: string;
  permissions?: string[];
}

export interface AppManifestBilling {
  model: "wallet-mix" | "creator-pays" | "user-pays";
  default_budget_usd?: number;
  session_ttl_seconds?: number;
}

export interface AppManifestCompatibility {
  manifest_schema: string; // e.g. "2025-01"
  required_features?: string[];
}

export interface AppManifest2025_01 {
  manifest_schema_version: "2025-01";
  app: AppManifestApp;
  surface?: AppManifestSurface;
  billing?: AppManifestBilling;
  compatibility?: AppManifestCompatibility;
  mcp_servers?: Array<Record<string, unknown>>;
  env?: Array<Record<string, unknown>>;
  [k: string]: unknown;
}

// -----------------------------------------------------------------------------
// Response types
// -----------------------------------------------------------------------------

export interface PublishResponse {
  app_id: string;
  app_version_id: string;
  version: string;
  bundle_hash: string;
  manifest_hash: string;
  submission_id: string;
}

export interface InstallResponse {
  app_instance_id: string;
  project_id: string;
  volume_id: string;
  node_name: string;
}

export interface SessionResponse {
  session_id: string;
  app_instance_id: string;
  litellm_key_id: string;
  api_key: string;
  budget_usd: number;
  ttl_seconds: number;
}

export interface VersionInfo {
  build_sha: string;
  schema_versions: { manifest: string[] };
  features: string[];
  feature_set_hash: string;
  runtime_api_supported: string[];
}

export interface CompatResult {
  compatible: boolean;
  missing: string[];
  manifest_schema_supported: string[];
  upgrade_required: boolean;
  feature_set_hash: string;
}

// -----------------------------------------------------------------------------
// Error
// -----------------------------------------------------------------------------

export class AppSdkHttpError extends Error {
  readonly status: number;
  readonly body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(`${status} ${message}`);
    this.name = "AppSdkHttpError";
    this.status = status;
    this.body = body;
  }
}

// -----------------------------------------------------------------------------
// Client
// -----------------------------------------------------------------------------

export class AppClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: AppSdkOptions) {
    if (!opts.apiKey || !opts.apiKey.startsWith("tsk_")) {
      throw new Error("AppClient: apiKey must be a Tesslate external API key (starts with 'tsk_')");
    }
    if (!opts.baseUrl) {
      throw new Error("AppClient: baseUrl is required");
    }
    this.baseUrl = opts.baseUrl.replace(/\/$/, "");
    this.apiKey = opts.apiKey;
    this.fetchImpl =
      opts.fetch ?? ((globalThis as unknown as { fetch: typeof fetch }).fetch);
    if (!this.fetchImpl) {
      throw new Error("AppClient: no fetch implementation available");
    }
  }

  // ---- Version lifecycle ---------------------------------------------------

  publishVersion(args: {
    projectId: string;
    manifest: AppManifest2025_01 | Record<string, unknown>;
    appId?: string;
  }): Promise<PublishResponse> {
    return this.post<PublishResponse>("/api/app-versions/publish", {
      project_id: args.projectId,
      manifest: args.manifest,
      app_id: args.appId ?? null,
    });
  }

  // ---- Install -------------------------------------------------------------

  installApp(args: {
    appVersionId: string;
    teamId: string;
    walletMixConsent: Record<string, unknown>;
    mcpConsents: Array<Record<string, unknown>>;
    updatePolicy?: "manual" | "patch-auto" | "minor-auto" | "pinned";
  }): Promise<InstallResponse> {
    return this.post<InstallResponse>("/api/app-installs/install", {
      app_version_id: args.appVersionId,
      team_id: args.teamId,
      wallet_mix_consent: args.walletMixConsent,
      mcp_consents: args.mcpConsents,
      update_policy: args.updatePolicy ?? "manual",
    });
  }

  // ---- Runtime -------------------------------------------------------------

  beginSession(args: {
    appInstanceId: string;
    budgetUsd?: number;
    ttlSeconds?: number;
  }): Promise<SessionResponse> {
    return this.post<SessionResponse>("/api/apps/runtime/sessions", {
      app_instance_id: args.appInstanceId,
      ...(args.budgetUsd !== undefined ? { budget_usd: args.budgetUsd } : {}),
      ...(args.ttlSeconds !== undefined ? { ttl_seconds: args.ttlSeconds } : {}),
    });
  }

  async endSession(sessionId: string): Promise<void> {
    await this.request("DELETE", `/api/apps/runtime/sessions/${encodeURIComponent(sessionId)}`);
  }

  beginInvocation(args: {
    appInstanceId: string;
    budgetUsd?: number;
    ttlSeconds?: number;
  }): Promise<SessionResponse> {
    return this.post<SessionResponse>("/api/apps/runtime/invocations", {
      app_instance_id: args.appInstanceId,
      ...(args.budgetUsd !== undefined ? { budget_usd: args.budgetUsd } : {}),
      ...(args.ttlSeconds !== undefined ? { ttl_seconds: args.ttlSeconds } : {}),
    });
  }

  async endInvocation(sessionId: string): Promise<void> {
    await this.request(
      "DELETE",
      `/api/apps/runtime/invocations/${encodeURIComponent(sessionId)}`,
    );
  }

  // ---- Version info --------------------------------------------------------

  getVersionInfo(): Promise<VersionInfo> {
    return this.request<VersionInfo>("GET", "/api/version");
  }

  checkCompat(args: {
    required_features: string[];
    manifest_schema: string;
  }): Promise<CompatResult> {
    return this.post<CompatResult>("/api/version/check-compat", args);
  }

  // ---- internals -----------------------------------------------------------

  private post<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>("POST", path, body);
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.apiKey}`,
      Accept: "application/json",
    };
    let payload: string | undefined;
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    const res = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method,
      headers,
      body: payload,
    });

    if (res.status === 204) {
      return undefined as unknown as T;
    }

    const text = await res.text();
    let parsed: unknown = null;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = text;
      }
    }
    if (!res.ok) {
      const msg =
        (parsed && typeof parsed === "object" && "detail" in (parsed as Record<string, unknown>)
          ? String((parsed as Record<string, unknown>).detail)
          : res.statusText) || "request failed";
      throw new AppSdkHttpError(res.status, msg, parsed);
    }
    return parsed as T;
  }
}

// -----------------------------------------------------------------------------
// Manifest builder (fluent, typed)
// -----------------------------------------------------------------------------

export class ManifestBuilder {
  private _app: AppManifestApp | null = null;
  private _surface: AppManifestSurface | null = null;
  private _billing: AppManifestBilling | null = null;
  private _compat: AppManifestCompatibility = { manifest_schema: "2025-01" };
  private _extras: Record<string, unknown> = {};

  app(a: AppManifestApp): this {
    this._app = { ...a };
    return this;
  }

  surface(s: AppManifestSurface): this {
    this._surface = { ...s };
    return this;
  }

  billing(b: AppManifestBilling): this {
    this._billing = { ...b };
    return this;
  }

  requireFeatures(features: string[]): this {
    this._compat = {
      ...this._compat,
      required_features: [...(this._compat.required_features ?? []), ...features],
    };
    return this;
  }

  extra(key: string, value: unknown): this {
    this._extras[key] = value;
    return this;
  }

  build(): AppManifest2025_01 {
    if (!this._app) {
      throw new Error("ManifestBuilder: .app({slug,name,version}) is required");
    }
    return {
      manifest_schema_version: "2025-01",
      app: this._app,
      ...(this._surface ? { surface: this._surface } : {}),
      ...(this._billing ? { billing: this._billing } : {}),
      compatibility: this._compat,
      ...this._extras,
    };
  }
}
