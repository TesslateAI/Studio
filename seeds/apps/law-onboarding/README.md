# Legal Intake + Redline Automation

A single Next.js monorepo with two route groups:
- `/` — Public client intake form (`app/(intake)`)
- `/dashboard` — Auth-gated attorney queue + detail view (`app/(dashboard)`)

---

## Quick Start

### 1. Copy environment variables

Create a `.env.local` file (never commit this):

```env
# Database
DATABASE_URL=postgresql://user:password@host:5432/dbname

# Auth (NextAuth)
NEXTAUTH_SECRET=<random 32+ char string>
NEXTAUTH_URL=http://localhost:3000
DASHBOARD_USER=attorney
DASHBOARD_PASSWORD=<your secure password>

# Google Drive (Prompt 4)
GOOGLE_SERVICE_ACCOUNT_JSON=<full JSON key as a single-line string>
GOOGLE_DRIVE_ROOT_FOLDER_ID=<Drive folder ID from URL>

# Legora (Prompt 6)
LEGORA_API_KEY=<your Legora API key>
LEGORA_API_URL=https://api.legora.io/v1
```

### 2. Run DB migrations

```bash
bun run migrate
```

### 3. (Optional) Seed test data

```bash
bun run seed
```

### 4. Start development server

```bash
bun run dev
```

---

## Credential Setup Details

### Google Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable the **Google Drive API**
4. Create a **Service Account** → create JSON key
5. Download the key file
6. **Share** your root Drive folder with the service account email (Editor)
7. Set `GOOGLE_SERVICE_ACCOUNT_JSON` to the full JSON content (one line, stringify it)
8. Set `GOOGLE_DRIVE_ROOT_FOLDER_ID` to the folder ID from its URL:  
   `https://drive.google.com/drive/folders/<FOLDER_ID_HERE>`

### Legora API

1. Log in to your [Legora](https://legora.io) account
2. Go to **Settings → API Keys** → create a new key
3. Note your API base URL (e.g. `https://api.legora.io/v1`)
4. Set templates in `config/templates.ts` to match your Legora template IDs

### NextAuth Secret

Generate a secure secret:
```bash
openssl rand -base64 32
```

---

## Routes

| Path | Description |
|------|-------------|
| `/` | Client intake form |
| `/confirmation?id=...` | Post-submission confirmation |
| `/login` | Attorney login |
| `/dashboard` | Submission queue (auth-gated) |
| `/dashboard/[id]` | Submission detail view (auth-gated) |

## API Routes

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/submit` | Submit intake form |
| GET | `/api/submissions` | List submissions (auth) |
| GET | `/api/submissions/[id]` | Submission detail + audit log (auth) |
| PATCH | `/api/submissions/[id]` | Update notes (auth) |
| POST | `/api/submissions/[id]/run-redline` | Trigger Legora redline (auth) |
| POST | `/api/submissions/[id]/mark-complete` | Mark complete (auth) |
| POST | `/api/automation/on-submission` | Internal: Drive + PDF automation |
| GET | `/api/health` | DB health check |

---

## Scripts

| Command | Description |
|---------|-------------|
| `bun run dev` | Start dev server |
| `bun run build` | Production build |
| `bun run migrate` | Run DB migrations |
| `bun run seed` | Seed test data |

---

## Architecture

```
app/
├── (intake)/          # Public — no auth
│   ├── page.tsx       # Intake form (/)
│   └── confirmation/  # Post-submit screen
├── (dashboard)/       # Auth-gated
│   ├── login/         # /login
│   └── dashboard/     # /dashboard + /dashboard/[id]
├── api/
│   ├── auth/          # NextAuth
│   ├── submit/        # Intake form POST
│   ├── submissions/   # Queue + detail CRUD
│   └── automation/    # Internal triggers
└── layout.tsx

lib/
├── db.ts              # Postgres pool + query helper
├── auth.ts            # NextAuth config
├── types.ts           # Shared TypeScript types
├── audit.ts           # Audit log writer
├── google-drive.ts    # Drive API helpers
├── pdf-generator.ts   # PDFKit intake PDF
└── legora.ts          # Legora API integration

config/
└── templates.ts       # Matter-type → Legora template map

migrations/
├── 001_create_intake_submissions.sql
└── 002_create_audit_log.sql
```

---

## Data Flow

```
Client submits form
  → POST /api/submit (validate, rate-limit, DB insert)
  → fires POST /api/automation/on-submission (async)
       → Google Drive: create folder tree
       → PDFKit: generate intake PDF
       → Upload docs to Drive
       → DB: status New → Docs Received

Attorney views /dashboard → clicks Run Redline
  → POST /api/submissions/[id]/run-redline
       → DB: status → Redlining (immediate)
       → lib/legora.ts (async):
           → POST each doc to Legora API
           → Upload redlined DOCX to Drive /Redlines/
           → DB: status → Ready for Review
           → needs_attention = true if confidence < 0.75

Attorney reviews → Mark Complete
  → POST /api/submissions/[id]/mark-complete
       → DB: status → Complete
```
