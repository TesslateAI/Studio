import { useEffect, useState } from 'react';
import {
  ArrowSquareOut,
  Clock,
  GitBranch,
  GitCommit,
  GitPullRequest,
  Lightbulb,
  Star,
  UsersThree,
  X,
} from '@phosphor-icons/react';
import {
  projectsApi,
  type GitCommit as GitCommitT,
  type GitRepoInfoResponse,
} from '../../../lib/api';
import { CommitRow } from './CommitRow';
import { ErrorState, InfoState, LoadingState, NoRemoteState } from './EmptyStates';
import { Term } from './Glossary';
import { formatAbsoluteDate, formatRelativeTime } from './relativeTime';

interface OverviewTabProps {
  projectSlug: string;
}

const EXPLAINER_STORAGE_KEY = 'tesslate.repositoryPanel.overviewExplainer.dismissed';

/**
 * Dismissible "what is a repo?" card shown at the top of the Overview tab.
 *
 * Dismissal persists to localStorage so returning users see a clean panel,
 * but the information lives behind the Glossary tooltips regardless.
 */
function ExplainerCard() {
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(EXPLAINER_STORAGE_KEY) === '1';
    } catch {
      return false;
    }
  });

  if (dismissed) return null;

  const onDismiss = () => {
    try {
      localStorage.setItem(EXPLAINER_STORAGE_KEY, '1');
    } catch {
      // Best effort — if storage is blocked, just collapse for this session.
    }
    setDismissed(true);
  };

  return (
    <div className="relative bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius)] p-3 pr-9">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 text-[var(--primary)] flex-shrink-0">
          <Lightbulb size={16} weight="fill" />
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-[12px] text-[var(--text)] leading-snug">
            This is where your code lives. Every time you or the AI agent makes a change, a snapshot
            called a <Term term="commit" /> gets saved.
          </p>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10.5px] text-[var(--text-muted)]">
            <Term term="repo" />
            <Term term="branch" />
            <Term term="merge" />
            <Term term="pullRequest" />
            <Term term="defaultBranch" />
          </div>
        </div>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss introduction"
        className="btn btn-icon btn-sm absolute top-1.5 right-1.5"
      >
        <X size={12} weight="bold" />
      </button>
    </div>
  );
}

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
}

function StatCard({ icon, label, value, hint }: StatCardProps) {
  return (
    <div className="bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius)] p-2.5 min-w-0">
      <div className="flex items-center gap-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide">
        <span className="text-[var(--text-subtle)]">{icon}</span>
        <span className="truncate">{label}</span>
      </div>
      <div className="mt-1 text-[14px] font-semibold text-[var(--text)] truncate">{value}</div>
      {hint && <div className="mt-0.5 text-[10px] text-[var(--text-muted)] truncate">{hint}</div>}
    </div>
  );
}

function ContributorRow({
  contributors,
}: {
  contributors: Array<{ login: string | null; avatar_url: string | null; html_url: string | null }>;
}) {
  const visible = contributors.slice(0, 6);
  const extra = contributors.length - visible.length;
  if (visible.length === 0) return <span className="text-[10px] text-[var(--text-muted)]">—</span>;
  return (
    <div className="flex items-center">
      <div className="flex -space-x-1.5">
        {visible.map((c, idx) => {
          const inner = c.avatar_url ? (
            <img
              src={c.avatar_url}
              alt={c.login ?? 'contributor'}
              className="w-5 h-5 rounded-full border border-[var(--bg)] object-cover"
              loading="lazy"
            />
          ) : (
            <span className="w-5 h-5 rounded-full border border-[var(--bg)] bg-[var(--surface-hover)] text-[9px] font-semibold text-[var(--text-muted)] flex items-center justify-center">
              {(c.login ?? '?').slice(0, 1).toUpperCase()}
            </span>
          );
          return c.html_url ? (
            <a
              key={`${c.login ?? 'anon'}-${idx}`}
              href={c.html_url}
              target="_blank"
              rel="noopener noreferrer"
              title={c.login ?? ''}
            >
              {inner}
            </a>
          ) : (
            <span key={`${c.login ?? 'anon'}-${idx}`} title={c.login ?? ''}>
              {inner}
            </span>
          );
        })}
      </div>
      {extra > 0 && (
        <span className="ml-1.5 text-[10px] text-[var(--text-muted)]">+{extra} more</span>
      )}
    </div>
  );
}

