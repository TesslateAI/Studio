import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as grpc from '@grpc/grpc-js';

import { checkRequest, BudgetError, type Budgets } from '../src/budgets.js';

const SMALL_BUDGETS: Budgets = {
  maxFiles: 3,
  maxTotalBytes: 100,
  perFileWallClockMs: 1000,
};

test('checkRequest passes for a valid small request', () => {
  const files = [
    { path: 'a.tsx', content: 'abc' },
    { path: 'b.tsx', content: 'def' },
  ];
  assert.doesNotThrow(() => checkRequest(files, SMALL_BUDGETS));
});

test('checkRequest rejects non-array with INVALID_ARGUMENT', () => {
  try {
    checkRequest('nope' as unknown, SMALL_BUDGETS);
    assert.fail('should have thrown');
  } catch (err) {
    assert.ok(err instanceof BudgetError);
    assert.equal(err.grpcCode, grpc.status.INVALID_ARGUMENT);
  }
});

test('checkRequest rejects too many files with RESOURCE_EXHAUSTED', () => {
  const files = [
    { path: 'a', content: 'x' },
    { path: 'b', content: 'y' },
    { path: 'c', content: 'z' },
    { path: 'd', content: 'w' },
  ];
  try {
    checkRequest(files, SMALL_BUDGETS);
    assert.fail('should have thrown');
  } catch (err) {
    assert.ok(err instanceof BudgetError);
    assert.equal(err.grpcCode, grpc.status.RESOURCE_EXHAUSTED);
    assert.match(err.message, /4 files/);
  }
});

test('checkRequest rejects oversize content with RESOURCE_EXHAUSTED', () => {
  const files = [{ path: 'big.tsx', content: 'x'.repeat(200) }];
  try {
    checkRequest(files, SMALL_BUDGETS);
    assert.fail('should have thrown');
  } catch (err) {
    assert.ok(err instanceof BudgetError);
    assert.equal(err.grpcCode, grpc.status.RESOURCE_EXHAUSTED);
  }
});

test('checkRequest rejects malformed file with INVALID_ARGUMENT', () => {
  const files = [{ path: 'ok.tsx', content: 'a' }, { path: 'bad.tsx' }];
  try {
    checkRequest(files as unknown, SMALL_BUDGETS);
    assert.fail('should have thrown');
  } catch (err) {
    assert.ok(err instanceof BudgetError);
    assert.equal(err.grpcCode, grpc.status.INVALID_ARGUMENT);
  }
});

test('checkRequest measures UTF-8 bytes, not character count', () => {
  // 50 × 4-byte emoji = 200 bytes, exceeds 100-byte budget even though
  // string length is only 50.
  const files = [{ path: 'emoji.tsx', content: '\u{1F4A9}'.repeat(50) }];
  try {
    checkRequest(files, SMALL_BUDGETS);
    assert.fail('should have thrown on utf-8 byte overflow');
  } catch (err) {
    assert.ok(err instanceof BudgetError);
    assert.equal(err.grpcCode, grpc.status.RESOURCE_EXHAUSTED);
  }
});

test('checkRequest empty array is valid', () => {
  assert.doesNotThrow(() => checkRequest([], SMALL_BUDGETS));
});
