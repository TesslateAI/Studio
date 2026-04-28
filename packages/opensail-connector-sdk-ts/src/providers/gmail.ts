// Gmail provider sugar. Mirrors the curated allowlist in
// orchestrator/app/services/apps/connector_proxy/provider_adapters/gmail.py.
// Endpoints carry the gmail/v1/users/{userId} prefix; user_id defaults to
// "me" (Google's well-known alias for the authorized user).
//
// messages.send() accepts either a pre-encoded `raw` (base64url RFC822)
// or the friendlier shorthand fields (to, from, subject, bodyText, ...)
// which the SDK encodes for you.

import type { Dispatch } from "./types.js";

const CONNECTOR_ID = "gmail";

export interface GmailListMessagesArgs {
  user_id?: string;
  q?: string;
  max_results?: number;
  page_token?: string;
  label_ids?: string[];
}

export interface GmailGetMessageArgs {
  id: string;
  user_id?: string;
  format?: "minimal" | "full" | "raw" | "metadata";
}

export interface GmailSendMessageArgs {
  user_id?: string;
  /** Pre-encoded base64url RFC822 message. Mutually exclusive with shorthand. */
  raw?: string;
  /** Shorthand: at minimum `to` is required when `raw` is omitted. */
  to?: string | string[];
  from?: string;
  subject?: string;
  bodyText?: string;
  bodyHtml?: string;
  cc?: string | string[];
  bcc?: string | string[];
  threadId?: string;
}

class GmailMessages {
  constructor(private readonly dispatch: Dispatch) {}

  list(args: GmailListMessagesArgs = {}): Promise<Record<string, unknown>> {
    const userId = args.user_id ?? "me";
    const query: Record<string, string | number | boolean | string[] | undefined> = {};
    if (args.q !== undefined) query.q = args.q;
    if (args.max_results !== undefined) query.maxResults = args.max_results;
    if (args.page_token !== undefined) query.pageToken = args.page_token;
    if (args.label_ids !== undefined) query.labelIds = args.label_ids;
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "GET",
      endpointPath: `gmail/v1/users/${userId}/messages`,
      query,
    });
  }

  get(args: GmailGetMessageArgs): Promise<Record<string, unknown>> {
    const userId = args.user_id ?? "me";
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "GET",
      endpointPath: `gmail/v1/users/${userId}/messages/${args.id}`,
      query: args.format !== undefined ? { format: args.format } : undefined,
    });
  }

  send(args: GmailSendMessageArgs): Promise<Record<string, unknown>> {
    if (args.raw === undefined && args.to === undefined) {
      throw new Error("Gmail.messages.send requires either 'raw' or at minimum 'to'");
    }
    if (args.raw !== undefined && args.to !== undefined) {
      throw new Error("Gmail.messages.send: pass 'raw' OR shorthand fields, not both");
    }
    const userId = args.user_id ?? "me";
    const raw = args.raw ?? buildRawMessage(args);
    const body: Record<string, unknown> = { raw };
    if (args.threadId !== undefined) body.threadId = args.threadId;
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "POST",
      endpointPath: `gmail/v1/users/${userId}/messages/send`,
      body,
    });
  }
}

class GmailLabels {
  constructor(private readonly dispatch: Dispatch) {}

  list(args: { user_id?: string } = {}): Promise<Record<string, unknown>> {
    const userId = args.user_id ?? "me";
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "GET",
      endpointPath: `gmail/v1/users/${userId}/labels`,
    });
  }
}

export class Gmail {
  readonly messages: GmailMessages;
  readonly labels: GmailLabels;
  constructor(dispatch: Dispatch) {
    this.messages = new GmailMessages(dispatch);
    this.labels = new GmailLabels(dispatch);
  }
}

// --- helpers ---------------------------------------------------------------

function joinAddresses(v: string | string[]): string {
  return Array.isArray(v) ? v.join(", ") : v;
}

/** Build a minimal RFC 822 message and base64url-encode it for Gmail's
 *  `raw` field. Intentionally simple — no MIME multipart unless both
 *  bodyText and bodyHtml are provided. */
function buildRawMessage(args: GmailSendMessageArgs): string {
  // args.to is guaranteed by send()'s precondition checks.
  const to = joinAddresses(args.to as string | string[]);
  const headers: string[] = [];
  headers.push(`To: ${to}`);
  if (args.from !== undefined) headers.push(`From: ${args.from}`);
  if (args.cc !== undefined) headers.push(`Cc: ${joinAddresses(args.cc)}`);
  if (args.bcc !== undefined) headers.push(`Bcc: ${joinAddresses(args.bcc)}`);
  if (args.subject !== undefined) headers.push(`Subject: ${args.subject}`);
  headers.push("MIME-Version: 1.0");

  let body: string;
  if (args.bodyText !== undefined && args.bodyHtml !== undefined) {
    const boundary = `bndry_${Math.random().toString(36).slice(2, 10)}`;
    headers.push(`Content-Type: multipart/alternative; boundary="${boundary}"`);
    body =
      `--${boundary}\r\n` +
      `Content-Type: text/plain; charset="UTF-8"\r\n\r\n${args.bodyText}\r\n` +
      `--${boundary}\r\n` +
      `Content-Type: text/html; charset="UTF-8"\r\n\r\n${args.bodyHtml}\r\n` +
      `--${boundary}--`;
  } else if (args.bodyHtml !== undefined) {
    headers.push(`Content-Type: text/html; charset="UTF-8"`);
    body = args.bodyHtml;
  } else {
    headers.push(`Content-Type: text/plain; charset="UTF-8"`);
    body = args.bodyText ?? "";
  }

  const message = `${headers.join("\r\n")}\r\n\r\n${body}`;
  // base64url, no padding (Gmail accepts both, but spec says url-safe).
  return base64UrlEncode(message);
}

function base64UrlEncode(input: string): string {
  // Use Node's Buffer when available; otherwise fall back to btoa for browsers.
  const buf = (globalThis as unknown as { Buffer?: { from: (s: string, e: string) => { toString: (e: string) => string } } })
    .Buffer;
  let b64: string;
  if (buf) {
    b64 = buf.from(input, "utf-8").toString("base64");
  } else {
    // Browser fallback: encode UTF-8 first.
    const bytes = new TextEncoder().encode(input);
    let bin = "";
    for (const b of bytes) bin += String.fromCharCode(b);
    b64 = (globalThis as unknown as { btoa: (s: string) => string }).btoa(bin);
  }
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
