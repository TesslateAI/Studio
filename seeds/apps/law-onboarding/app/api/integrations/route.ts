import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { DEMO_MODE } from "@/lib/demo-data";

export const runtime = "nodejs";

interface IntegrationStatus {
  id: string;
  name: string;
  description: string;
  status: "connected" | "degraded" | "not_configured";
  detail: string;
  env_vars: string[];
  configured: boolean;
  docs_url?: string;
}

export async function GET() {
  const session = await getServerSession(authOptions);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const integrations: IntegrationStatus[] = [];

  // ── Postgres / DATABASE_URL ──────────────────────────────────────────────
  const dbUrl = process.env.DATABASE_URL;
  const dbConfigured = !!dbUrl && dbUrl !== "${DATABASE_URL}";
  if (dbConfigured) {
    try {
      const { pool } = await import("@/lib/db");
      const client = await pool.connect();
      await client.query("SELECT 1");
      client.release();
      integrations.push({
        id: "postgres",
        name: "PostgreSQL",
        description: "Primary database storing all submissions and audit logs.",
        status: "connected",
        detail: "Connection healthy — query OK.",
        env_vars: ["DATABASE_URL"],
        configured: true,
        docs_url: "https://www.postgresql.org/docs/",
      });
    } catch (e) {
      integrations.push({
        id: "postgres",
        name: "PostgreSQL",
        description: "Primary database storing all submissions and audit logs.",
        status: "degraded",
        detail: `Connection failed: ${e instanceof Error ? e.message : "unknown error"}`,
        env_vars: ["DATABASE_URL"],
        configured: true,
        docs_url: "https://www.postgresql.org/docs/",
      });
    }
  } else {
    integrations.push({
      id: "postgres",
      name: "PostgreSQL",
      description: "Primary database storing all submissions and audit logs.",
      status: "not_configured",
      detail: DEMO_MODE ? "Running in demo mode — no database connected." : "DATABASE_URL is not set.",
      env_vars: ["DATABASE_URL"],
      configured: false,
      docs_url: "https://neon.tech",
    });
  }

  // ── Legora AI ────────────────────────────────────────────────────────────
  const legoraKey = process.env.LEGORA_API_KEY;
  const legoraConfigured = !!legoraKey && legoraKey !== "${LEGORA_API_KEY}";
  if (legoraConfigured) {
    try {
      const res = await fetch("https://api.legora.com/v1/health", {
        headers: { Authorization: `Bearer ${legoraKey}` },
        signal: AbortSignal.timeout(5000),
      });
      if (res.ok) {
        integrations.push({
          id: "legora",
          name: "Legora AI",
          description: "AI-powered contract redlining engine. Automatically reviews and marks up uploaded documents.",
          status: "connected",
          detail: "API reachable — authentication valid.",
          env_vars: ["LEGORA_API_KEY", "LEGORA_CONFIDENCE_THRESHOLD"],
          configured: true,
          docs_url: "https://legora.com/docs",
        });
      } else {
        integrations.push({
          id: "legora",
          name: "Legora AI",
          description: "AI-powered contract redlining engine. Automatically reviews and marks up uploaded documents.",
          status: "degraded",
          detail: `API returned HTTP ${res.status} — check your API key.`,
          env_vars: ["LEGORA_API_KEY", "LEGORA_CONFIDENCE_THRESHOLD"],
          configured: true,
          docs_url: "https://legora.com/docs",
        });
      }
    } catch {
      integrations.push({
        id: "legora",
        name: "Legora AI",
        description: "AI-powered contract redlining engine. Automatically reviews and marks up uploaded documents.",
        status: "degraded",
        detail: "API unreachable — network error or timeout.",
        env_vars: ["LEGORA_API_KEY", "LEGORA_CONFIDENCE_THRESHOLD"],
        configured: true,
        docs_url: "https://legora.com/docs",
      });
    }
  } else {
    integrations.push({
      id: "legora",
      name: "Legora AI",
      description: "AI-powered contract redlining engine. Automatically reviews and marks up uploaded documents.",
      status: "not_configured",
      detail: "LEGORA_API_KEY is not set. Redline requests will be skipped.",
      env_vars: ["LEGORA_API_KEY", "LEGORA_CONFIDENCE_THRESHOLD"],
      configured: false,
      docs_url: "https://legora.com/docs",
    });
  }

  // ── Google Drive ─────────────────────────────────────────────────────────
  const driveJson = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
  const driveFolderId = process.env.GOOGLE_DRIVE_PARENT_FOLDER_ID;
  const driveConfigured =
    !!driveJson &&
    driveJson !== "${GOOGLE_SERVICE_ACCOUNT_JSON}" &&
    !!driveFolderId &&
    driveFolderId !== "${GOOGLE_DRIVE_PARENT_FOLDER_ID}";

  if (driveConfigured) {
    try {
      const parsed = JSON.parse(driveJson!);
      const hasEmail = !!parsed.client_email;
      integrations.push({
        id: "google_drive",
        name: "Google Drive",
        description: "Automatically creates per-client folders and uploads submitted documents.",
        status: hasEmail ? "connected" : "degraded",
        detail: hasEmail
          ? `Service account: ${parsed.client_email}`
          : "Service account JSON is missing client_email.",
        env_vars: ["GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_DRIVE_PARENT_FOLDER_ID"],
        configured: true,
        docs_url: "https://developers.google.com/drive",
      });
    } catch {
      integrations.push({
        id: "google_drive",
        name: "Google Drive",
        description: "Automatically creates per-client folders and uploads submitted documents.",
        status: "degraded",
        detail: "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON.",
        env_vars: ["GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_DRIVE_PARENT_FOLDER_ID"],
        configured: true,
        docs_url: "https://developers.google.com/drive",
      });
    }
  } else {
    integrations.push({
      id: "google_drive",
      name: "Google Drive",
      description: "Automatically creates per-client folders and uploads submitted documents.",
      status: "not_configured",
      detail: "Service account credentials not set. Files will not be stored in Drive.",
      env_vars: ["GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_DRIVE_PARENT_FOLDER_ID"],
      configured: false,
      docs_url: "https://developers.google.com/drive",
    });
  }

  // ── NextAuth / Auth ──────────────────────────────────────────────────────
  const nextauthSecret = process.env.NEXTAUTH_SECRET;
  const nextauthUrl = process.env.NEXTAUTH_URL;
  const authConfigured =
    !!nextauthSecret &&
    nextauthSecret !== "${NEXTAUTH_SECRET}" &&
    !!nextauthUrl &&
    nextauthUrl !== "${NEXTAUTH_URL}";

  integrations.push({
    id: "auth",
    name: "Authentication",
    description: "Credentials-based auth guarding the attorney dashboard.",
    status: authConfigured ? "connected" : "degraded",
    detail: authConfigured
      ? `JWT session auth active. URL: ${nextauthUrl}`
      : "NEXTAUTH_SECRET or NEXTAUTH_URL is not properly configured.",
    env_vars: ["NEXTAUTH_SECRET", "NEXTAUTH_URL", "DASHBOARD_USER", "DASHBOARD_PASSWORD"],
    configured: authConfigured,
    docs_url: "https://next-auth.js.org",
  });

  // ── Automation Webhook ───────────────────────────────────────────────────
  const automationSecret = process.env.AUTOMATION_SECRET;
  const automationConfigured =
    !!automationSecret && automationSecret !== "${AUTOMATION_SECRET}";

  integrations.push({
    id: "automation",
    name: "Automation Webhook",
    description: "Internal webhook triggered on new submissions to run post-processing (Drive upload, Legora redline).",
    status: automationConfigured ? "connected" : "not_configured",
    detail: automationConfigured
      ? "AUTOMATION_SECRET is set — endpoint is protected."
      : "AUTOMATION_SECRET not set. The /api/automation/on-submission endpoint is unprotected.",
    env_vars: ["AUTOMATION_SECRET"],
    configured: automationConfigured,
  });

  return NextResponse.json({ integrations, demo_mode: DEMO_MODE });
}
