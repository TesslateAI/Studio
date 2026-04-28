import db from "@/lib/db";
import type { AuditActor, AuditEventType } from "@/lib/types";

interface AuditParams {
  submission_id: string;
  event_type: AuditEventType;
  actor: AuditActor;
  from_status?: string;
  to_status?: string;
  detail?: Record<string, unknown>;
}

export async function writeAuditLog(params: AuditParams): Promise<void> {
  const { submission_id, event_type, actor, from_status, to_status, detail } =
    params;
  await db.query(
    `INSERT INTO audit_log
       (submission_id, event_type, actor, from_status, to_status, detail)
     VALUES ($1, $2, $3, $4, $5, $6)`,
    [
      submission_id,
      event_type,
      actor,
      from_status ?? null,
      to_status ?? null,
      detail ? JSON.stringify(detail) : null,
    ]
  );
}
