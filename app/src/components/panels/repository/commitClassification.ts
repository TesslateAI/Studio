/**
 * Heuristic commit classifier.
 *
 * Goal: give a non-technical person a plain-English pill next to every commit
 * so they can skim a history without decoding conventional-commit prefixes or
 * branch names. Runs purely on the commit title + author name; we deliberately
 * do NOT call an LLM or fetch commit diffs — this must be fast, deterministic,
 * and runnable offline.
 *
 * Precedence (first match wins):
 *   1. Conventional-commit prefix: feat/fix/chore/docs/test/refactor/perf/style/ci/build/revert
 *   2. Squashed-merge marker: "Merge pull request"
 *   3. Revert marker: "Revert "..."
 *   4. Release / version bump heuristic: "bump to v1.2.3", "release 1.2", "chore(release):"
 *   5. Keyword sweep (fix, bug, add, update, remove, delete, rename…)
 *   6. Fallback → "update"
 *
 * The classifier returns a stable machine key plus a human label and emoji.
 * UI code picks color from the key via `COMMIT_KIND_ACCENT`.
 */

export type CommitKind =
  | 'feature'
  | 'fix'
  | 'docs'
  | 'chore'
  | 'refactor'
  | 'test'
  | 'perf'
  | 'style'
  | 'ci'
  | 'build'
  | 'merge'
  | 'revert'
  | 'release'
  | 'remove'
  | 'rename'
  | 'update';

export interface CommitSummary {
  kind: CommitKind;
  label: string;
  emoji: string;
}

const CONVENTIONAL: Record<string, CommitKind> = {
  feat: 'feature',
  feature: 'feature',
  fix: 'fix',
  bugfix: 'fix',
  hotfix: 'fix',
  docs: 'docs',
  doc: 'docs',
  chore: 'chore',
  refactor: 'refactor',
  test: 'test',
  tests: 'test',
  perf: 'perf',
  style: 'style',
  ci: 'ci',
  build: 'build',
  revert: 'revert',
};

const LABEL_BY_KIND: Record<CommitKind, { label: string; emoji: string }> = {
  feature: { label: 'New feature', emoji: '✨' },
  fix: { label: 'Bug fix', emoji: '🐛' },
  docs: { label: 'Documentation', emoji: '📝' },
  chore: { label: 'Maintenance', emoji: '🧹' },
  refactor: { label: 'Refactor', emoji: '♻️' },
  test: { label: 'Tests', emoji: '🧪' },
  perf: { label: 'Performance', emoji: '⚡' },
  style: { label: 'Styling', emoji: '💅' },
  ci: { label: 'CI / automation', emoji: '🤖' },
  build: { label: 'Build setup', emoji: '🏗️' },
  merge: { label: 'Merge', emoji: '🔀' },
  revert: { label: 'Revert', emoji: '⏪' },
  release: { label: 'Release', emoji: '🚀' },
  remove: { label: 'Removed code', emoji: '🗑️' },
  rename: { label: 'Rename', emoji: '🏷️' },
  update: { label: 'Update', emoji: '📦' },
};

/** Accent class keyed by kind — used for the pill background. */
export const COMMIT_KIND_ACCENT: Record<CommitKind, string> = {
  feature: 'bg-[#22c55e]/15 text-[#16a34a]',
  fix: 'bg-[#ef4444]/15 text-[#dc2626]',
  docs: 'bg-[#3b82f6]/15 text-[#2563eb]',
  chore: 'bg-[var(--surface-hover)] text-[var(--text-muted)]',
  refactor: 'bg-[#a855f7]/15 text-[#9333ea]',
  test: 'bg-[#14b8a6]/15 text-[#0d9488]',
  perf: 'bg-[#f97316]/15 text-[#ea580c]',
  style: 'bg-[#ec4899]/15 text-[#db2777]',
  ci: 'bg-[#06b6d4]/15 text-[#0891b2]',
  build: 'bg-[#eab308]/15 text-[#ca8a04]',
  merge: 'bg-[#6366f1]/15 text-[#4f46e5]',
  revert: 'bg-[#64748b]/15 text-[#475569]',
  release: 'bg-[#f59e0b]/15 text-[#d97706]',
  remove: 'bg-[#ef4444]/15 text-[#dc2626]',
  rename: 'bg-[#8b5cf6]/15 text-[#7c3aed]',
  update: 'bg-[var(--surface-hover)] text-[var(--text-muted)]',
};

function bareLabel(kind: CommitKind): CommitSummary {
  const entry = LABEL_BY_KIND[kind];
  return { kind, label: entry.label, emoji: entry.emoji };
}

/**
 * Classify a commit from its title (first line) and optional author name.
 *
 * The author is used as a tiebreaker signal — e.g. commits from known bot
 * accounts ("dependabot") lean toward `chore`.
 */
