import { readFileSync } from "fs";
import { join } from "path";
import db from "../lib/db";

async function migrate() {
  const migrationFiles = [
    "001_create_intake_submissions.sql",
    "002_create_audit_log.sql",
  ];

  console.log("Running migrations...");

  for (const file of migrationFiles) {
    const filePath = join(process.cwd(), "migrations", file);
    const sql = readFileSync(filePath, "utf-8");
    console.log(`  → ${file}`);
    await db.query(sql);
  }

  console.log("Migrations complete.");
  await db.end();
}

migrate().catch((err) => {
  console.error("Migration failed:", err);
  process.exit(1);
});
