import { describe, it, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as grpc from '@grpc/grpc-js';

import { startServer, type Server } from '../src/server.js';
import { AstServiceDefinition } from '../src/service_desc.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE_PATH = path.resolve(__dirname, '../..', 'test/fixture.tsx');
const FIXTURE = readFileSync(FIXTURE_PATH, 'utf8');

const ADDRESS = '127.0.0.1:19010';
const AstClient = grpc.makeGenericClientConstructor(AstServiceDefinition, 'AstService');

let server: Server;
let client: grpc.Client;

function callUnary<Req, Res>(method: string, req: Req, deadlineMs = 10_000): Promise<Res> {
  return new Promise((resolve, reject) => {
    const deadline = new Date(Date.now() + deadlineMs);
    (client as unknown as Record<
      string,
      (r: Req, opts: { deadline: Date }, cb: (err: grpc.ServiceError | null, res: Res) => void) => void
    >)[method]!(req, { deadline }, (err, res) => (err ? reject(err) : resolve(res)));
  });
}

describe('AST gRPC server end-to-end', { concurrency: false }, () => {
  before(async () => {
    process.env.AST_BIND_HOST = '127.0.0.1';
    process.env.AST_BIND_PORT = '19010';
    process.env.AST_POOL_THREADS = '2';
    process.env.AST_MAX_FILES = '5';
    process.env.AST_MAX_TOTAL_BYTES = '200000';
    process.env.LOG_LEVEL = 'error';

    server = await startServer();
    client = new (AstClient as unknown as new (
      addr: string,
      creds: grpc.ChannelCredentials,
    ) => grpc.Client)(ADDRESS, grpc.credentials.createInsecure());
  }, { timeout: 30_000 });

  after(async () => {
    if (client) client.close();
    if (server) await server.shutdown('test-teardown');
  });

  it('Ping returns service metadata', async () => {
  const ping = await callUnary<
    Record<string, never>,
    { ok: boolean; pid: number; service: string; worker_count: number }
  >('Ping', {});
  assert.equal(ping.ok, true);
  assert.equal(ping.service, 'tesslateast.AstService');
  assert.ok(ping.worker_count >= 1);
});

  it('Index over gRPC round-trips JSON codec and returns oids', async () => {
  const res = await callUnary<
    { files: { path: string; content: string }[] },
    {
      files: { path: string; content: string; modified: boolean }[];
      index: Record<string, unknown>;
    }
  >('Index', { files: [{ path: 'a.tsx', content: FIXTURE }] });
  assert.equal(res.files.length, 1);
  assert.equal(res.files[0]!.modified, true);
  assert.ok(Object.keys(res.index).length >= 5);
});

  it('ApplyDiff over gRPC applies attribute change', async () => {
  const idx = await callUnary<
    { files: { path: string; content: string }[] },
    { files: { path: string; content: string }[]; index: Record<string, unknown> }
  >('Index', { files: [{ path: 'a.tsx', content: FIXTURE }] });
  const firstOid = Object.keys(idx.index)[0]!;
  const modifiedContent = idx.files[0]!.content;

  const res = await callUnary<
    { files: { path: string; content: string }[]; requests: unknown[] },
    { files: { path: string; content: string; modified: boolean }[] }
  >('ApplyDiff', {
    files: [{ path: 'a.tsx', content: modifiedContent }],
    requests: [{ oid: firstOid, attributes: { id: 'rpcset' }, override_classes: true }],
  });
  assert.equal(res.files[0]!.modified, true);
  assert.ok(res.files[0]!.content.includes('id="rpcset"'));
});

  it('server enforces max-files budget with RESOURCE_EXHAUSTED', async () => {
  const files = Array.from({ length: 6 }, (_, i) => ({
    path: `f${i}.tsx`,
    content: '<div />',
  }));
  try {
    await callUnary('Index', { files });
    assert.fail('expected RESOURCE_EXHAUSTED');
  } catch (err) {
    const e = err as grpc.ServiceError;
    assert.equal(e.code, grpc.status.RESOURCE_EXHAUSTED);
    assert.match(e.details ?? '', /6 files/);
  }
});

  it('server returns INVALID_ARGUMENT for non-array files', async () => {
  try {
    await callUnary('Index', { files: 'nope' as unknown } as unknown as {
      files: { path: string; content: string }[];
    });
    assert.fail('expected INVALID_ARGUMENT');
  } catch (err) {
    const e = err as grpc.ServiceError;
    assert.equal(e.code, grpc.status.INVALID_ARGUMENT);
  }
});

  it('server returns INVALID_ARGUMENT for malformed file entry', async () => {
  try {
    await callUnary('Index', {
      files: [{ path: 'ok.tsx', content: 'x' }, { path: 'missing-content' } as unknown as {
        path: string;
        content: string;
      }],
    });
    assert.fail('expected INVALID_ARGUMENT');
  } catch (err) {
    const e = err as grpc.ServiceError;
    assert.equal(e.code, grpc.status.INVALID_ARGUMENT);
  }
});

  it('Ping stays responsive while Piscina pool is under load', async () => {
  const fixtureFiles = Array.from({ length: 3 }, () => ({
    path: 'busy.tsx',
    content: FIXTURE,
  }));
  const indexPromises = Array.from({ length: 5 }, () =>
    callUnary('Index', { files: fixtureFiles }),
  );
  const pingStarted = Date.now();
  const ping = await callUnary<Record<string, never>, { ok: boolean }>('Ping', {});
  const pingDuration = Date.now() - pingStarted;
  assert.equal(ping.ok, true);
  assert.ok(pingDuration < 500, `Ping took ${pingDuration}ms — main thread may be blocked`);
  await Promise.all(indexPromises);
});

  it('client deadline propagates as DEADLINE_EXCEEDED', async () => {
  const fixtureFiles = Array.from({ length: 3 }, () => ({
    path: 'slow.tsx',
    content: FIXTURE,
  }));
  try {
    await callUnary('Index', { files: fixtureFiles }, 1);
    assert.fail('expected DEADLINE_EXCEEDED');
  } catch (err) {
    const e = err as grpc.ServiceError;
    assert.equal(e.code, grpc.status.DEADLINE_EXCEEDED);
  }
});
});
