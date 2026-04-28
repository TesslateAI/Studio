import { NextRequest, NextResponse } from "next/server";
import { query } from "@/lib/db";
import { DEMO_MODE, demoSubmissions, demoAuditLogs } from "@/lib/demo-data";

export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  // ── DEMO MODE ───────────────────────────────────────────────────────────
  if (DEMO_MODE) {
    const sub = demoSubmissions.find((s) => s.id === id);
    if (!sub) return NextResponse.json({ error: "Not found" }, { status: 404 });
    const prev = sub.status;
    sub.status = "Complete";
    sub.needs_attention = false;
    const logs = demoAuditLogs[id] ?? [];
    logs.push({
      id: `al-demo-${Date.now()}`,
      submission_id: id,
      actor: "attorney",
      event_type: "STATUS_CHANGE",
      detail: `Status changed: ${prev} → Complete`,
      created_at: new Date().toISOString(),
    });
    demoAuditLogs[id] = logs;
    return NextResponse.json({ success: true, status: "Complete" });
  }

  try {
    const cur = await query<{ status: string }>(
      `SELECT status FROM intake_submissions WHERE id = $1`,
      [id]
    );

    if (cur.rows.length === 0) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }

    const fromStatus = cur.rows[0].status;

    await query(
      `UPDATE intake_submissions
       SET status = 'Complete', needs_attention = false
       WHERE id = $1`,
      [id]
    );

    await query(
      `INSERT INTO audit_log
         (submission_id, event_type, actor, from_status, to_status, detail)
       VALUES ($1, 'STATUS_CHANGE', 'attorney', $2, 'Complete', $3::jsonb)`,
      [
        id,
        fromStatus,
        JSON.stringify({ note: "Manually marked complete by attorney" }),
      ]
    );

    return NextResponse.json({ success: true, status: "Complete" });
  } catch (err) {
    console.error("[mark-complete] error:", err instanceof Error ? err.message : err);
    return NextResponse.json({ error: "Failed to mark complete." }, { status: 500 });
  }
}
