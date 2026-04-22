# Legal Intake + Redline Automation — Master Build Prompts

> Reference document for all 7 build prompts. See TESSLATE.md for project config.

---

## Architecture

Single Next.js monorepo, two route groups:
- `(intake)` → public client intake form at `/`
- `(dashboard)` → auth-gated attorney dashboard at `/dashboard`

**Single container, one port (3000).** No need to split — secrets are shared, deployments simple.

---

## Prompt 1 ✅ — Foundation: Data Layer + Project Scaffold

**Goal:** Stand up the project with two route groups and the database schema.

**Outputs:**
- Intake app (route group) — "Coming Soon" page
- Dashboard app (route group) — "Login" stub
- `intake_submissions` table created
- `audit_log` table created
- Both route groups can query the DB

**Files built:**
- `migrations/001_create_intake_submissions.sql`
- `migrations/002_create_audit_log.sql`
- `lib/db.ts`
- `lib/types.ts`
- `lib/audit.ts`
- `scripts/migrate.ts`
- `app/(intake)/page.tsx`
- `app/(intake)/layout.tsx`
- `app/(dashboard)/login/page.tsx`
- `app/(dashboard)/dashboard/page.tsx`
- `app/(dashboard)/layout.tsx`
- `app/api/health/route.ts`

---

## Prompt 2 — Client Intake Form (Frontend + Submit API)

**Goal:** Fully functional intake form with file upload and confirmation screen.

**Preconditions:** Prompt 1 complete; DB accessible

**Outputs / Acceptance Criteria:**
- Form captures: first_name, last_name, email, phone, matter_type, description, consent checkbox
- Multi-file upload (.pdf, .docx only, max 10MB each)
- On submit: row inserted into `intake_submissions` with `status=New`
- Confirmation screen shows submission ID and "We'll be in touch" message
- Rate limiting: max 5 submissions per IP per hour
- No PII in any URL

**Files to build:**
- `app/(intake)/page.tsx` — intake form UI (replaces stub)
- `app/(intake)/confirmation/page.tsx`
- `app/api/submit/route.ts` — POST handler, DB insert, file temp-store

---

## Prompt 3 — Attorney Dashboard (Auth + Queue View)

**Goal:** Auth-gated dashboard showing the submission queue with status pipeline.

**Preconditions:** Prompt 1 complete; submissions exist in DB (can seed test data)

**Outputs / Acceptance Criteria:**
- `/login` page with username/password
- `/dashboard` (protected) shows table of all submissions
- Columns: Name, Matter Type, Submitted At, Status, Needs Attention flag
- Clickable rows navigate to detail view (stub for Prompt 5)
- Status badge color coding: New=gray, Redlining=yellow, Ready for Review=blue, Complete=green
- Session cookie, no PII in URL

**Files to build:**
- NextAuth setup (`app/api/auth/[...nextauth]/route.ts`)
- `app/(dashboard)/login/page.tsx` (replaces stub)
- `app/(dashboard)/dashboard/page.tsx` (replaces stub)
- `app/api/submissions/route.ts` — GET list

---

## Prompt 4 — Google Drive Integration + Automation Trigger 1

**Goal:** On new submission, create Drive folder tree, generate intake PDF, upload all files.

**Preconditions:** Prompts 1 + 2 complete; Google Service Account credentials in secrets

**Outputs / Acceptance Criteria:**
- Submitting intake form triggers automation (async, non-blocking)
- Drive folder created: `/Clients/[LastName]_[FirstName]/Intake/` and `/Redlines/`
- PDF of intake answers uploaded to `/Intake/intake_form.pdf`
- Client-uploaded docs copied to `/Intake/`
- `drive_folder_url` populated on the submission row
- Status advances: New → Docs Received
- Audit log entry created for each status change

**Credentials needed:**
- `GOOGLE_SERVICE_ACCOUNT_JSON`
- `GOOGLE_DRIVE_ROOT_FOLDER_ID`

**Files to build:**
- `app/api/automation/on-submission/route.ts`
- `lib/google-drive.ts`
- `lib/pdf-generator.ts`

---

## Prompt 5 — Dashboard Detail View + Action Buttons

**Goal:** Full detail view for each submission; plumb "Run Redline" and "Mark Complete" buttons.

**Preconditions:** Prompts 3 + 4 complete

