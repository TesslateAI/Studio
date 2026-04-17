import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { indexFile, type OidMeta } from '../src/ops/index.js';
import { applyDiffFile, type DiffRequest } from '../src/ops/apply_diff.js';
import { parseSource } from '../src/ops/common.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// The fixture lives at project-root-relative test/fixture.tsx. Under
// tsc outDir, compiled tests end up in dist/test/*, so walk up twice.
const FIXTURE_PATH = path.resolve(__dirname, '../..', 'test/fixture.tsx');
const FIXTURE = readFileSync(FIXTURE_PATH, 'utf8');

test('indexFile injects data-oid on every JSX element', () => {
  const globalOids = new Set<string>();
  const result = indexFile({ path: 'fixture.tsx', content: FIXTURE }, globalOids);

  assert.equal(result.error, undefined);
  assert.equal(result.modified, true);
  assert.equal(result.path, 'fixture.tsx');

  const oids = Object.keys(result.index);
  assert.ok(oids.length >= 5, `expected ≥5 oids, got ${oids.length}`);
  for (const oid of oids) {
    assert.match(oid, /^[a-z0-9]{7}$/, `oid ${oid} must be 7 lowercase alnum`);
    const meta = result.index[oid] as OidMeta;
    assert.equal(meta.path, 'fixture.tsx');
    assert.ok(typeof meta.tag_name === 'string');
    assert.ok((meta.start_line ?? 0) > 0);
  }

  for (const oid of oids) {
    const count = (result.content.match(new RegExp(`data-oid="${oid}"`, 'g')) || []).length;
    assert.equal(count, 1, `oid ${oid} should appear exactly once`);
  }
});

test('indexFile is idempotent: second run does not modify', () => {
  const pass1 = indexFile({ path: 'fixture.tsx', content: FIXTURE }, new Set());
  const pass2 = indexFile({ path: 'fixture.tsx', content: pass1.content }, new Set());
  assert.equal(pass2.modified, false);
  assert.equal(pass2.content, pass1.content);
});

test('indexFile detects dynamic type (array map) and component name', () => {
  const r = indexFile({ path: 'fixture.tsx', content: FIXTURE }, new Set());
  const liEntry = Object.values(r.index).find((m) => m.tag_name === 'li');
  assert.ok(liEntry, 'li element should be indexed');
  assert.equal(liEntry!.dynamic_type, 'array');
  assert.equal(liEntry!.component, 'Greeting');
});

test('indexFile detects conditional rendering via logical &&', () => {
  const r = indexFile({ path: 'fixture.tsx', content: FIXTURE }, new Set());
  const spanEntry = Object.values(r.index).find((m) => m.tag_name === 'span');
  assert.ok(spanEntry);
  assert.equal(spanEntry!.dynamic_type, 'conditional');
});

test('indexFile respects globalOids for cross-file collision avoidance', () => {
  // Fake an existing oid that would collide if generator used it.
  const globalOids = new Set<string>(['abcdefg']);
  const src = '<div data-oid="abcdefg" />';
  // Collision path: element already has "abcdefg" but it's in globalOids
  // so a new one should be generated.
  const r = indexFile({ path: 'a.tsx', content: src }, globalOids);
  assert.equal(r.modified, true);
  const newOids = Object.keys(r.index);
  assert.equal(newOids.length, 1);
  assert.notEqual(newOids[0], 'abcdefg');
});

test('indexFile reports error for unparseable source and preserves original', () => {
  const r = indexFile({ path: 'bad.tsx', content: 'const x = <div' }, new Set());
  assert.ok(r.error);
  assert.equal(r.modified, false);
  assert.equal(r.content, 'const x = <div');
  assert.deepEqual(r.index, {});
});

test('indexFile on empty source returns no oids, no modification', () => {
  const r = indexFile({ path: 'empty.tsx', content: '' }, new Set());
  assert.equal(r.modified, false);
  assert.equal(r.content, '');
  assert.deepEqual(r.index, {});
});

test('indexFile skips Fragment and React.Fragment elements', () => {
  const src = `
    import React from 'react';
    export function F() {
      return <><div>a</div><React.Fragment><span>b</span></React.Fragment></>;
    }
  `;
  const r = indexFile({ path: 'f.tsx', content: src }, new Set());
  const tags = Object.values(r.index).map((m) => m.tag_name).sort();
  assert.deepEqual(tags, ['div', 'span']);
});

test('applyDiffFile changes className on targeted oid (override mode)', () => {
  const pass1 = indexFile({ path: 'a.tsx', content: FIXTURE }, new Set());
  const firstOid = Object.keys(pass1.index)[0]!;
  const byOid = new Map<string, DiffRequest>([
    [firstOid, { oid: firstOid, attributes: { className: 'p-8 bg-red-500' }, override_classes: true }],
  ]);
  const r = applyDiffFile({ path: 'a.tsx', content: pass1.content }, byOid);
  assert.equal(r.error, undefined);
  assert.equal(r.modified, true);
  assert.ok(r.content.includes('className="p-8 bg-red-500"'));
});

