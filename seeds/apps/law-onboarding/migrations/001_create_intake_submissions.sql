CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS intake_submissions (
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

CREATE INDEX IF NOT EXISTS idx_intake_submissions_status
  ON intake_submissions (status);

CREATE INDEX IF NOT EXISTS idx_intake_submissions_submitted_at
  ON intake_submissions (submitted_at DESC);
