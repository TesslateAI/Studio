export interface FileRef {
  id?: string;
  drive_id?: string;
  name: string;
  size: number;
  mime: string;
  drive_url?: string;
  legora_confidence?: number;
  temp_data?: string;
}

export type MatterType =
  | "NDA"
  | "Contractor Agreement"
  | "Confidentiality"
  | "Employment Contract"
  | "Commercial Lease"
  | "SaaS Agreement"
  | "IP Assignment"
  | "Joint Venture"
  | "Other";

export type SubmissionStatus =
  | "New"
  | "Needs Review"
  | "Docs Received"
  | "Redlining"
  | "Ready for Review"
  | "Complete";

export type AuditEventType =
  | "SUBMISSION_RECEIVED"
  | "STATUS_CHANGE"
  | "FILE_UPLOAD"
  | "DRIVE_FOLDER_CREATED"
  | "LEGORA_REDLINE_STARTED"
  | "LEGORA_REDLINE_COMPLETE"
  | "LEGORA_CALL"
  | "DRIVE_OP"
  | "NOTE_ADDED"
  | "NOTE_UPDATED"
  | "NEEDS_ATTENTION_FLAGGED";

export type AuditActor = "system" | "attorney" | "client";

export interface IntakeSubmission {
  id: string;
  submitted_at: string;
  first_name: string;
  last_name: string;
  email: string;
  phone?: string;
  matter_type: string;
  description?: string;
  consent?: boolean;
  uploaded_file_refs: FileRef[] | null;
  status: SubmissionStatus;
  drive_folder_url?: string | null;
  redline_file_refs?: FileRef[] | null;
  needs_attention: boolean;
  notes?: string;
  ip_hash?: string;
}

export interface AuditLogEntry {
  id: string;
  submission_id: string;
  created_at: string;
  occurred_at?: string;
  event_type: AuditEventType | string;
  actor: AuditActor | string;
  detail?: string | Record<string, unknown>;
  from_status?: string;
  to_status?: string;
}
