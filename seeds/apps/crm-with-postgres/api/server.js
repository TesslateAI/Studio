// Tiny Express API backed by Postgres.
// DATABASE_URL is injected by the platform via a ContainerConnection
// (env_injection from the `db` service container).

const express = require("express");
const { Pool } = require("pg");

const PORT = parseInt(process.env.PORT || "3001", 10);
const DATABASE_URL = process.env.DATABASE_URL;

if (!DATABASE_URL) {
  console.error("DATABASE_URL is not set; refusing to start.");
  process.exit(1);
}

const pool = new Pool({ connectionString: DATABASE_URL });

async function ensureSchema() {
  // Idempotent — runs every boot. Cheap on already-created tables.
  await pool.query(`
    CREATE TABLE IF NOT EXISTS contacts (
      id SERIAL PRIMARY KEY,
      name TEXT NOT NULL,
      email TEXT NOT NULL UNIQUE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
  `);
}

const app = express();
app.use(express.json());

app.get("/healthz", (_req, res) => res.json({ ok: true }));

app.get("/contacts", async (_req, res) => {
  try {
    const r = await pool.query(
      "SELECT id, name, email, created_at FROM contacts ORDER BY id ASC LIMIT 100"
    );
    res.json(r.rows);
  } catch (e) {
    res.status(500).json({ error: String(e.message || e) });
  }
});

app.post("/contacts", async (req, res) => {
  const { name, email } = req.body || {};
  if (!name || !email) {
    return res.status(400).json({ error: "name and email required" });
  }
  try {
    const r = await pool.query(
      "INSERT INTO contacts (name, email) VALUES ($1, $2) RETURNING id, name, email, created_at",
      [name, email]
    );
    res.status(201).json(r.rows[0]);
  } catch (e) {
    res.status(500).json({ error: String(e.message || e) });
  }
});

async function main() {
  // Retry schema bootstrap — Postgres may not be ready on first boot.
  let attempts = 0;
  while (true) {
    try {
      await ensureSchema();
      break;
    } catch (e) {
      attempts += 1;
      if (attempts > 30) {
        console.error("ensureSchema failed after 30 attempts:", e.message);
        process.exit(1);
      }
      console.warn(`db not ready (attempt ${attempts}): ${e.message}`);
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  app.listen(PORT, "0.0.0.0", () => {
    console.log(`api listening on :${PORT}`);
  });
}

main();
