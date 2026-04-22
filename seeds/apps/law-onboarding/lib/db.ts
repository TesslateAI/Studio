import { Pool } from "pg";

declare global {
  var _pgPool: Pool | undefined;
}

function createPool(): Pool {
  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) {
    throw new Error("DATABASE_URL environment variable is not set");
  }
  return new Pool({
    connectionString,
    max: 10,
    idleTimeoutMillis: 30000,
    connectionTimeoutMillis: 2000,
    ssl:
      process.env.NODE_ENV === "production"
        ? { rejectUnauthorized: false }
        : false,
  });
}

const db: Pool =
  process.env.NODE_ENV === "development"
    ? (globalThis._pgPool ??= createPool())
    : createPool();

export default db;
export { Pool };

export async function query<T = Record<string, unknown>>(
  text: string,
  params?: unknown[]
) {
  return db.query<T>(text, params);
}
