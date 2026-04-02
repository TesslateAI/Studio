import {
  TesslateApiError,
  TesslateAuthError,
  TesslateError,
  TesslateForbiddenError,
  TesslateNotFoundError,
} from "./errors.js";

export interface HttpClientOptions {
  baseUrl: string;
  apiKey: string;
  /** Request timeout in milliseconds (default: 30 000). */
  timeout?: number;
}

export class HttpClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly timeout: number;

  constructor(opts: HttpClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, "");
    this.apiKey = opts.apiKey;
    this.timeout = opts.timeout ?? 30_000;
  }

  // -- Public helpers -------------------------------------------------------

  async get<T>(path: string, query?: Record<string, string>): Promise<T> {
    const url = this.buildUrl(path, query);
    return this.request<T>(url, { method: "GET" });
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    const url = this.buildUrl(path);
    return this.request<T>(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }

  async patch<T>(path: string, body?: unknown): Promise<T> {
    const url = this.buildUrl(path);
    return this.request<T>(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }

  async delete<T = void>(path: string, body?: unknown): Promise<T> {
    const url = this.buildUrl(path);
    const init: RequestInit = { method: "DELETE" };
    if (body !== undefined) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(body);
    }
    return this.request<T>(url, init);
  }

  /** Return a raw Response (for SSE / streaming). */
  async stream(path: string, query?: Record<string, string>): Promise<Response> {
    const url = this.buildUrl(path, query);
    const res = await fetch(url, {
      method: "GET",
      headers: this.headers(),
      signal: AbortSignal.timeout(this.timeout * 10), // longer timeout for streams
    });
    if (!res.ok) {
      await this.throwForStatus(res);
    }
    return res;
  }

  // -- Internals ------------------------------------------------------------

  private buildUrl(path: string, query?: Record<string, string>): string {
    const url = new URL(`${this.baseUrl}${path}`);
    if (query) {
      for (const [k, v] of Object.entries(query)) {
        if (v !== undefined) url.searchParams.set(k, v);
      }
    }
    return url.toString();
  }

  private headers(): Record<string, string> {
    return { Authorization: `Bearer ${this.apiKey}` };
  }

  private async request<T>(url: string, init: RequestInit): Promise<T> {
    const headers = { ...this.headers(), ...(init.headers as Record<string, string>) };
    let res: Response;
    try {
      res = await fetch(url, {
        ...init,
        headers,
        signal: AbortSignal.timeout(this.timeout),
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === "TimeoutError") {
        throw new TesslateError(`Request timed out after ${this.timeout}ms: ${init.method} ${url}`);
      }
      throw err;
    }

    if (!res.ok) {
      await this.throwForStatus(res);
    }

    const text = await res.text();
    if (!text) return undefined as T;
    return JSON.parse(text) as T;
  }

  private async throwForStatus(res: Response): Promise<never> {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text().catch(() => null);
    }

    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : `HTTP ${res.status}`;

    switch (res.status) {
      case 401:
        throw new TesslateAuthError(detail, body);
      case 403:
        throw new TesslateForbiddenError(detail, body);
      case 404:
        throw new TesslateNotFoundError(detail, body);
      default:
        throw new TesslateApiError(detail, res.status, { body });
    }
  }
}