export function OverviewTab({ projectSlug }: OverviewTabProps) {
  const [info, setInfo] = useState<GitRepoInfoResponse | null>(null);
  const [commits, setCommits] = useState<GitCommitT[] | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      projectsApi.getGitRepoInfo(projectSlug),
      projectsApi.getGitCommits(projectSlug, { limit: 15 }),
    ])
      .then(([infoRes, commitsRes]) => {
        if (cancelled) return;
        setInfo(infoRes);
        setCommits(commitsRes.commits ?? []);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : 'Could not load overview';
        setError(message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectSlug]);

  if (loading) return <LoadingState label="Loading overview…" />;

  if (error) {
    return <ErrorState message={error} />;
  }

  if (info?.status === 'no_remote') {
    return <NoRemoteState feature="a repository overview" />;
  }

  if (info?.status === 'error' || !info) {
    return <ErrorState message={info?.message ?? 'GitHub is not responding right now.'} />;
  }

  // Local-only repos (git init'd, no GitHub remote): hide GitHub-specific
  // affordances like stars / open PRs / contributors / "All commits" link.
  const isLocal = info.status === 'local';

  return (
    <div className="flex flex-col gap-3 p-3">
      {!isLocal && <ExplainerCard />}

      {/* Description */}
      {info.description && (
        <p className="text-[12px] text-[var(--text)] leading-snug">{info.description}</p>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-2">
        <StatCard
          icon={<GitBranch size={12} weight="bold" />}
          label="Default branch"
          value={info.default_branch ?? '—'}
          hint={<Term term="defaultBranch">What's this?</Term>}
        />
        <StatCard
          icon={<Clock size={12} weight="bold" />}
          label="Last activity"
          value={formatRelativeTime(info.pushed_at) || '—'}
          hint={info.pushed_at ? formatAbsoluteDate(info.pushed_at) : undefined}
        />
        {!isLocal && (
          <>
            <StatCard
              icon={<GitPullRequest size={12} weight="bold" />}
              label="Open PRs"
              value={info.open_pulls_count ?? 0}
              hint={<Term term="pullRequest">What's a PR?</Term>}
            />
            <StatCard
              icon={<Star size={12} weight="bold" />}
              label="Stars"
              value={info.stars ?? 0}
            />
          </>
        )}
      </div>

      {/* Contributors — GitHub-only data; hidden for local-only repos. */}
      {!isLocal && (
        <div className="bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius)] p-2.5">
          <div className="flex items-center gap-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wide">
            <UsersThree size={12} weight="bold" />
            <span>Contributors</span>
            {info.contributors && info.contributors.length > 0 && (
              <span className="ml-auto text-[10px] text-[var(--text-muted)] normal-case tracking-normal">
                {info.contributors.length} total
              </span>
            )}
          </div>
          <div className="mt-1.5">
            <ContributorRow contributors={info.contributors ?? []} />
          </div>
        </div>
      )}

      {/* Recent activity */}
      <div>
        <div className="flex items-center justify-between mb-1.5 px-0.5">
          <div className="flex items-center gap-1.5 text-[10.5px] text-[var(--text-muted)] uppercase tracking-wide">
            <GitCommit size={12} weight="bold" />
            <span>Recent activity</span>
          </div>
          {info.html_url && (
            <a
              href={`${info.html_url}/commits`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[10.5px] text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
            >
              All commits
              <ArrowSquareOut size={10} weight="bold" />
            </a>
          )}
        </div>

        {!commits || commits.length === 0 ? (
          <InfoState
            title="No commits yet."
            body="Your first change will show up here as soon as the agent saves it."
          />
        ) : (
          <div className="bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius)] p-1">
            {commits.map((c) => (
              <CommitRow key={c.sha} commit={c} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
