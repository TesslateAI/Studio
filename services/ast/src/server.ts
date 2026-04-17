import * as grpc from '@grpc/grpc-js';
import type { sendUnaryData, ServerUnaryCall } from '@grpc/grpc-js';

import {
  AstServiceDefinition,
  SERVICE_NAME,
  type PingResponse,
  type IndexRequest,
  type IndexResponse,
  type ApplyDiffRequest,
  type ApplyDiffResponse,
} from './service_desc.js';
import { createPool, warmPool, runFile } from './pool.js';
import { BUDGETS, BudgetError, checkRequest, type FileInput } from './budgets.js';
import { log } from './logger.js';
import type { DiffRequest, ApplyDiffResult } from './ops/apply_diff.js';
import type { IndexFileResult } from './ops/index.js';
import { HealthService, HealthServiceDefinition, SERVING_STATUS } from './health.js';

const MAX_MESSAGE_SIZE = 64 * 1024 * 1024;

const GRPC_CHANNEL_OPTIONS: grpc.ChannelOptions = {
  'grpc.max_send_message_length': MAX_MESSAGE_SIZE,
  'grpc.max_receive_message_length': MAX_MESSAGE_SIZE,
  'grpc.keepalive_time_ms': 30_000,
  'grpc.keepalive_timeout_ms': 10_000,
  'grpc.keepalive_permit_without_calls': 1,
  'grpc.http2.max_pings_without_data': 0,
};

function toGrpcError(err: unknown): { code: grpc.status; details: string } {
  if (err instanceof BudgetError) {
    return { code: err.grpcCode, details: err.message };
  }
  if (err && typeof err === 'object' && 'grpcCode' in err && typeof (err as { grpcCode: unknown }).grpcCode === 'number') {
    return {
      code: (err as { grpcCode: grpc.status }).grpcCode,
      details: String((err as { message?: unknown }).message ?? err),
    };
  }
  if (err instanceof Error && err.name === 'AbortError') {
    return { code: grpc.status.DEADLINE_EXCEEDED, details: err.message };
  }
  return { code: grpc.status.INTERNAL, details: String((err as Error)?.message ?? err) };
}

function grpcStatusName(code: grpc.status): string {
  const entry = Object.entries(grpc.status).find(([, v]) => v === code);
  return entry ? entry[0] : String(code);
}

type Handler<Req, Res> = (req: Req, call: ServerUnaryCall<Req, Res>) => Promise<Res>;

function wrapHandler<Req, Res>(method: string, handler: Handler<Req, Res>) {
  return (call: ServerUnaryCall<Req, Res>, callback: sendUnaryData<Res>) => {
    const started = Date.now();
    const req = call.request;
    let bytesIn = 0;
    try {
      bytesIn = Buffer.byteLength(JSON.stringify(req ?? {}), 'utf8');
    } catch {
      // ignore
    }

    handler(req, call)
      .then((result) => {
        const bytesOut = Buffer.byteLength(JSON.stringify(result ?? {}), 'utf8');
        log.info('rpc', {
          method,
          bytes_in: bytesIn,
          bytes_out: bytesOut,
          duration_ms: Date.now() - started,
          outcome: 'ok',
        });
        callback(null, result);
      })
      .catch((err: unknown) => {
        const { code, details } = toGrpcError(err);
        log.warn('rpc', {
          method,
          bytes_in: bytesIn,
          duration_ms: Date.now() - started,
          outcome: 'error',
          error_code: grpcStatusName(code),
          error: details,
        });
        callback({ code, details } as grpc.ServiceError);
      });
  };
}

export interface Server {
  grpcServer: grpc.Server;
  shutdown: (signal: string) => Promise<void>;
}

