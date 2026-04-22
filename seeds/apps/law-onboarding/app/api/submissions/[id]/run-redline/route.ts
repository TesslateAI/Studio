import { NextRequest, NextResponse } from "next/server";
import { query } from "@/lib/db";
import { runLegora } from "@/lib/legora";
import { DEMO_MODE, demoSubmissions, demoAuditLogs } from "@/lib/demo-data";
import type { FileRef } from "@/lib/types";

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
    sub.status = "Redlining";
    sub.needs_attention = false;
    const logs = demoAuditLogs[id] ?? [];
    logs.push({
      id: `al-demo-${Date.now()}`,
      submission_id: id,
      actor: "attorney",
      event_type: "STATUS_CHANGE",
      detail: `Status changed: ${prev} → Redlining`,
      created_at: new Date().toISOString(),
    });
    logs.push({
      id: `al-demo-${Date.now() + 1}`,
      submission_id: id,
      actor: "system",
      event_type: "LEGORA_REDLINE_STARTED",
      detail: "Legora AI redline analysis initiated (demo mode).",
      created_at: new Date().toISOString(),
    });
    demoAuditLogs[id] = logs;
    return NextResponse.json({ success: true, status: "Redlining" });
  }

  try {
    const cur = await query<{
      status: string;
      uploaded_file_refs: FileRef[] | string;
      first_name: string;
      last_name: string;
      matter_type: string;
      drive_folder_url: string | null;
    }>(`SELECT status, uploaded_file_refs, first_name, last_name,
               matter_type, drive_folder_url
        FROM intake_submissions WHERE id = $1`,
      [id]
    );

    if (cur.rows.length === 0) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }

    const sub = cur.rows[0];
    const fromStatus = sub.status;

    const fileRefs: FileRef[] =
      typeof sub.uploaded_file_refs === "string"
        ? JSON.parse(sub.uploaded_file_refs)
        : sub.uploaded_file_refs ?? [];

    await query(
      `UPDATE intake_submissions SET status = 'Redlining', needs_attention = false WHERE id = $1`,
      [id]
    );

    await query(
      `INSERT INTO audit_log
         (submission_id, event_type, actor, from_status, to_status, detail)
       VALUES ($1, 'STATUS_CHANGE', 'attorney', $2, 'Redlining', $3::jsonb)`,
      [id, fromStatus, JSON.stringify({ note: "Redline triggered by attorney" })]
    );

    runLegora({
      submissionId: id,
      fileRefs,
      matterType: sub.matter_type,
      clientName: `${sub.last_name}_${sub.first_name}`,
      driveFolderUrl: sub.drive_folder_url,
    }).catch((err) =>
      console.error("[run-redline] Legora error:", err instanceof Error ? err.message : err)
    );

    return NextResponse.json({ success: true, status: "Redlining" });
  } catch (err) {
    console.error("[run-redline] error:", err instanceof Error ? err.message : err);
    return NextResponse.json({ error: "Failed to trigger redline." }, { status: 500 });
  }
}
