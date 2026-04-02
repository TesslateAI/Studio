/**
 * SDK Smoke Test — creates its own project, tests every resource, cleans up.
 *
 * Usage: npx tsx smoke-test.ts
 */

import { TesslateClient, TesslateApiError } from './src/index.js';

const API_KEY = process.env.TESSLATE_API_KEY;
const BASE_URL = process.env.TESSLATE_BASE_URL || 'http://localhost:8899';

if (!API_KEY) {
  console.error('Error: TESSLATE_API_KEY env var is required.\n  Usage: TESSLATE_API_KEY=tsk_... npx tsx smoke-test.ts');
  process.exit(1);
}

const ts = new TesslateClient({ apiKey: API_KEY, baseUrl: BASE_URL, timeout: 15_000 });

let passed = 0;
let failed = 0;

async function test(name: string, fn: () => Promise<void>) {
  try {
    await fn();
    console.log(`  ✓ ${name}`);
    passed++;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.log(`  ✗ ${name}: ${msg}`);
    failed++;
  }
}

function assert(condition: boolean, msg: string) {
  if (!condition) throw new Error(`Assertion failed: ${msg}`);
}

async function main() {
  console.log('\n=== Tesslate SDK Smoke Test ===\n');

  // ---------------------------------------------------------------
  // Create a dedicated test project
  // ---------------------------------------------------------------
  console.log('Setup:');

  let slug = '';
  let projectId = '';

  await test('create test project', async () => {
    // Look up the Next.js 16 base ID dynamically (different per environment)
    const basesRes = await fetch(`${BASE_URL}/api/marketplace/bases?search=Next.js+16`, {
      headers: { Authorization: `Bearer ${API_KEY}` },
    });
    const basesData = await basesRes.json() as { bases: Array<{ id: string; name: string }> };
    const nextBase = basesData.bases.find((b) => b.name === 'Next.js 16');
    assert(nextBase !== undefined, 'Next.js 16 base must exist in marketplace');

    const result = await ts.projects.create({
      name: 'sdk-smoke-test',
      description: 'Auto-created by SDK smoke test',
      base_id: nextBase!.id,
      source_type: 'base',
    });
    assert(typeof result.project === 'object', 'should return project object');
    assert(typeof result.task_id === 'string', 'should return task_id');
    slug = result.project.slug;
    projectId = result.project.id;
    console.log(`    slug=${slug}, id=${projectId}, task=${result.task_id}`);

    // Wait for project setup to complete and volume to be ready
    console.log('    waiting for setup...');
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const p = await ts.projects.get(slug);
      if (p.environment_status === 'active') {
        // Verify volume is actually ready by checking file tree
        const tree = await ts.projects.files(slug).tree();
        if (tree.status === 'ready' && tree.files.length > 0) {
          console.log(`    setup complete (${(i + 1) * 2}s, ${tree.files.length} files)`);
          break;
        }
      }
      if (p.environment_status === 'setup_failed') {
        throw new Error('project setup failed');
      }
    }
  });

  if (!slug) {
    console.log('\n  Cannot continue without a project. Aborting.\n');
    process.exit(1);
  }

  // ---------------------------------------------------------------
  // Projects
  // ---------------------------------------------------------------
  console.log('\nProjects:');

  await test('list projects includes new project', async () => {
    const projects = await ts.projects.list();
    assert(Array.isArray(projects), 'should return array');
    const found = projects.find((p) => p.slug === slug);
    assert(found !== undefined, `should find project ${slug} in list`);
  });

  await test('get project by slug', async () => {
    const p = await ts.projects.get(slug);
    assert(p.slug === slug, 'slug should match');
    assert(p.id === projectId, 'id should match');
    assert(p.name === 'sdk-smoke-test', 'name should match');
    assert(typeof p.created_at === 'string', 'should have created_at');
  });

  await test('get project by id', async () => {
    const p = await ts.projects.get(projectId);
    assert(p.id === projectId, 'id should match');
  });

  await test('get non-existent project returns 404', async () => {
    try {
      await ts.projects.get('does-not-exist-zzzzz');
      throw new Error('should have thrown');
    } catch (err) {
      assert(err instanceof TesslateApiError, 'should be TesslateApiError');
      assert((err as TesslateApiError).status === 404, 'should be 404');
    }
  });

  // ---------------------------------------------------------------
  // Files
  // ---------------------------------------------------------------
  console.log('\nFiles:');

  const files = ts.projects.files(slug);

  await test('file tree contains template files', async () => {
    const tree = await files.tree();
    assert(tree.status === 'ready', `status should be ready, got ${tree.status}`);
    assert(tree.files.length > 0, 'should have files from template');
    const names = tree.files.map((f) => f.name);
    assert(names.includes('package.json'), 'should have package.json from template');
  });

  await test('read existing template file (package.json)', async () => {
    const result = await files.read('package.json');
    assert(result.content.includes('"name"'), 'package.json should have a name field');
    assert(result.content.includes('"dependencies"'), 'package.json should have dependencies');
    assert(result.size > 0, 'should have non-zero size');
  });

  await test('modify existing file and read back', async () => {
    // Read the original
    const original = await files.read('package.json');
    assert(original.content.length > 0, 'original should have content');

    // Modify it
    const modified = original.content.replace('"private": true', '"private": false');
    assert(modified !== original.content, 'modification should change content');
    await files.write('package.json', modified);

    // Read back and verify the edit stuck
    const readBack = await files.read('package.json');
    assert(readBack.content.includes('"private": false'), 'edit should persist');
    assert(!readBack.content.includes('"private": true'), 'old value should be gone');

    // Restore original
    await files.write('package.json', original.content);
  });

  await test('write + read roundtrip (new file)', async () => {
    const content = `sdk-test-${Date.now()}`;
    const writeResult = await files.write('sdk-test.txt', content);
    assert(typeof writeResult.message === 'string', 'write should return message');

    // Read back — retry only on 404 (volume sync delay), fail immediately on auth/other errors
    let readResult;
    for (let attempt = 0; attempt < 5; attempt++) {
      try {
        readResult = await files.read('sdk-test.txt');
        break;
      } catch (err) {
        if (err instanceof TesslateApiError && err.status === 404 && attempt < 4) {
          await new Promise((r) => setTimeout(r, 1000));
          continue;
        }
        throw err; // rethrow auth errors, 500s, non-API errors immediately
      }
    }
    assert(readResult !== undefined, 'should eventually read back the file');
    assert(readResult!.content === content, 'content should match what was written');
    assert(typeof readResult!.size === 'number', 'should have size');
  });

  await test('overwrite file', async () => {
    await files.write('sdk-test.txt', 'updated content');
    const result = await files.read('sdk-test.txt');
    assert(result.content === 'updated content', 'should have updated content');
  });

  await test('batch read returns file contents', async () => {
    await files.write('batch-a.txt', 'aaa');
    await files.write('batch-b.txt', 'bbb');
    // Retry until both files are readable (volume sync)
    let result;
    for (let attempt = 0; attempt < 5; attempt++) {
      await new Promise((r) => setTimeout(r, 1000));
      result = await files.readBatch(['batch-a.txt', 'batch-b.txt']);
      if (result.files.length === 2) break;
    }
    assert(result!.files.length === 2, `should return 2 files, got ${result!.files.length} (errors: ${JSON.stringify(result!.errors)})`);
    const sorted = result!.files.sort((a, b) => a.path.localeCompare(b.path));
    assert(sorted[0].content === 'aaa', 'batch-a.txt content should be aaa');
    assert(sorted[1].content === 'bbb', 'batch-b.txt content should be bbb');
  });

  await test('read non-existent file returns 404', async () => {
    try {
      await files.read('this-does-not-exist-ever.txt');
      throw new Error('should have thrown');
    } catch (err) {
      assert(err instanceof TesslateApiError, 'should be TesslateApiError');
      assert((err as TesslateApiError).status === 404, `should be 404, got ${(err as TesslateApiError).status}`);
    }
  });

  // ---------------------------------------------------------------
  // Containers
  // ---------------------------------------------------------------
  console.log('\nContainers:');

  const containers = ts.projects.containers(slug);

  await test('list containers', async () => {
    const list = await containers.list();
    assert(Array.isArray(list), 'should return array');
  });

  // ---------------------------------------------------------------
  // Agent
  // ---------------------------------------------------------------
  console.log('\nAgent:');

  await test('agent status for non-existent task returns 404', async () => {
    try {
      await ts.agent.status('non-existent-task-id');
      throw new Error('should have thrown');
    } catch (err) {
      assert(err instanceof TesslateApiError, 'should be TesslateApiError');
      assert((err as TesslateApiError).status === 404, `should be 404, got ${(err as TesslateApiError).status}`);
    }
  });

  // ---------------------------------------------------------------
  // Shell (auth check — container won't be running)
  // ---------------------------------------------------------------
  console.log('\nShell:');

  await test('shell auth works (container may not be running)', async () => {
    try {
      const session = await ts.shell.createSession({ project_id: projectId });
      // If it succeeds, that proves auth works — clean up
      assert(typeof session.session_id === 'string', 'should return session_id');
      await ts.shell.close(session.session_id);
    } catch (err) {
      // Must be a TesslateApiError — network/parse errors should fail the test
      assert(err instanceof TesslateApiError, `unexpected error type: ${err}`);
      const apiErr = err as TesslateApiError;
      // 401/403 = auth broken (our fault), anything else = container not running (expected)
      assert(apiErr.status !== 401 && apiErr.status !== 403, `auth failed with ${apiErr.status}: ${apiErr.message}`);
    }
  });

  // ---------------------------------------------------------------
  // Auth & Error handling
  // ---------------------------------------------------------------
  console.log('\nAuth & Errors:');

  await test('bad API key returns 401', async () => {
    const bad = new TesslateClient({ apiKey: 'tsk_invalid', baseUrl: BASE_URL });
    try {
      await bad.projects.list();
      throw new Error('should have thrown');
    } catch (err) {
      assert(err instanceof TesslateApiError, 'should be TesslateApiError');
      assert((err as TesslateApiError).status === 401, 'should be 401');
    }
  });

  await test('non-tsk token returns 401', async () => {
    const bad = new TesslateClient({ apiKey: 'not-a-valid-key', baseUrl: BASE_URL });
    try {
      await bad.projects.list();
      throw new Error('should have thrown');
    } catch (err) {
      assert(err instanceof TesslateApiError, 'should be TesslateApiError');
      assert((err as TesslateApiError).status === 401, 'should be 401');
    }
  });

  await test('error includes body with detail', async () => {
    try {
      await ts.projects.get('does-not-exist-zzzzz');
    } catch (err) {
      assert(err instanceof TesslateApiError, 'should be TesslateApiError');
      assert((err as TesslateApiError).body !== undefined, 'should have body');
      assert(typeof (err as TesslateApiError).message === 'string', 'should have message');
    }
  });

  // ---------------------------------------------------------------
  // Cleanup — delete the test project
  // ---------------------------------------------------------------
  console.log('\nCleanup:');

  await test('delete test project', async () => {
    // Delete is async — returns 200 and project is removed in the background
    await ts.projects.delete(slug);
    // Poll until the project is gone (async deletion)
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      try {
        await ts.projects.get(slug);
      } catch (err) {
        if (err instanceof TesslateApiError && err.status === 404) return; // success
      }
    }
    throw new Error('project still exists after 30s');
  });

  // ---------------------------------------------------------------
  // Summary
  // ---------------------------------------------------------------
  console.log(`\n=== Results: ${passed} passed, ${failed} failed ===\n`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error('Fatal error:', err);
  process.exit(1);
});
