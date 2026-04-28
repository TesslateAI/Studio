import { NextRequest, NextResponse } from "next/server";
import { createHash } from "crypto";
import { query } from "@/lib/db";
import { DEMO_MODE } from "@/lib/demo-data";
import type { FileRef } from "@/lib/types";

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB
const ALLOWED_MIME = new Set([
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]);
const ALLOWED_EXT = new Set([".pdf", ".docx"]);
const RATE_LIMIT_MAX = 5;
const RATE_LIMIT_WINDOW_MS = 60 * 60 * 1000; // 1 hour
const VALID_MATTER_TYPES = new Set([
  "NDA",
  "Contractor Agreement",
  "Confidentiality",
  "Employment Contract",
  "Commercial Lease",
  "SaaS Agreement",
  "IP Assignment",
  "Joint Venture",
  "Other",
]);

// In-memory rate limit store
const rateLimitStore = new Map<string, number[]>();

function getIpHash(req: NextRequest): string {
  const forwarded = req.headers.get("x-forwarded-for");
  const ip = forwarded ? forwarded.split(",")[0].trim() : "unknown";
  return createHash("sha256").update(ip + (process.env.NEXTAUTH_SECRET ?? "secret")).digest("hex");
}

function checkRateLimit(ipHash: string): boolean {
  const now = Date.now();
  const window = now - RATE_LIMIT_WINDOW_MS;
  const hits = (rateLimitStore.get(ipHash) ?? []).filter((t) => t > window);
  if (hits.length >= RATE_LIMIT_MAX) return false;
  rateLimitStore.set(ipHash, [...hits, now]);
  return true;
}

export async function POST(req: NextRequest) {
  // Rate limit check
  const ipHash = getIpHash(req);
  if (!checkRateLimit(ipHash)) {
    return NextResponse.json(
      { error: "Too many submissions. Please try again later." },
      { status: 429 }
    );
  }

  // Parse multipart form data
  let formData: FormData;
  try {
    formData = await req.formData();
  } catch {
    return NextResponse.json({ error: "Invalid form data." }, { status: 400 });
  }

  // Extract fields
  const first_name = (formData.get("first_name") as string | null)?.trim() ?? "";
  const last_name = (formData.get("last_name") as string | null)?.trim() ?? "";
  const email = (formData.get("email") as string | null)?.trim() ?? "";
  const phone = (formData.get("phone") as string | null)?.trim() ?? "";
  const matter_type = (formData.get("matter_type") as string | null)?.trim() ?? "";
  const description = (formData.get("description") as string | null)?.trim() ?? "";
  const consent = formData.get("consent") === "true";

  // Validate required fields
  if (!first_name || !last_name || !email || !matter_type || !description) {
    return NextResponse.json(
      { error: "Missing required fields." },
      { status: 400 }
    );
  }

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return NextResponse.json({ error: "Invalid email address." }, { status: 400 });
  }

  if (!VALID_MATTER_TYPES.has(matter_type)) {
    return NextResponse.json({ error: "Invalid matter type." }, { status: 400 });
  }

  if (description.trim().length < 20) {
    return NextResponse.json(
      { error: "Description must be at least 20 characters." },
      { status: 400 }
    );
  }

  if (!consent) {
    return NextResponse.json(
      { error: "Consent is required." },
      { status: 400 }
    );
  }

  // Process uploaded files
  const rawFiles = formData.getAll("files") as File[];
  const fileRefs: FileRef[] = [];

  for (const file of rawFiles) {
    if (!(file instanceof File) || file.size === 0) continue;

    const ext = "." + (file.name.split(".").pop() ?? "").toLowerCase();
    const mime = file.type;

    if (!ALLOWED_EXT.has(ext) && !ALLOWED_MIME.has(mime)) {
      return NextResponse.json(
        { error: `File "${file.name}" is not a supported type (PDF or DOCX only).` },
        { status: 400 }
      );
    }

    if (file.size > MAX_FILE_SIZE) {
      return NextResponse.json(
        { error: `File "${file.name}" exceeds the 10MB size limit.` },
        { status: 400 }
      );
    }

    const buffer = await file.arrayBuffer();
    const base64 = Buffer.from(buffer).toString("base64");

    fileRefs.push({
      id: crypto.randomUUID(),
      name: file.name,
      size: file.size,
      mime: mime || (ext === ".pdf" ? "application/pdf" : "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
      temp_data: `data:${mime};base64,${base64}`,
    });
  }

  // ── DEMO MODE: skip DB, return a fake submission ID ───────────────────────
  if (DEMO_MODE) {
    const fakeId = `demo-new-${crypto.randomUUID().slice(0, 8)}`;
    console.log("[submit] DEMO MODE — skipping DB insert, returning fake id:", fakeId);
    return NextResponse.json({ id: fakeId }, { status: 201 });
  }

  // Insert into database
  try {
    const result = await query<{ id: string }>(
      `INSERT INTO intake_submissions
         (first_name, last_name, email, phone, matter_type, description,
          consent, uploaded_file_refs, status, ip_hash)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, 'New', $9)
       RETURNING id`,
      [
        first_name,
        last_name,
        email,
        phone || null,
        matter_type,
        description,
        consent,
        JSON.stringify(fileRefs),
        ipHash,
      ]
    );

    const submissionId = result.rows[0].id;

    await query(
      `INSERT INTO audit_log
         (submission_id, event_type, actor, to_status, detail)
       VALUES ($1, 'STATUS_CHANGE', 'client', 'New', $2::jsonb)`,
      [
        submissionId,
        JSON.stringify({
          note: "Intake form submitted",
          file_count: fileRefs.length,
        }),
      ]
    );

    triggerAutomation(submissionId, req).catch((err) =>
      console.error("[submit] Automation trigger error:", err instanceof Error ? err.message : err)
    );

    return NextResponse.json({ id: submissionId }, { status: 201 });
  } catch (err) {
    console.error("[submit] DB error:", err instanceof Error ? err.message : "unknown");
    return NextResponse.json(
      { error: "Failed to save submission. Please try again." },
      { status: 500 }
    );
  }
}

async function triggerAutomation(submissionId: string, req: NextRequest) {
  const baseUrl =
    process.env.NEXTAUTH_URL ??
    `http://localhost:${process.env.PORT ?? 3000}`;

  const res = await fetch(`${baseUrl}/api/automation/on-submission`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-automation-secret": process.env.NEXTAUTH_SECRET ?? "",
    },
    body: JSON.stringify({ submissionId }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Automation responded ${res.status}: ${text}`);
  }
}
