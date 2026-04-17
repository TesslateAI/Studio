import * as grpc from '@grpc/grpc-js';

export interface Budgets {
  readonly maxFiles: number;
  readonly maxTotalBytes: number;
  readonly perFileWallClockMs: number;
}

// Read env lazily via a getter so tests (and any env change between
// module load and first RPC) see the right values. Negligible overhead
// — one env lookup per RPC.
export function getBudgets(): Budgets {
  return {
    maxFiles: Number(process.env.AST_MAX_FILES ?? 1000),
    maxTotalBytes: Number(process.env.AST_MAX_TOTAL_BYTES ?? 52_428_800),
    perFileWallClockMs: Number(process.env.AST_PER_FILE_WALL_MS ?? 10_000),
  };
}

// Kept for tests / startup logging; prefer getBudgets() in request paths.
export const BUDGETS: Budgets = getBudgets();

export class BudgetError extends Error {
  readonly grpcCode: grpc.status;
  constructor(code: grpc.status, message: string) {
    super(message);
    this.name = 'BudgetError';
    this.grpcCode = code;
  }
}

export interface FileInput {
  path: string;
  content: string;
}

// Validate request shape and enforce per-request budgets. Throws
// BudgetError (mapped to gRPC status codes by the server interceptor).
export function checkRequest(files: unknown, budgets: Budgets = getBudgets()): asserts files is FileInput[] {
  if (!Array.isArray(files)) {
    throw new BudgetError(grpc.status.INVALID_ARGUMENT, 'files must be an array');
  }
  if (files.length > budgets.maxFiles) {
    throw new BudgetError(
      grpc.status.RESOURCE_EXHAUSTED,
      `request has ${files.length} files, budget is ${budgets.maxFiles}`,
    );
  }
  let total = 0;
  for (const f of files) {
    if (
      !f ||
      typeof (f as { path?: unknown }).path !== 'string' ||
      typeof (f as { content?: unknown }).content !== 'string'
    ) {
      throw new BudgetError(
        grpc.status.INVALID_ARGUMENT,
        'each file must have {path: string, content: string}',
      );
    }
    total += Buffer.byteLength((f as FileInput).content, 'utf8');
    if (total > budgets.maxTotalBytes) {
      throw new BudgetError(
        grpc.status.RESOURCE_EXHAUSTED,
        `request content exceeds ${budgets.maxTotalBytes} bytes`,
      );
    }
  }
}