**Outputs / Acceptance Criteria:**
- `/dashboard/[id]` shows all intake answers, Drive folder link, file list, status badge, notes field
- "Run Redline" button visible when status is `Docs Received` or `Ready for Review`
- "Mark Complete" button visible when status is `Ready for Review` or `Redlining`
- Buttons call respective API routes (stubs OK if Legora not yet wired)
- Optimistic UI update on status change (no full reload)

**Files to build:**
- `app/(dashboard)/dashboard/[id]/page.tsx`
- `app/api/submissions/[id]/route.ts` — GET detail, PATCH notes
- `app/api/submissions/[id]/mark-complete/route.ts`
- `app/api/submissions/[id]/run-redline/route.ts` (stub)

---

## Prompt 6 — Legora Integration + Automation Trigger 2

**Goal:** Wire "Run Redline" to Legora API; save outputs to Drive; update status.

**Preconditions:** Prompt 5 complete; Legora API key in secrets; templates in Drive

**Outputs / Acceptance Criteria:**
- "Run Redline" sets status → Redlining immediately
- Each `/Intake/` doc sent to Legora with correct template
- Legora response saved to `/Redlines/[filename]_redlined.docx`
- `redline_file_refs` array updated on submission row
- Status → Ready for Review when all docs processed
- On Legora error or confidence < threshold: `needs_attention = true`
- Audit log entry for every Legora call

**Credentials needed:**
- `LEGORA_API_KEY`
- `LEGORA_API_URL`

**Files to build:**
- `lib/legora.ts`
- Wire `run-redline/route.ts` to use `lib/legora.ts`
- `config/templates.ts`

---

## Prompt 7 — Hardening: Rate Limiting, Audit UI, E2E Test

**Goal:** Run one real end-to-end test client through the full system; fix gaps.

**Outputs / Acceptance Criteria:**
- Submit a real test intake → Drive folder → trigger redline → output in dashboard
- Audit log visible in dashboard (collapsible panel on detail view)
- `needs_attention` banner tested with forced Legora error
- Rate limiting verified (6th submission from same IP within 1hr rejected)
- No PII in any URL, log line, or error message
- "Mark Complete" sets status and records audit entry

**Files to build:**
- Audit log UI component
- Bug fixes from E2E run
- `README.md` with credential setup instructions

---

## Data Contracts

### `intake_submissions`
```sql
CREATE TABLE intake_submissions (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  submitted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  first_name          TEXT NOT NULL,
  last_name           TEXT NOT NULL,
  email               TEXT NOT NULL,
  phone               TEXT,
  matter_type         TEXT NOT NULL CHECK (
                        matter_type IN ('NDA','Contractor Agreement',
                                        'Confidentiality','Other')
                      ),
  description         TEXT NOT NULL,
  consent             BOOLEAN NOT NULL DEFAULT false,
  uploaded_file_refs  JSONB NOT NULL DEFAULT '[]',
  status              TEXT NOT NULL DEFAULT 'New'
                        CHECK (status IN (
                          'New','Docs Received','Redlining',
                          'Ready for Review','Complete'
                        )),
  drive_folder_url    TEXT,
  redline_file_refs   JSONB DEFAULT '[]',
  needs_attention     BOOLEAN NOT NULL DEFAULT false,
  notes               TEXT,
  ip_hash             TEXT
);
```

### `audit_log`
```sql
CREATE TABLE audit_log (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id   UUID REFERENCES intake_submissions(id) ON DELETE CASCADE,
  occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  event_type      TEXT NOT NULL,
  actor           TEXT NOT NULL,
  from_status     TEXT,
  to_status       TEXT,
  detail          JSONB
);
```

### FileRef (JSONB element)
```ts
type FileRef = {
  id: string;
  name: string;
  size: number;
  mime: string;
  drive_url?: string;
  legora_confidence?: number;
}
```

---

## Integration Checklist

| Integration | Credential | Prompt |
|-------------|-----------|--------|
| Google Drive | `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_DRIVE_ROOT_FOLDER_ID` | 4 |
| Legora | `LEGORA_API_KEY`, `LEGORA_API_URL` | 6 |
| Auth | `NEXTAUTH_SECRET`, `DASHBOARD_USER`, `DASHBOARD_PASSWORD` | 3 |

---

## Out of Scope for V1

- Email delivery of redline package
- Multi-user / role-based auth
- Client portal
- Billing / payment
- Mobile-native app
- Bulk intake
