import { ArrowSquareOut } from '@phosphor-icons/react';
import type { GitCommit } from '../../../lib/api';
import { Tooltip } from '../../ui/Tooltip';
import { classifyCommit, COMMIT_KIND_ACCENT, type CommitSummary } from './commitClassification';
import { formatAbsoluteDate, formatRelativeTime } from './relativeTime';

interface CommitRowProps {
  commit: GitCommit;
  compact?: boolean;
  onSelect?: (sha: string) => void;
  selected?: boolean;
}

function authorDisplayName(commit: GitCommit): string {
  return commit.author.name || commit.author.login || commit.committer.name || 'Unknown';
}

function AvatarDisc({ commit }: { commit: GitCommit }) {
  const name = authorDisplayName(commit);
  const initials =
    name
      .split(/\s+/)
      .map((p) => p[0])
      .filter(Boolean)
      .slice(0, 2)
      .join('')
      .toUpperCase() || '?';

  if (commit.author.avatar_url) {
    return (
      <img
        src={commit.author.avatar_url}
        alt={`${name}'s avatar`}
        width={20}
        height={20}
        className="w-5 h-5 rounded-full border border-[var(--border)] flex-shrink-0 object-cover"
        loading="lazy"
      />
    );
  }
  return (
    <span
      className="w-5 h-5 rounded-full border border-[var(--border)] bg-[var(--surface-hover)] text-[9px] font-semibold text-[var(--text-muted)] flex items-center justify-center flex-shrink-0"
      aria-hidden="true"
    >
      {initials}
    </span>
  );
}

function KindPill({ summary }: { summary: CommitSummary }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-[var(--radius-small)] text-[9.5px] font-medium whitespace-nowrap ${
        COMMIT_KIND_ACCENT[summary.kind]
      }`}
    >
      <span aria-hidden="true">{summary.emoji}</span>
      <span>{summary.label}</span>
    </span>
  );
}

/**
 * One line in a recent-activity / graph list.
 *
 * Renders: avatar · kind pill · title · author · relative time · GitHub link.
 * All pieces degrade gracefully when their source data is missing so we
 * never show "undefined" or an empty row.
 */
export function CommitRow({ commit, compact = false, onSelect, selected }: CommitRowProps) {
  const summary = classifyCommit(commit.title, commit.author.login);
  const when = commit.author.date ?? commit.committer.date;
  const rel = formatRelativeTime(when);
  const abs = formatAbsoluteDate(when);
  const name = authorDisplayName(commit);

  const body = (
    <>
      <AvatarDisc commit={commit} />
      <div className="flex-1 min-w-0">
        <div className="flex items-start gap-1.5 min-w-0">
          <KindPill summary={summary} />
          <span
            className="flex-1 text-[12px] text-[var(--text)] leading-snug line-clamp-2 min-w-0"
            title={commit.message || commit.title}
          >
            {commit.title || '(no commit message)'}
          </span>
        </div>
        {!compact && (
          <div className="flex items-center gap-1.5 mt-0.5 text-[10px] text-[var(--text-muted)]">
            <span className="truncate">{name}</span>
            {rel && (
              <>
                <span className="text-[var(--text-subtle)]">·</span>
                <Tooltip content={abs} side="top">
                  <span className="cursor-default">{rel}</span>
                </Tooltip>
              </>
            )}
            {commit.short_sha && (
              <>
                <span className="text-[var(--text-subtle)]">·</span>
                <span className="font-mono text-[var(--text-subtle)]">{commit.short_sha}</span>
              </>
            )}
          </div>
        )}
      </div>
      {commit.html_url && (
        <a
          href={commit.html_url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="flex-shrink-0 text-[var(--text-subtle)] hover:text-[var(--text)] transition-colors opacity-0 group-hover:opacity-100"
          title="Open on GitHub"
          aria-label="Open commit on GitHub"
        >
          <ArrowSquareOut size={11} weight="bold" />
        </a>
      )}
    </>
  );

  if (onSelect) {
    return (
      <button
        type="button"
        onClick={() => onSelect(commit.sha)}
        className={`group w-full flex items-start gap-2 px-2 py-1.5 rounded-[var(--radius-small)] text-left transition-colors ${
          selected
            ? 'bg-[var(--surface-hover)] border border-[var(--border-hover)]'
            : 'hover:bg-[var(--surface-hover)] border border-transparent'
        }`}
      >
        {body}
      </button>
    );
  }

  return (
    <div className="group flex items-start gap-2 px-2 py-1.5 rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] transition-colors">
      {body}
    </div>
  );
}