export async function startServer(): Promise<Server> {
  // Read env at call time (not module-load time) so tests can set
  // AST_BIND_PORT after importing the module.
  const host = process.env.AST_BIND_HOST ?? '0.0.0.0';
  const port = Number(process.env.AST_BIND_PORT ?? 9000);

  const pool = createPool();
  await warmPool(pool);

  const server = new grpc.Server(GRPC_CHANNEL_OPTIONS);

  // ── Ping ────────────────────────────────────────────────────────
  // Runs on the MAIN thread. Never dispatched to Piscina so pool
  // saturation can never fail the readiness probe.
  const ping: Handler<Record<string, never>, PingResponse> = async () => ({
    ok: true,
    pid: process.pid,
    service: SERVICE_NAME,
    worker_count: pool.options.maxThreads as number,
    queue_depth: pool.queueSize,
    active: pool.utilization,
  });

  // ── Index ────────────────────────────────────────────────────────
  const index: Handler<IndexRequest, IndexResponse> = async (req) => {
    const files = (req?.files ?? []) as FileInput[];
    checkRequest(files);

    const outFiles: IndexResponse['files'] = new Array(files.length);
    const mergedIndex: Record<string, unknown> = {};
    const seenOids = new Set<string>();

    const results = await Promise.all(
      files.map((file, idx) => {
        const knownOids = Array.from(seenOids);
        return runFile(pool, { op: 'index_file', file, known_oids: knownOids }).then(
          (r) => [idx, r as IndexFileResult] as const,
        );
      }),
    );
    for (const [idx, r] of results.sort((a, b) => a[0] - b[0])) {
      const entry: IndexResponse['files'][number] = {
        path: r.path,
        content: r.content,
        modified: r.modified,
      };
      if (r.error) entry.error = r.error;
      outFiles[idx] = entry;
      for (const [oid, meta] of Object.entries(r.index || {})) {
        if (seenOids.has(oid)) continue;
        seenOids.add(oid);
        mergedIndex[oid] = meta;
      }
    }
    return { files: outFiles, index: mergedIndex };
  };

  // ── ApplyDiff ────────────────────────────────────────────────────
  const applyDiff: Handler<ApplyDiffRequest, ApplyDiffResponse> = async (req) => {
    const files = (req?.files ?? []) as FileInput[];
    const requests = req?.requests ?? [];
    checkRequest(files);
    if (!Array.isArray(requests)) {
      throw new BudgetError(grpc.status.INVALID_ARGUMENT, 'requests must be an array');
    }

    const requestsByOid: [string, DiffRequest][] = [];
    for (const r of requests) {
      if (r && typeof (r as { oid?: unknown }).oid === 'string') {
        requestsByOid.push([(r as { oid: string }).oid, r as unknown as DiffRequest]);
      }
    }

    const outFiles = (await Promise.all(
      files.map((file) =>
        runFile(pool, {
          op: 'apply_diff_file',
          file,
          requests_by_oid: requestsByOid,
        }).then((r) => r as ApplyDiffResult),
      ),
    )) as ApplyDiffResponse['files'];
    return { files: outFiles };
  };

  server.addService(AstServiceDefinition, {
    Ping: wrapHandler('Ping', ping),
    Index: wrapHandler('Index', index),
    ApplyDiff: wrapHandler('ApplyDiff', applyDiff),
  });

  // Standard grpc.health.v1.Health service — k8s grpc probes speak
  // this protocol. Register "" (overall) and our service name so both
  // forms of the probe (with or without service filter) succeed.
  const health = new HealthService();
  health.setStatus('', SERVING_STATUS.SERVING);
  health.setStatus(SERVICE_NAME, SERVING_STATUS.SERVING);
  server.addService(HealthServiceDefinition, health.handlers());

  await new Promise<number>((resolve, reject) => {
    server.bindAsync(`${host}:${port}`, grpc.ServerCredentials.createInsecure(), (err, boundPort) => {
      if (err) return reject(err);
      log.info('server.listening', {
        host,
        port: boundPort,
        service: SERVICE_NAME,
        budgets: BUDGETS,
      });
      resolve(boundPort);
    });
  });

  const shutdown = async (signal: string): Promise<void> => {
    log.info('server.shutdown', { signal });
    await new Promise<void>((resolve) => {
      server.tryShutdown(() => resolve());
    });
    await pool.destroy();
  };

  return { grpcServer: server, shutdown };
}

// Entry point: only run when invoked directly (not when imported by tests).
const isEntryPoint =
  process.argv[1] && process.argv[1].endsWith('server.js');

if (isEntryPoint) {
  startServer()
    .then((srv) => {
      const handleSignal = (signal: string) => {
        srv.shutdown(signal).finally(() => process.exit(0));
        setTimeout(() => {
          log.warn('server.force_exit', { signal });
          process.exit(1);
        }, 15_000).unref();
      };
      process.on('SIGTERM', () => handleSignal('SIGTERM'));
      process.on('SIGINT', () => handleSignal('SIGINT'));
    })
    .catch((err: unknown) => {
      log.error('server.boot_failed', {
        error: String((err as Error)?.stack ?? err),
      });
      process.exit(1);
    });
}
