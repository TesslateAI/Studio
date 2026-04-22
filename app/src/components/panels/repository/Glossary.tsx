import type { ReactNode } from 'react';
import { Question } from '@phosphor-icons/react';
import { Tooltip } from '../../ui/Tooltip';

/**
 * Plain-English glossary for git/GitHub terminology.
 *
 * Centralized so the same definitions are used everywhere in the panel and
 * a PM can reword them in one place without hunting through components.
 *
 * Bias: every definition should read naturally to someone who has never
 * touched git before. Avoid chained jargon ("a commit is a tree object").
 */
export const GLOSSARY = {
  repo: {
    label: 'Repository',
    definition:
      'A repository (or "repo") is the folder that holds your whole project and every change that has ever been made to it.',
  },
  commit: {
    label: 'Commit',
    definition:
      'A commit is a saved snapshot of your project. Every time you or the AI agent makes a change, a commit records what changed and why.',
  },
  branch: {
    label: 'Branch',
    definition:
      'A branch is a parallel copy of your project where you can try changes without touching the main version. When the changes look good, you merge the branch back in.',
  },
  merge: {
    label: 'Merge',
    definition:
      'Merging takes the changes from one branch and folds them into another — usually bringing a feature branch back into the main version.',
  },
  pullRequest: {
    label: 'Pull Request',
    definition:
      'A pull request is a proposal to merge one branch into another. Teammates can review the changes before they go in.',
  },
  defaultBranch: {
    label: 'Default branch',
    definition:
      'The main copy of your project that most people see. Usually called "main" or "master".',
  },
  aheadBehind: {
    label: 'Ahead / Behind',
    definition:
      '"Ahead" means this branch has new commits that the default branch doesn\'t. "Behind" means the default branch has commits this branch is missing.',
  },
  author: {
    label: 'Author',
    definition: 'The person (or AI agent) who wrote the change that the commit records.',
  },
  sha: {
    label: 'SHA',
    definition:
      'A SHA is a unique fingerprint for each commit — a short string of letters and numbers you can use to point at exactly that change.',
  },
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;

interface TermProps {
  term: GlossaryKey;
  children?: ReactNode;
  /** Render as a help-icon button instead of wrapping the label. */
  asIcon?: boolean;
}

/**
 * Renders `children` (or the term's label) with a dashed underline and a
 * hover tooltip showing the plain-English definition.
 */
export function Term({ term, children, asIcon = false }: TermProps) {
  const entry = GLOSSARY[term];
  const content = entry.definition;

  if (asIcon) {
    return (
      <Tooltip content={content} side="top">
        <button
          type="button"
          aria-label={`What does "${entry.label}" mean?`}
          className="inline-flex items-center justify-center w-4 h-4 rounded-full text-[var(--text-subtle)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
        >
          <Question size={11} weight="bold" />
        </button>
      </Tooltip>
    );
  }

  return (
    <Tooltip content={content} side="top">
      <span className="underline decoration-dotted decoration-[var(--text-subtle)] underline-offset-2 cursor-help">
        {children ?? entry.label}
      </span>
    </Tooltip>
  );
}
