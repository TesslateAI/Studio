import { NextRequest, NextResponse } from "next/server";
import { query } from "@/lib/db";
import { DEMO_MODE, demoSubmissions } from "@/lib/demo-data";
import type { IntakeSubmission } from "@/lib/types";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const status = searchParams.get("status");
  const attention = searchParams.get("attention");
  const page = Math.max(1, parseInt(searchParams.get("page") ?? "1", 10));
  const limit = Math.min(100, Math.max(1, parseInt(searchParams.get("limit") ?? "50", 10)));
  const offset = (page - 1) * limit;

  // ── DEMO MODE ─────────────────────────────────────────────────────────────
  if (DEMO_MODE) {
    let data = [...demoSubmissions];
    if (status) data = data.filter((s) => s.status === status);
    if (attention === "true") data = data.filter((s) => s.needs_attention);
    const total = data.length;
    const paged = data.slice(offset, offset + limit);
    return NextResponse.json({
      data: paged,
      total,
      page,
      limit,
      pages: Math.ceil(total / limit),
    });
  }

  const conditions: string[] = [];
  const params: unknown[] = [];
  let idx = 1;

  if (status) {
    conditions.push(`status = $${idx++}`);
    params.push(status);
  }

  if (attention === "true") {
    conditions.push(`needs_attention = true`);
  }

  const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";

  try {
    const countResult = await query<{ count: string }>(
      `SELECT COUNT(*) AS count FROM intake_submissions ${where}`,
      params
    );
    const total = parseInt(countResult.rows[0].count, 10);

    params.push(limit, offset);
    const result = await query<IntakeSubmission>(
      `SELECT
         id, submitted_at, first_name, last_name, email,
         matter_type, status, needs_attention, drive_folder_url,
         (uploaded_file_refs::jsonb) as uploaded_file_refs
       FROM intake_submissions
       ${where}
       ORDER BY
         needs_attention DESC,
         submitted_at DESC
       LIMIT $${idx++} OFFSET $${idx++}`,
      params
    );

    return NextResponse.json({
      data: result.rows,
      total,
      page,
      limit,
      pages: Math.ceil(total / limit),
    });
  } catch (err) {
    console.error("[submissions] DB error:", err instanceof Error ? err.message : "unknown");
    return NextResponse.json({ error: "Failed to load submissions." }, { status: 500 });
  }
}
