import { PrismaClient } from '@prisma/client';
import fs from 'node:fs';
import path from 'node:path';
import { execSync } from 'node:child_process';

const DATA_DIR = '/app/data';
const SENTINEL = path.join(DATA_DIR, '.migrations-applied');

function ensureMigrations() {
  try {
    if (!fs.existsSync(DATA_DIR)) {
      fs.mkdirSync(DATA_DIR, { recursive: true });
    }
    if (fs.existsSync(SENTINEL)) return;
    console.log('[crm] applying prisma migrations...');
    execSync('npx prisma migrate deploy', {
      cwd: '/app',
      stdio: 'inherit',
      env: { ...process.env },
    });
    fs.writeFileSync(SENTINEL, new Date().toISOString());
  } catch (err) {
    // If migrate deploy fails (e.g. no migrations directory), try db push
    // as a pragmatic fallback for first-boot seed.
    console.warn('[crm] migrate deploy failed, falling back to db push', err);
    try {
      execSync('npx prisma db push --skip-generate --accept-data-loss', {
        cwd: '/app',
        stdio: 'inherit',
        env: { ...process.env },
      });
      fs.writeFileSync(SENTINEL, new Date().toISOString());
    } catch (err2) {
      console.error('[crm] prisma db push also failed', err2);
    }
  }
}

declare global {
  // eslint-disable-next-line no-var
  var __crmPrisma: PrismaClient | undefined;
}

// Skip runtime DB setup during `next build` — prerender workers import this
// module to collect page metadata and shouldn't touch the filesystem or spawn
// prisma. Migrations run on first request (or via the startup_command on the
// pod), not at build time.
if (process.env.NEXT_PHASE !== 'phase-production-build') {
  ensureMigrations();
}

export const prisma: PrismaClient =
  global.__crmPrisma ??
  new PrismaClient({
    log: ['error', 'warn'],
  });

if (process.env.NODE_ENV !== 'production') {
  global.__crmPrisma = prisma;
}