test('applyDiffFile twMerges className when override_classes is false', () => {
  const src = '<div className="p-4 text-red-500" data-oid="aaaaaaa" />';
  const byOid = new Map<string, DiffRequest>([
    ['aaaaaaa', { oid: 'aaaaaaa', attributes: { className: 'p-8 text-blue-500' } }],
  ]);
  const r = applyDiffFile({ path: 'a.tsx', content: src }, byOid);
  assert.equal(r.modified, true);
  // twMerge should collapse conflicting p-* and text-* classes.
  assert.ok(r.content.includes('className="p-8 text-blue-500"'));
});

test('applyDiffFile with no matching oid is a no-op', () => {
  const pass1 = indexFile({ path: 'a.tsx', content: FIXTURE }, new Set());
  const byOid = new Map<string, DiffRequest>([
    ['nomatch', { oid: 'nomatch', attributes: { id: 'x' } }],
  ]);
  const r = applyDiffFile({ path: 'a.tsx', content: pass1.content }, byOid);
  assert.equal(r.modified, false);
  assert.equal(r.content, pass1.content);
});

test('applyDiffFile removes element when remove=true', () => {
  const src = '<div><span data-oid="bbbbbbb">gone</span><p data-oid="ccccccc">stay</p></div>';
  const byOid = new Map<string, DiffRequest>([
    ['bbbbbbb', { oid: 'bbbbbbb', remove: true }],
  ]);
  const r = applyDiffFile({ path: 'a.tsx', content: src }, byOid);
  assert.equal(r.modified, true);
  assert.ok(!r.content.includes('bbbbbbb'));
  assert.ok(r.content.includes('ccccccc'));
});

test('applyDiffFile replaces text_content with new string', () => {
  const src = '<h1 data-oid="ddddddd">Old Title</h1>';
  const byOid = new Map<string, DiffRequest>([
    ['ddddddd', { oid: 'ddddddd', text_content: 'New Title' }],
  ]);
  const r = applyDiffFile({ path: 'a.tsx', content: src }, byOid);
  assert.equal(r.modified, true);
  assert.ok(r.content.includes('New Title'));
  assert.ok(!r.content.includes('Old Title'));
});

test('applyDiffFile wrap_with wraps element and preserves inner oid', () => {
  const src = '<span data-oid="eeeeeee">inner</span>';
  const byOid = new Map<string, DiffRequest>([
    ['eeeeeee', { oid: 'eeeeeee', wrap_with: { tag_name: 'div', oid: 'fffffff', classes: 'wrapper' } }],
  ]);
  const r = applyDiffFile({ path: 'a.tsx', content: src }, byOid);
  assert.equal(r.modified, true);
  assert.ok(r.content.includes('<div data-oid="fffffff"'));
  assert.ok(r.content.includes('className="wrapper"'));
  assert.ok(r.content.includes('data-oid="eeeeeee"'));
});

test('applyDiffFile structure_changes append inserts child', () => {
  const src = '<div data-oid="ggggggg"><p>existing</p></div>';
  const byOid = new Map<string, DiffRequest>([
    ['ggggggg', {
      oid: 'ggggggg',
      structure_changes: [{ type: 'insert', location: 'append', element: { tag_name: 'span', text: 'new', oid: 'hhhhhhh' } }],
    }],
  ]);
  const r = applyDiffFile({ path: 'a.tsx', content: src }, byOid);
  assert.equal(r.modified, true);
  assert.ok(r.content.includes('<span data-oid="hhhhhhh">new</span>'));
});

test('applyDiffFile style_patch kebab→camel and null removes', () => {
  const src = '<div data-oid="iiiiiii" style={{color: "red", fontSize: "10px"}} />';
  const byOid = new Map<string, DiffRequest>([
    ['iiiiiii', {
      oid: 'iiiiiii',
      style_patch: { 'background-color': 'blue', color: null },
    }],
  ]);
  const r = applyDiffFile({ path: 'a.tsx', content: src }, byOid);
  assert.equal(r.modified, true);
  assert.ok(r.content.includes('backgroundColor'));
  assert.ok(!r.content.match(/color:\s*"red"/));
});

test('applyDiffFile attribute removal (value=null) removes attribute', () => {
  const src = '<img data-oid="jjjjjjj" alt="desc" src="/x.png" />';
  const byOid = new Map<string, DiffRequest>([
    ['jjjjjjj', { oid: 'jjjjjjj', attributes: { alt: null } }],
  ]);
  const r = applyDiffFile({ path: 'a.tsx', content: src }, byOid);
  assert.equal(r.modified, true);
  assert.ok(!r.content.includes('alt='));
  assert.ok(r.content.includes('src="/x.png"'));
});

test('applyDiffFile on unparseable source surfaces error, preserves original', () => {
  const byOid = new Map<string, DiffRequest>([
    ['kkkkkkk', { oid: 'kkkkkkk', remove: true }],
  ]);
  const r = applyDiffFile({ path: 'bad.tsx', content: 'const x = <div' }, byOid);
  assert.ok(r.error);
  assert.equal(r.modified, false);
  assert.equal(r.content, 'const x = <div');
});

test('parseSource handles decorators, private fields, top-level await', () => {
  const src = `
    await fetch('x');
    class C {
      #secret = 1;
      @deco
      method() {}
    }
  `;
  // Just verify it doesn't throw.
  assert.doesNotThrow(() => parseSource(src));
});
