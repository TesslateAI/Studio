// Nightly digest runner. Reads the CRM SQLite DB if available, asks Llama for
// a 5-bullet summary, and writes /app/data/digest-YYYY-MM-DD.json.
//
// Invoked by the platform as a one-shot K8s Job (see app.manifest.json).

'use strict';

const fs = require('node:fs');
const path = require('node:path');

const DATA_DIR = '/app/data';
const CRM_DB = path.join(DATA_DIR, 'crm.db');

function log(...args) {
  console.log('[digest]', ...args);
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

function readStats() {
  try {
    if (!fs.existsSync(CRM_DB)) {
      log('no CRM DB at', CRM_DB, '- generating synthetic stats');
      return {
        synthetic: true,
        contacts_total: 12,
        contacts_new_today: 3,
        notes_today: 5,
        activities_today: 11,
        recent_activity: [
          { kind: 'created', contact: 'Jane Smith', at: new Date().toISOString() },
          { kind: 'note_added', contact: 'Acme Corp', at: new Date().toISOString() },
        ],
      };
    }
    const Database = require('better-sqlite3');
    const db = new Database(CRM_DB, { readonly: true, fileMustExist: true });
    const sinceIso = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
    const contactsTotal = db.prepare('SELECT COUNT(*) AS n FROM Contact').get().n;
    const contactsNew = db
      .prepare('SELECT COUNT(*) AS n FROM Contact WHERE createdAt >= ?')
      .get(sinceIso).n;
    const notesToday = db
      .prepare('SELECT COUNT(*) AS n FROM Note WHERE createdAt >= ?')
      .get(sinceIso).n;
    const activitiesToday = db
      .prepare('SELECT COUNT(*) AS n FROM Activity WHERE createdAt >= ?')
      .get(sinceIso).n;
    const recent = db
      .prepare(
        `SELECT a.kind AS kind, a.createdAt AS at, c.name AS contact
           FROM Activity a JOIN Contact c ON c.id = a.contactId
          ORDER BY a.createdAt DESC LIMIT 20`,
      )
      .all();
    db.close();
    return {
      synthetic: false,
      contacts_total: contactsTotal,
      contacts_new_today: contactsNew,
      notes_today: notesToday,
      activities_today: activitiesToday,
      recent_activity: recent,
    };
  } catch (err) {
    log('stats read failed:', err.message);
    return { synthetic: true, error: err.message };
  }
}

async function summarize(stats) {
  const apiKey = process.env.LLAMA_API_KEY;
  const baseURL = process.env.LLAMA_API_BASE;
  const model = process.env.LLAMA_MODEL || 'Llama-4-Maverick-17B-128E-Instruct-FP8';
  if (!apiKey || !baseURL) {
    log('LLAMA_API_KEY or LLAMA_API_BASE missing; returning stub summary');
    return '- (stub) no Llama creds configured\n- totals: ' + JSON.stringify(stats);
  }
  const OpenAI = require('openai');
  const client = new OpenAI.default({ apiKey, baseURL });
  const prompt = `Summarize this CRM activity feed in exactly 5 bullet points. Focus on notable new contacts, status changes, and engagement patterns. Keep each bullet under 25 words.\n\nStats: ${JSON.stringify(
    stats,
    null,
    2,
  )}`;
  const resp = await client.chat.completions.create({
    model,
    messages: [
      { role: 'system', content: 'You are a concise CRM analyst. Output only markdown bullets.' },
      { role: 'user', content: prompt },
    ],
  });
  return resp.choices?.[0]?.message?.content ?? '(no summary)';
}

async function main() {
  try {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  } catch {
    // ignore
  }
  log('start', { date: today(), invocation: process.env.INVOCATION_ID ?? null });
  const stats = readStats();
  log('stats', stats);
  const summary = await summarize(stats);
  log('summary ready, length=', summary.length);
  const out = {
    generatedAt: new Date().toISOString(),
    invocationId: process.env.INVOCATION_ID ?? null,
    summary,
    stats,
  };
  const outPath = path.join(DATA_DIR, `digest-${today()}.json`);
  fs.writeFileSync(outPath, JSON.stringify(out, null, 2));
  log('wrote', outPath);
}

main().catch((err) => {
  console.error('[digest] fatal', err);
  process.exit(1);
});
