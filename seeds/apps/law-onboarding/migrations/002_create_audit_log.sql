CREATE TABLE IF NOT EXISTS audit_log (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id   UUID REFERENCES intake_submissions(id) ON DELETE CASCADE,
  occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  event_type      TEXT NOT NULL,
  actor           TEXT NOT NULL,
  from_status     TEXT,
  to_status       TEXT,
  detail          JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_log_submission_id
  ON audit_log (submission_id);

CREATE INDEX IF NOT EXISTS idx_audit_log_occurred_at
  ON audit_log (occurred_at DESC);
