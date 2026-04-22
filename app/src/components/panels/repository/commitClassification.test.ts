import { describe, expect, it } from 'vitest';
import { classifyCommit, summarizeFileBuckets } from './commitClassification';

describe('classifyCommit — conventional prefixes', () => {
  it('maps feat: to feature', () => {
    expect(classifyCommit('feat: add new login button').kind).toBe('feature');
  });

  it('maps fix(scope): to fix', () => {
    expect(classifyCommit('fix(auth): session handling race').kind).toBe('fix');
  });

  it('maps docs: to docs', () => {
    expect(classifyCommit('docs: clarify readme setup steps').kind).toBe('docs');
  });

  it('respects breaking-change marker', () => {
    expect(classifyCommit('feat!: new API surface').kind).toBe('feature');
  });

  it('is case-insensitive on the prefix', () => {
    expect(classifyCommit('FIX: handle the bug').kind).toBe('fix');
  });
});

describe('classifyCommit — structural messages', () => {
  it('marks merge PR commits as merge', () => {
    expect(classifyCommit('Merge pull request #42 from octo/feat').kind).toBe('merge');
  });

  it('marks merge-branch commits as merge', () => {
    expect(classifyCommit('Merge branch develop into feature/x').kind).toBe('merge');
  });

  it('marks revert commits as revert', () => {
    expect(classifyCommit('Revert "feat: broken thing"').kind).toBe('revert');
  });

  it('treats version bumps as release', () => {
    expect(classifyCommit('Release v1.2.3').kind).toBe('release');
    expect(classifyCommit('bump version to 0.4.0').kind).toBe('release');
    expect(classifyCommit('v2.0.0').kind).toBe('release');
  });
});

describe('classifyCommit — keyword heuristics', () => {
  it('catches "fix" without a prefix', () => {
    expect(classifyCommit('fixed the sign-in bug').kind).toBe('fix');
  });

  it('catches "add" → feature', () => {
    expect(classifyCommit('add repository panel overview tab').kind).toBe('feature');
  });

  it('catches "remove" → remove', () => {
    expect(classifyCommit('remove deprecated button').kind).toBe('remove');
  });

  it('catches "rename" → rename', () => {
    expect(classifyCommit('rename foo to bar').kind).toBe('rename');
  });

  it('routes readme-related → docs', () => {
    expect(classifyCommit('update README with install steps').kind).toBe('docs');
  });

  it('routes test-related → test', () => {
    expect(classifyCommit('add tests for graph layout').kind).toBe('test');
  });

  it('routes dependabot author → chore', () => {
    expect(classifyCommit('Bump lodash', 'dependabot[bot]').kind).toBe('chore');
  });

  it('falls back to update for ambiguous text', () => {
    expect(classifyCommit('wip').kind).toBe('update');
    expect(classifyCommit('...').kind).toBe('update');
  });

  it('returns update for empty or whitespace titles', () => {
    expect(classifyCommit('').kind).toBe('update');
    expect(classifyCommit('   ').kind).toBe('update');
  });
});

describe('summarizeFileBuckets', () => {
  it('buckets by extension family', () => {
    const buckets = summarizeFileBuckets([
      'app/src/foo.tsx',
      'app/src/bar.ts',
      'README.md',
      'docs/setup.md',
      'styles/base.css',
    ]);
    expect(buckets).toEqual([
      { label: 'documentation', count: 2 },
      { label: 'UI component', count: 1 },
      { label: 'code', count: 1 },
      { label: 'styling', count: 1 },
    ]);
  });

  it('separates tests from code', () => {
    const buckets = summarizeFileBuckets(['src/foo.ts', 'src/foo.test.ts', 'src/bar.spec.tsx']);
    expect(buckets.find((b) => b.label === 'test')?.count).toBe(2);
    expect(buckets.find((b) => b.label === 'code')?.count).toBe(1);
  });

  it('returns [] for empty input', () => {
    expect(summarizeFileBuckets([])).toEqual([]);
  });
});
