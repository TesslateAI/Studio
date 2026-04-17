import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import * as PiscinaNs from 'piscina';

import { BUDGETS } from './budgets.js';
import { log } from './logger.js';
import type { WorkerTask, WorkerResult } from './worker.js';

// piscina ships its class as both a default export and a named export.
// Normalize to a usable constructor + type.
type PiscinaInstance = InstanceType<typeof PiscinaNs.Piscina>;
const Piscina = PiscinaNs.Piscina;

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export function createPool(): PiscinaInstance {
  // Thread count must match the container's CPU limit, not the node's
  // parallelism — running 16 threads on a 2-CPU cgroup starves the
  // event loop and fails health probes. Overlays set AST_POOL_THREADS
  // explicitly; the fallback only fires in dev / outside Kubernetes.
  const threads =
    Number(process.env.AST_POOL_THREADS) ||
    (typeof os.availableParallelism === 'function' ? os.availableParallelism() : os.cpus().length);

  // Per-worker V8 heap cap. Bounds Babel's worst-case memory use so
  // one pathological parse can't OOM the whole container.
  const maxOldMb = Number(process.env.AST_WORKER_MAX_OLD_MB ?? 256);
  const maxYoungMb = Number(process.env.AST_WORKER_MAX_YOUNG_MB ?? 64);
  const codeRangeMb = Number(process.env.AST_WORKER_CODE_RANGE_MB ?? 32);

  const pool = new Piscina({
    filename: path.join(__dirname, 'worker.js'),
    minThreads: threads,
    maxThreads: threads,
    idleTimeout: Infinity,
    // Each task is one file with a hard wall-clock cap; exceeding it
    // terminates ONLY that worker thread, not the whole pool.
    concurrentTasksPerWorker: 1,
    resourceLimits: {
      maxOldGenerationSizeMb: maxOldMb,
      maxYoungGenerationSizeMb: maxYoungMb,
      codeRangeSizeMb: codeRangeMb,
    },
  });

  log.info('pool.created', {
    threads,
    max_old_mb: maxOldMb,
    max_young_mb: maxYoungMb,
    code_range_mb: codeRangeMb,
  });
  return pool;
}

// Warm every worker thread by running one warmup task per thread
// concurrently. Piscina spreads tasks across idle workers, so with
// concurrentTasksPerWorker=1 this reliably hits each thread once.
export async function warmPool(pool: PiscinaInstance): Promise<void> {
  const threads = pool.options.maxThreads as number;
  const started = Date.now();
  await Promise.all(
    Array.from({ length: threads }, () => pool.run({ op: 'warmup' } satisfies WorkerTask)),
  );
  log.info('pool.warmed', { threads, duration_ms: Date.now() - started });
}

export interface RunFileOptions {
  timeoutMs?: number;
}

export function runFile(
  pool: PiscinaInstance,
  task: WorkerTask,
  { timeoutMs = BUDGETS.perFileWallClockMs }: RunFileOptions = {},
): Promise<WorkerResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new Error('per-file timeout')), timeoutMs);
  return (pool.run(task, { signal: controller.signal }) as Promise<WorkerResult>).finally(() =>
    clearTimeout(timer),
  );
}
