import { NextResponse } from "next/server";
import db from "@/lib/db";

export async function GET() {
  try {
    const result = await db.query(
      "SELECT COUNT(*) as count FROM intake_submissions"
    );
    return NextResponse.json({
      status: "ok",
      database: "connected",
      submission_count: Number(result.rows[0].count),
    });
  } catch (err) {
    return NextResponse.json(
      {
        status: "error",
        database: "disconnected",
        message: err instanceof Error ? err.message : "Unknown error",
      },
      { status: 503 }
    );
  }
}
