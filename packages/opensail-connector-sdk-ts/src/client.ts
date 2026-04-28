// ConnectorProxy is the single-entry HTTP client. It owns the fetch
// implementation, attaches the X-OpenSail-AppInstance header on every
// request, and exposes one property per provider. Each provider uses
// `this._request(...)` so all I/O is centralised.

import { Slack } from "./providers/slack.js";
import { GitHub } from "./providers/github.js";
import { Linear } from "./providers/linear.js";
import { Gmail } from "./providers/gmail.js";

// Mirrored from
// orchestrator/app/services/apps/connector_proxy/auth.py::APP_INSTANCE_HEADER.
const APP_INSTANCE_HEADER = "X-OpenSail-AppInstance";

const RUNTIME_URL_ENV = "OPENSAIL_RUNTIME_URL";
const TOKEN_ENV = "OPENSAIL_APPINSTANCE_TOKEN";

export interface ConnectorProxyOptions {
  /** Base URL of the proxy. Defaults to `process.env.OPENSAIL_RUNTIME_URL`. */
  baseUrl?: string;
  /** Per-pod app-instance token. Defaults to `process.env.OPENSAIL_APPINSTANCE_TOKEN`. */
  token?: string;
  /** Injectable fetch (for tests / non-Node runtimes). Defaults to `globalThis.fetch`. */
  fetch?: typeof fetch;
}

export class ConnectorProxyHttpError extends Error {
  readonly status: number;
  readonly body: unknown;
  readonly response: Response;
  constructor(status: number, message: string, body: unknown, response: Response) {
    super(`${status} ${message}`);
    this.name = "ConnectorProxyHttpError";
    this.status = status;
    this.body = body;
    this.response = response;
  }
}

interface RequestArgs {
  connectorId: string;
  method: string;
  endpointPath: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | string[] | undefined>;
  headers?: Record<string, string>;
}

export class ConnectorProxy {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly fetchImpl: typeof fetch;

  readonly slack: Slack;
  readonly github: GitHub;
  readonly linear: Linear;
  readonly gmail: Gmail;

  constructor(opts: ConnectorProxyOptions = {}) {
    const envBase = readEnv(RUNTIME_URL_ENV);
    const envToken = readEnv(TOKEN_ENV);
    const resolvedBase = opts.baseUrl ?? envBase;
    const resolvedToken = opts.token ?? envToken;

    if (!resolvedBase) {
      throw new Error(
        `ConnectorProxy: baseUrl not provided and $${RUNTIME_URL_ENV} is not set in the environment`,
      );
    }
    if (!resolvedToken) {
      throw new Error(
        `ConnectorProxy: token not provided and $${TOKEN_ENV} is not set in the environment`,
      );
    }

    this.baseUrl = resolvedBase.replace(/\/$/, "");
    this.token = resolvedToken;
    this.fetchImpl = opts.fetch ?? (globalThis as unknown as { fetch: typeof fetch }).fetch;
    if (!this.fetchImpl) {
      throw new Error("ConnectorProxy: no fetch implementation available");
    }

    // Provider sugar. Each receives a callback that flows back into
    // _request so we never hand out the bare fetch / token to providers.
    // The explicit generic `<T>` keeps Dispatch's type parameter alive
    // through the arrow — without it TS infers `unknown` and the
    // assignment to providers fails.
    const dispatch = <T>(args: RequestArgs): Promise<T> => this._request<T>(args);
    this.slack = new Slack(dispatch);
    this.github = new GitHub(dispatch);
    this.linear = new Linear(dispatch);
    this.gmail = new Gmail(dispatch);
  }

  /** Build the full URL the proxy expects: {base}/connectors/{id}/{path}. */
  private buildUrl(connectorId: string, endpointPath: string, query?: RequestArgs["query"]): string {
    const cleanPath = endpointPath.replace(/^\/+/, "");
    let url = `${this.baseUrl}/connectors/${encodeURIComponent(connectorId)}/${cleanPath}`;
    if (query) {
      const usp = new URLSearchParams();
      for (const [k, v] of Object.entries(query)) {
        if (v === undefined) continue;
        if (Array.isArray(v)) {
          for (const item of v) usp.append(k, String(item));
        } else {
          usp.append(k, String(v));
        }
      }
      const qs = usp.toString();
      if (qs) url += `?${qs}`;
    }
    return url;
  }

  /** Low-level dispatch. Public so callers can hit allowlisted endpoints
   *  for which no sugar method exists yet. */
  async _request<T = unknown>(args: RequestArgs): Promise<T> {
    const url = this.buildUrl(args.connectorId, args.endpointPath, args.query);
    const headers: Record<string, string> = {
      [APP_INSTANCE_HEADER]: this.token,
      Accept: "application/json",
      ...(args.headers ?? {}),
    };
    let payload: string | undefined;
    if (args.body !== undefined) {
      headers["Content-Type"] = headers["Content-Type"] ?? "application/json";
      payload = JSON.stringify(args.body);
    }
    const res = await this.fetchImpl(url, {
      method: args.method,
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
      const detail =
        parsed && typeof parsed === "object" && "detail" in (parsed as Record<string, unknown>)
          ? String((parsed as Record<string, unknown>).detail)
          : res.statusText || "request failed";
      throw new ConnectorProxyHttpError(res.status, detail, parsed, res);
    }
    return parsed as T;
  }
}

function readEnv(name: string): string | undefined {
  // process is a Node-ism; in browsers `globalThis.process` is undefined
  // and that's fine — the user must pass baseUrl/token explicitly.
  const proc = (globalThis as unknown as { process?: { env?: Record<string, string | undefined> } })
    .process;
  return proc?.env?.[name];
}
