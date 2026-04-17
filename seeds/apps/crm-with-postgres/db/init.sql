-- Cosmetic init script. Not auto-loaded — the API container creates the
-- contacts table idempotently at startup. Mount this at
-- /docker-entrypoint-initdb.d/init.sql to have Postgres run it on first boot.

CREATE TABLE IF NOT EXISTS contacts (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
