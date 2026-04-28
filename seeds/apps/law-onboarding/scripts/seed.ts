import db from "../lib/db";

const MATTER_TYPES = ["NDA", "Contractor Agreement", "Confidentiality", "Other"] as const;
const STATUSES = ["New", "Docs Received", "Redlining", "Ready for Review", "Complete"] as const;

const FIRST_NAMES = ["James", "Maria", "David", "Sarah", "Michael", "Emily", "Robert", "Jennifer"];
const LAST_NAMES = ["Anderson", "Thompson", "Garcia", "Martinez", "Wilson", "Lee", "Taylor", "Moore"];

function pick<T>(arr: readonly T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

async function seed() {
  console.log("Seeding test submissions...");

  for (let i = 0; i < 12; i++) {
    const firstName = pick(FIRST_NAMES);
    const lastName = pick(LAST_NAMES);
    const matterType = pick(MATTER_TYPES);
    const status = pick(STATUSES);
    const needsAttention = Math.random() < 0.2;

    const result = await db.query<{ id: string }>(
      `INSERT INTO intake_submissions
         (first_name, last_name, email, phone, matter_type, description,
          consent, uploaded_file_refs, status, needs_attention, ip_hash)
       VALUES ($1, $2, $3, $4, $5, $6, $7, '[]'::jsonb, $8, $9, 'seed')
       ON CONFLICT DO NOTHING
       RETURNING id`,
      [
        firstName,
        lastName,
        `${firstName.toLowerCase()}.${lastName.toLowerCase()}@example.com`,
        `555-${String(Math.floor(Math.random() * 9000) + 1000)}`,
        matterType,
        `This is a test submission for a ${matterType} matter. The client needs assistance with drafting and reviewing the agreement terms.`,
        true,
        status,
        needsAttention,
      ]
    );

    if (result.rows[0]) {
      const id = result.rows[0].id;
      await db.query(
        `INSERT INTO audit_log (submission_id, event_type, actor, to_status, detail)
         VALUES ($1, 'STATUS_CHANGE', 'system', $2, '{"note":"seeded"}'::jsonb)`,
        [id, status]
      );
      console.log(`  Created: ${lastName}, ${firstName} — ${matterType} — ${status}${needsAttention ? " ⚠️" : ""}`);
    }
  }

  console.log("\nSeed complete.");
  await db.end();
}

seed().catch((e) => {
  console.error("Seed failed:", e);
  process.exit(1);
});
