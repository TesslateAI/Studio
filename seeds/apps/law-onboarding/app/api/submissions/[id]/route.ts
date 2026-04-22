import { NextRequest, NextResponse } from "next/server";
import { query } from "@/lib/db";
import { DEMO_MODE, demoSubmissions, demoAuditLogs } from "@/lib/demo-data";
import type { IntakeSubmission } from "@/lib/types";

// GET /api/submissions/[id]
export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  // ── DEMO MODE ───────────────────────────────────────────────────────────
  if (DEMO_MODE) {
    const sub = demoSubmissions.find((s) => s.id === id);
    if (!sub) return NextResponse.json({ error: "Not found" }, { status: 404 });
    const audit_entries = (demoAuditLogs[id] ?? []).slice().reverse();
    return NextResponse.json({ ...sub, audit_entries });
  }

  try {
    const result = await query<IntakeSubmission>(
      `SELECT
         s.*,
         COALESCE(
           json_agg(
             json_build_object(
               'id', a.id,
               'occurred_at', a.occurred_at,
               'event_type', a.event_type,
               'actor', a.actor,
               'from_status', a.from_status,
               'to_status', a.to_status,
               'detail', a.detail
             ) ORDER BY a.occurred_at DESC
           ) FILTER (WHERE a.id IS NOT NULL),
           '[]'
         ) as audit_entries
       FROM intake_submissions s
       LEFT JOIN audit_log a ON a.submission_id = s.id
       WHERE s.id = $1
       GROUP BY s.id`,
      [id]
    );

    if (result.rows.length === 0) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }

    return NextResponse.json(result.rows[0]);
  } catch (err) {
    console.error("[submissions/id] GET error:", err instanceof Error ? err.message : err);
    return NextResponse.json({ error: "Failed to load submission." }, { status: 500 });
  }
}

// PATCH /api/submissions/[id] — update notes only
export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  let notes: string;
  try {
    const body = await req.json();
    if (typeof body.notes !== "string") {
      return NextResponse.json({ error: "notes must be a string" }, { status: 400 });
    }
    notes = body.notes;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  // ── DEMO MODE ───────────────────────────────────────────────────────────
  if (DEMO_MODE) {
    const sub = demoSubmissions.find((s) => s.id === id);
    if (!sub) return NextResponse.json({ error: "Not found" }, { status: 404 });
    sub.notes = notes;
    return NextResponse.json({ success: true });
  }

  try {
    const result = await query<{ id: string }>(
      `UPDATE intake_submissions SET notes = $1 WHERE id = $2 RETURNING id`,
      [notes, id]
    );

    if (result.rows.length === 0) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }

    await query(
      `INSERT INTO audit_log (submission_id, event_type, actor, detail)
       VALUES ($1, 'NOTE_UPDATED', 'attorney', $2::jsonb)`,
      [id, JSON.stringify({ note: "Attorney notes updated" })]
    );

    return NextResponse.json({ success: true });
  } catch (err) {
    console.error("[submissions/id] PATCH error:", err instanceof Error ? err.message : err);
    return NextResponse.json({ error: "Failed to update notes." }, { status: 500 });
  }
}
