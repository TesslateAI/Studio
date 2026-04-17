import { indexFile, type IndexFileResult } from './ops/index.js';
import { applyDiffFile, type ApplyDiffResult, type DiffRequest } from './ops/apply_diff.js';
import type { FileInput } from './budgets.js';

// Piscina worker. One task = one file. Static imports at the top of
// this file are what warm each worker's own V8 JIT cache.

const WARMUP_SOURCE = `
import React from 'react';
export function Hello({name}: {name: string}) {
  return <div className="p-4"><span>{name}</span></div>;
}
`;

export type WarmupResult = { ok: true };

export type WorkerTask =
  | { op: 'warmup' }
  | { op: 'index_file'; file: FileInput; known_oids?: string[] }
  | { op: 'apply_diff_file'; file: FileInput; requests_by_oid?: [string, DiffRequest][] };

export type WorkerResult = WarmupResult | IndexFileResult | ApplyDiffResult;

function warmup(): WarmupResult {
  const globalOids = new Set<string>();
  indexFile({ path: '__warmup.tsx', content: WARMUP_SOURCE }, globalOids);
  applyDiffFile({ path: '__warmup.tsx', content: WARMUP_SOURCE }, new Map());
  return { ok: true };
}

export default function run(task: WorkerTask): WorkerResult {
  switch (task.op) {
    case 'warmup':
      return warmup();
    case 'index_file': {
      const globalOids = new Set(task.known_oids ?? []);
      return indexFile(task.file, globalOids);
    }
    case 'apply_diff_file': {
      const byOid = new Map(task.requests_by_oid ?? []);
      return applyDiffFile(task.file, byOid);
    }
    default: {
      const _exhaustive: never = task;
      throw new Error(`unknown op: ${String((_exhaustive as { op?: unknown }).op)}`);
    }
  }
}
