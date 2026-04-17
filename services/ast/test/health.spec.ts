import { describe, it, before, after } from 'node:test';
import assert from 'node:assert/strict';
import * as grpc from '@grpc/grpc-js';

import { startServer, type Server } from '../src/server.js';
import { HealthServiceDefinition, SERVING_STATUS } from '../src/health.js';

const ADDRESS = '127.0.0.1:19011';
const HealthClient = grpc.makeGenericClientConstructor(HealthServiceDefinition, 'Health');

describe('grpc.health.v1.Health', { concurrency: false }, () => {
  let server: Server;
  let client: grpc.Client;

  before(async () => {
    process.env.AST_BIND_HOST = '127.0.0.1';
    process.env.AST_BIND_PORT = '19011';
    process.env.AST_POOL_THREADS = '2';
    process.env.LOG_LEVEL = 'error';
    server = await startServer();
    client = new (HealthClient as unknown as new (
      addr: string,
      creds: grpc.ChannelCredentials,
    ) => grpc.Client)(ADDRESS, grpc.credentials.createInsecure());
  }, { timeout: 30_000 });

  after(async () => {
    if (client) client.close();
    if (server) await server.shutdown('test-teardown');
  });

  const check = (service: string) =>
    new Promise<{ status: number }>((resolve, reject) => {
      (client as unknown as Record<
        string,
        (
          r: { service: string },
          cb: (err: grpc.ServiceError | null, res: { status: number }) => void,
        ) => void
      >).Check!({ service }, (err, res) => (err ? reject(err) : resolve(res)));
    });

  it('overall "" service returns SERVING', async () => {
    const res = await check('');
    assert.equal(res.status, SERVING_STATUS.SERVING);
  });

  it('named service returns SERVING', async () => {
    const res = await check('tesslateast.AstService');
    assert.equal(res.status, SERVING_STATUS.SERVING);
  });

  it('unknown service returns NOT_FOUND', async () => {
    try {
      await check('does.not.exist');
      assert.fail('expected NOT_FOUND');
    } catch (err) {
      const e = err as grpc.ServiceError;
      assert.equal(e.code, grpc.status.NOT_FOUND);
    }
  });
});