export function classifyCommit(titleRaw: string, authorLogin?: string | null): CommitSummary {
  const title = (titleRaw ?? '').trim();
  if (!title) return bareLabel('update');

  // 1. Merge / revert markers win over everything — they're structural, not
  //    editorial, and usually show up as auto-generated messages.
  if (/^Merge pull request\b/i.test(title) || /^Merge branch\b/i.test(title)) {
    return bareLabel('merge');
  }
  if (/^Revert\s+"/i.test(title) || /^Revert:\s/i.test(title)) {
    return bareLabel('revert');
  }

  // 2. Conventional-commit prefix.
  //    Covers `feat:`, `fix(scope):`, `chore!:` (breaking), etc.
  const convMatch = title.match(/^([a-z]+)(?:\([^)]+\))?(!)?\s*:/i);
  if (convMatch) {
    const prefix = convMatch[1].toLowerCase();
    const mapped = CONVENTIONAL[prefix];
    if (mapped) return bareLabel(mapped);
  }

  // 3. Release / version bump — a lot of projects use "Release 1.2.3" or
  //    "bump version to 0.4.0" without the conventional-commit scaffolding.
  if (
    /^release\s+v?\d/i.test(title) ||
    /\b(bump|upgrade|update)\s+(version|to\s+v?\d)/i.test(title) ||
    /^v\d+\.\d+/.test(title)
  ) {
    return bareLabel('release');
  }

  // 4. Bot authors → chore. Keeps dependabot / renovate noise down.
  const login = (authorLogin ?? '').toLowerCase();
  if (
    login === 'dependabot[bot]' ||
    login === 'dependabot' ||
    login === 'renovate[bot]' ||
    login === 'github-actions[bot]'
  ) {
    return bareLabel('chore');
  }

  // 5. Keyword sweep on the first ~80 chars — order matters, most specific first.
  const lower = title.toLowerCase();
  if (/\b(fix(e[sd])?|bug|hotfix|patch|resolves?|closes?\s+#\d+)\b/.test(lower)) {
    return bareLabel('fix');
  }
  if (/\b(delete[sd]?|remove[sd]?|drop(ped)?)\b/.test(lower)) {
    return bareLabel('remove');
  }
  if (/\brename[sd]?\b/.test(lower) || /\bmove[sd]?\b/.test(lower)) {
    return bareLabel('rename');
  }
  if (/\b(docs?|readme|changelog|documentation)\b/.test(lower)) {
    return bareLabel('docs');
  }
  if (/\btests?\b|\bspec(s)?\b/.test(lower)) {
    return bareLabel('test');
  }
  if (/\brefactor(ed|s|ing)?\b|\bcleanup\b|\bsimplif/.test(lower)) {
    return bareLabel('refactor');
  }
  if (/\bperf(ormance)?\b|\boptimiz/.test(lower)) {
    return bareLabel('perf');
  }
  if (/\bstyl(e|ing)\b|\bformat(ting)?\b|\blint\b/.test(lower)) {
    return bareLabel('style');
  }
  if (/\b(ci|github\s+actions|workflow)\b/.test(lower)) {
    return bareLabel('ci');
  }
  if (/\b(build|webpack|vite|bundler?)\b/.test(lower)) {
    return bareLabel('build');
  }
  if (/\b(add(ed|s|ing)?|introduce[ds]?|implement[eds]?|create[ds]?)\b/.test(lower)) {
    return bareLabel('feature');
  }
  if (/\b(update[ds]?|tweak[eds]?|adjust[eds]?|improve[ds]?)\b/.test(lower)) {
    return bareLabel('update');
  }

  // 6. Fallback — the author did *something*, we just can't place it.
  return bareLabel('update');
}

/**
 * File-type summary for the inline "Changed files" list.
 *
 * Scans an array of filenames and returns an ordered list of
 * `{label, count}` bucketing by extension family. Kept independent from
 * `classifyCommit` because it answers a different question ("what parts of
 * the app moved?").
 */
export function summarizeFileBuckets(
  filenames: readonly string[]
): Array<{ label: string; count: number }> {
  const buckets = new Map<string, number>();
  const bump = (label: string) => buckets.set(label, (buckets.get(label) ?? 0) + 1);

  for (const name of filenames) {
    const lower = name.toLowerCase();
    if (/\.(md|mdx|rst|txt)$/.test(lower) || lower === 'readme' || lower === 'license') {
      bump('documentation');
    } else if (/\.(test|spec)\.(tsx?|jsx?|py)$/.test(lower)) {
      bump('test');
    } else if (/\.(tsx|jsx)$/.test(lower)) {
      bump('UI component');
    } else if (/\.(ts|js|mjs|cjs)$/.test(lower)) {
      bump('code');
    } else if (/\.py$/.test(lower)) {
      bump('Python');
    } else if (/\.go$/.test(lower)) {
      bump('Go');
    } else if (/\.(css|scss|sass|less)$/.test(lower)) {
      bump('styling');
    } else if (/\.(json|ya?ml|toml)$/.test(lower)) {
      bump('config');
    } else if (/\.(png|jpe?g|gif|svg|webp|avif|ico)$/.test(lower)) {
      bump('image');
    } else {
      bump('other');
    }
  }

  return Array.from(buckets.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([label, count]) => ({ label, count }));
}
