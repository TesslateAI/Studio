import { useEffect, useState } from 'react';
import { ArrowSquareOut, CheckCircle, GitBranch } from '@phosphor-icons/react';
import { projectsApi, type GitBranchSummary, type GitBranchesResponse } from '../../../lib/api';
import { ErrorState, InfoState, LoadingState, NoRemoteState } from './EmptyStates';
import { Term } from './Glossary';

interface BranchesTabProps {
  projectSlug: string;
}

function AheadBehindBadge({ branch }: { branch: GitBranchSummary }) {
  if (branch.is_default) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-[var(--radius-small)] bg-[var(--primary)]/15 text-[var(--primary)] text-[9.5px] font-medium">
        <CheckCircle size={10} weight="fill" />
        Default
      </span>
    );
  }
  const ahead = branch.ahead_by ?? null;
  const behind = branch.behind_by ?? null;
  if (ahead == null && behind == null) {
    return <span className="text-[10px] text-[var(--text-muted)]">—</span>;
  }
  return (
    <span className="inline-flex items-center gap-1 text-[10px]">
      {ahead != null && (
        <span
          className={`inline-flex items-center gap-0.5 ${
            ahead > 0 ? 'text-[#16a34a]' : 'text-[var(--text-muted)]'
          }`}
        >
          <span aria-hidden="true">↑</span>
          {ahead}
        </span>
      )}
      {behind != null && (
        <span
          className={`inline-flex items-center gap-0.5 ${
            behind > 0 ? 'text-[#dc2626]' : 'text-[var(--text-muted)]'
          }`}
        >
          <span aria-hidden="true">↓</span>
          {behind}
        </span>
      )}
    </span>
  );
}

function BranchRow({ branch }: { branch: GitBranchSummary }) {
  return (
    <div className="flex items-center gap-2 px-2.5 py-2 rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] transition-colors">
      <GitBranch
        size={13}
        weight="bold"
        className={branch.is_default ? 'text-[var(--primary)]' : 'text-[var(--text-subtle)]'}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="text-[12px] text-[var(--text)] truncate font-medium">{branch.name}</span>
          {branch.protected && (
            <span
              className="px-1 py-0.5 rounded-[var(--radius-small)] bg-[var(--surface-hover)] text-[9px] text-[var(--text-muted)]"
              title="Protected branch"
            >
              protected
            </span>
          )}
        </div>
        {branch.sha && (
          <span className="text-[10px] font-mono text-[var(--text-subtle)]">
            {branch.sha.slice(0, 7)}
          </span>
        )}
      </div>
      <AheadBehindBadge branch={branch} />
      {branch.html_url && (
        <a
          href={branch.html_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[var(--text-subtle)] hover:text-[var(--text)] transition-colors"
          title="Open branch on GitHub"
          aria-label={`Open ${branch.name} on GitHub`}
        >
          <ArrowSquareOut size={11} weight="bold" />
        </a>
      )}
    </div>
  );
}

export function BranchesTab({ projectSlug }: BranchesTabProps) {
  const [data, setData] = useState<GitBranchesResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    projectsApi
      .getGitBranches(projectSlug)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load branches');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectSlug]);

  if (loading) return <LoadingState label="Loading branches…" />;
  if (error) return <ErrorState message={error} />;
  if (data?.status === 'no_remote') {
    return <NoRemoteState feature="branches" />;
  }
  if (data?.status === 'error' || !data) {
    return <ErrorState message={data?.message ?? 'GitHub is not responding right now.'} />;
  }
  const branches = data.branches ?? [];
  if (branches.length === 0) {
    return (
      <InfoState title="No branches found." body="This repo only has its default branch for now." />
    );
  }

  return (
    <div className="flex flex-col gap-2 p-3">
      <p className="text-[11px] text-[var(--text-muted)] leading-snug">
        Each <Term term="branch" /> is a parallel copy of your project. The{' '}
        <Term term="aheadBehind">ahead/behind</Term> counts show how far each branch has drifted
        from the default.
      </p>
      <div className="bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius)] p-1">
        {branches.map((b) => (
          <BranchRow key={b.name} branch={b} />
        ))}
      </div>
    </div>
  );
}
