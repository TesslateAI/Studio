/**
 * Demo data layer — used when DATABASE_URL is not set.
 * Returns realistic mock submissions so the UI is fully explorable.
 */

import type { IntakeSubmission, AuditLogEntry } from "@/lib/types";

export const DEMO_MODE = !process.env.DATABASE_URL || process.env.DATABASE_URL === "${DATABASE_URL}";

export const demoSubmissions: IntakeSubmission[] = [
  {
    id: "demo-001",
    submitted_at: new Date(Date.now() - 1 * 60 * 60 * 1000).toISOString(),
    first_name: "Margaret",
    last_name: "Chen",
    email: "m.chen@email.com",
    phone: "415-555-0192",
    matter_type: "NDA",
    description:
      "I need a mutual NDA reviewed before signing with a new technology partner. They sent over their standard template which appears to have some aggressive IP assignment clauses I am concerned about.",
    status: "Needs Review",
    needs_attention: true,
    drive_folder_url: null,
    uploaded_file_refs: [{ name: "mutual_nda_draft_v2.pdf", drive_id: "demo-file-1", mime: "application/pdf", size: 204800 }],
    redline_file_refs: null,
    notes: "Client flagged sections 4.3 and 7.1 as concerns.",
  },
  {
    id: "demo-002",
    submitted_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    first_name: "James",
    last_name: "Okafor",
    email: "jokafor@startupco.io",
    phone: "650-555-0347",
    matter_type: "Employment Contract",
    description:
      "CEO contract review for Series A startup. Includes equity compensation, termination clauses, and non-compete provisions. Need quick turnaround as board meeting is Thursday.",
    status: "Redlining",
    needs_attention: false,
    drive_folder_url: "https://drive.google.com/drive/folders/demo",
    uploaded_file_refs: [
      { name: "ceo_agreement_draft.docx", drive_id: "demo-file-2", mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", size: 98304 },
      { name: "equity_schedule.pdf", drive_id: "demo-file-3", mime: "application/pdf", size: 51200 },
    ],
    redline_file_refs: [{ name: "ceo_agreement_REDLINE.pdf", drive_id: "demo-redline-1", mime: "application/pdf", size: 115200 }],
    notes: "",
  },
  {
    id: "demo-003",
    submitted_at: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(),
    first_name: "Sarah",
    last_name: "Whitmore",
    email: "swhitmore@consulting.net",
    phone: "312-555-0811",
    matter_type: "Commercial Lease",
    description:
      "Office space lease for expanding consulting practice. 3,500 sq ft, 5-year term with option to renew. Landlord is requesting personal guarantee which I want to negotiate.",
    status: "Ready for Review",
    needs_attention: false,
    drive_folder_url: "https://drive.google.com/drive/folders/demo",
    uploaded_file_refs: [
      { name: "office_lease_v1.pdf", drive_id: "demo-file-4", mime: "application/pdf", size: 409600 },
    ],
    redline_file_refs: [{ name: "office_lease_REDLINE.pdf", drive_id: "demo-redline-2", mime: "application/pdf", size: 440320 }],
    notes: "Pay special attention to CAM charges and termination rights.",
  },
  {
    id: "demo-004",
    submitted_at: new Date(Date.now() - 12 * 60 * 60 * 1000).toISOString(),
    first_name: "David",
    last_name: "Nakamura",
    email: "dnakamura@venturecap.com",
    phone: "212-555-0456",
    matter_type: "SaaS Agreement",
    description:
      "Enterprise SaaS subscription agreement with Fortune 500 client. $2M ARR deal. They want significant modifications to the standard MSA especially around data security, SLAs, and indemnification.",
    status: "Docs Received",
    needs_attention: false,
    drive_folder_url: null,
    uploaded_file_refs: [
      { name: "enterprise_msa_redline_client.docx", drive_id: "demo-file-5", mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", size: 163840 },
      { name: "security_addendum.pdf", drive_id: "demo-file-6", mime: "application/pdf", size: 81920 },
      { name: "dpa_draft.pdf", drive_id: "demo-file-7", mime: "application/pdf", size: 65536 },
    ],
    redline_file_refs: null,
    notes: "",
  },
  {
    id: "demo-005",
    submitted_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
    first_name: "Patricia",
    last_name: "Nguyen",
    email: "pnguyen@medtech.com",
    phone: "617-555-0234",
    matter_type: "IP Assignment",
    description:
      "Technology transfer agreement for medical device patent portfolio. Acquiring 12 patents from university spin-out. Need thorough review of representations and warranties section.",
    status: "Complete",
    needs_attention: false,
    drive_folder_url: "https://drive.google.com/drive/folders/demo",
    uploaded_file_refs: [
      { name: "patent_assignment_agreement.pdf", drive_id: "demo-file-8", mime: "application/pdf", size: 307200 },
    ],
    redline_file_refs: [{ name: "patent_assignment_FINAL.pdf", drive_id: "demo-redline-3", mime: "application/pdf", size: 319488 }],
    notes: "Review completed. Client approved final version.",
  },
  {
    id: "demo-006",
    submitted_at: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
    first_name: "Robert",
    last_name: "Fitzpatrick",
    email: "rfitz@realestate.com",
    phone: "602-555-0789",
    matter_type: "Joint Venture",
    description:
      "Real estate JV agreement for mixed-use development project. Three partners each contributing capital and expertise. Complex profit-sharing and decision-making provisions need to be balanced.",
    status: "New",
    needs_attention: true,
    drive_folder_url: null,
    uploaded_file_refs: [],
    redline_file_refs: null,
    notes: "",
  },
];

export const demoAuditLogs: Record<string, AuditLogEntry[]> = {
  "demo-001": [
    { id: "al-001", submission_id: "demo-001", actor: "system", event_type: "SUBMISSION_RECEIVED", detail: "New intake submission received via public form.", created_at: new Date(Date.now() - 1 * 60 * 60 * 1000).toISOString() },
    { id: "al-002", submission_id: "demo-001", actor: "system", event_type: "NEEDS_ATTENTION_FLAGGED", detail: "Flagged for attorney review: urgent timeline noted in description.", created_at: new Date(Date.now() - 59 * 60 * 1000).toISOString() },
  ],
  "demo-002": [
    { id: "al-003", submission_id: "demo-002", actor: "system", event_type: "SUBMISSION_RECEIVED", detail: "New intake submission received via public form.", created_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString() },
    { id: "al-004", submission_id: "demo-002", actor: "system", event_type: "DRIVE_FOLDER_CREATED", detail: "Google Drive folder created and files uploaded.", created_at: new Date(Date.now() - 3 * 60 * 60 * 1000 + 5000).toISOString() },
    { id: "al-005", submission_id: "demo-002", actor: "attorney", event_type: "STATUS_CHANGE", detail: "Status changed: Docs Received → Redlining", created_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString() },
    { id: "al-006", submission_id: "demo-002", actor: "system", event_type: "LEGORA_REDLINE_STARTED", detail: "Legora AI redline analysis initiated.", created_at: new Date(Date.now() - 2 * 60 * 60 * 1000 + 1000).toISOString() },
  ],
  "demo-003": [
    { id: "al-007", submission_id: "demo-003", actor: "system", event_type: "SUBMISSION_RECEIVED", detail: "New intake submission received via public form.", created_at: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString() },
    { id: "al-008", submission_id: "demo-003", actor: "system", event_type: "DRIVE_FOLDER_CREATED", detail: "Google Drive folder created and files uploaded.", created_at: new Date(Date.now() - 6 * 60 * 60 * 1000 + 5000).toISOString() },
    { id: "al-009", submission_id: "demo-003", actor: "system", event_type: "LEGORA_REDLINE_COMPLETE", detail: "Legora returned redlined document. Confidence: 0.91.", created_at: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString() },
    { id: "al-010", submission_id: "demo-003", actor: "attorney", event_type: "STATUS_CHANGE", detail: "Status changed: Redlining → Ready for Review", created_at: new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString() },
    { id: "al-011", submission_id: "demo-003", actor: "attorney", event_type: "NOTE_ADDED", detail: "Note updated by attorney.", created_at: new Date(Date.now() - 3.5 * 60 * 60 * 1000).toISOString() },
  ],
  "demo-004": [
    { id: "al-012", submission_id: "demo-004", actor: "system", event_type: "SUBMISSION_RECEIVED", detail: "New intake submission received via public form.", created_at: new Date(Date.now() - 12 * 60 * 60 * 1000).toISOString() },
  ],
  "demo-005": [
    { id: "al-013", submission_id: "demo-005", actor: "system", event_type: "SUBMISSION_RECEIVED", detail: "New intake submission received.", created_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString() },
    { id: "al-014", submission_id: "demo-005", actor: "system", event_type: "DRIVE_FOLDER_CREATED", detail: "Google Drive folder created.", created_at: new Date(Date.now() - 24 * 60 * 60 * 1000 + 5000).toISOString() },
    { id: "al-015", submission_id: "demo-005", actor: "system", event_type: "LEGORA_REDLINE_COMPLETE", detail: "Legora returned redlined document. Confidence: 0.94.", created_at: new Date(Date.now() - 22 * 60 * 60 * 1000).toISOString() },
    { id: "al-016", submission_id: "demo-005", actor: "attorney", event_type: "STATUS_CHANGE", detail: "Status changed: Ready for Review → Complete", created_at: new Date(Date.now() - 20 * 60 * 60 * 1000).toISOString() },
  ],
  "demo-006": [
    { id: "al-017", submission_id: "demo-006", actor: "system", event_type: "SUBMISSION_RECEIVED", detail: "New intake submission received via public form.", created_at: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString() },
    { id: "al-018", submission_id: "demo-006", actor: "system", event_type: "NEEDS_ATTENTION_FLAGGED", detail: "Flagged: no documents uploaded, client mentioned urgent deadline.", created_at: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000 + 3000).toISOString() },
  ],
};
