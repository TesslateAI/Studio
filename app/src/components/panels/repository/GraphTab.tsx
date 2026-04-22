import { useEffect, useMemo, useState } from 'react';
import { ArrowSquareOut, GitMerge } from '@phosphor-icons/react';
import {
  projectsApi,
  type GitCommit as GitCommitT,
  type GitCommitsResponse,
} from '../../../lib/api';
import { ErrorState, InfoState, LoadingState, NoRemoteState } from './EmptyStates';
import { classifyCommit, summarizeFileBuckets } from './commitClassification';
import { formatAbsoluteDate, formatRelativeTime } from './relativeTime';
import { laneColor, layoutCommitGraph, type GraphEdge } from './graphLayout';

interface GraphTabProps {
  projectSlug: string;
}

const ROW_HEIGHT = 36;
const LANE_WIDTH = 14;
const DOT_RADIUS = 4;
const LEFT_PADDING = 10;

function edgePath(edge: GraphEdge): string {
  const x1 = LEFT_PADDING + edge.fromLane * LANE_WIDTH;
  const y1 = ROW_HEIGHT / 2;
  const targetRow = edge.toIndex != null ? edge.toIndex - edge.fromIndex : 1; // straight down off-slice
  const x2 = LEFT_PADDING + edge.toLane * LANE_WIDTH;
  const y2 = y1 + targetRow * ROW_HEIGHT;

  if (x1 === x2) {
    return `M ${x1} ${y1} L ${x2} ${y2}`;
  }
  // Curved joiner for diagonal hops — a single cubic bezier that eases
  // between lanes. Looks smoother than a 90-degree elbow.
  const midY = (y1 + y2) / 2;
  return `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;
}

interface GraphRowProps {
  commit: GitCommitT;
  lane: number;
  isMerge: boolean;
  totalLanes: number;
  selected: boolean;
  onSelect: (sha: string) => void;
}

function GraphRow({ commit, lane, isMerge, totalLanes, selected, onSelect }: GraphRowProps) {
  const summary = classifyCommit(commit.title, commit.author.login);
  const when = commit.author.date ?? commit.committer.date;
  const graphWidth = LEFT_PADDING + totalLanes * LANE_WIDTH;
  const dotX = LEFT_PADDING + lane * LANE_WIDTH;
  return (
    <button
      type="button"
      onClick={() => onSelect(commit.sha)}
      className={`relative flex items-stretch w-full text-left transition-colors ${
        selected ? 'bg-[var(--surface-hover)]' : 'hover:bg-[var(--surface-hover)]'
      }`}
      style={{ minHeight: ROW_HEIGHT }}
    >
      {/* Graph column spacer */}
      <span
        aria-hidden="true"
        className="flex-shrink-0 relative"
        style={{ width: graphWidth + LEFT_PADDING }}
      >
        <span
          className="absolute rounded-full border-2"
          style={{
            top: ROW_HEIGHT / 2 - DOT_RADIUS,
            left: dotX - DOT_RADIUS,
            width: DOT_RADIUS * 2,
            height: DOT_RADIUS * 2,
            backgroundColor: isMerge ? 'var(--bg)' : laneColor(lane),
            borderColor: laneColor(lane),
          }}
        />
      </span>
      <span className="flex-1 min-w-0 py-1 pr-2 flex items-center gap-1.5">
        <span
          className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0`}
          style={{ backgroundColor: laneColor(lane) }}
          aria-hidden="true"
        />
        <span className="flex-1 min-w-0">
          <span className="flex items-center gap-1 min-w-0">
            {isMerge && (
              <GitMerge
                size={11}
                weight="bold"
                className="flex-shrink-0 text-[var(--text-subtle)]"
              />
            )}
            <span className="text-[11.5px] text-[var(--text)] truncate">
              {summary.emoji} {commit.title || '(no commit message)'}
            </span>
          </span>
          <span className="flex items-center gap-1.5 text-[10px] text-[var(--text-muted)] truncate">
            <span className="truncate">
              {commit.author.name || commit.author.login || 'Unknown'}
            </span>
            {when && (
              <>
                <span className="text-[var(--text-subtle)]">·</span>
                <span title={formatAbsoluteDate(when)}>{formatRelativeTime(when)}</span>
              </>
            )}
          </span>
        </span>
        {commit.author.avatar_url && (
          <img
            src={commit.author.avatar_url}
            alt=""
            className="w-4 h-4 rounded-full border border-[var(--border)] object-cover flex-shrink-0"
            loading="lazy"
          />
        )}
      </span>
    </button>
  );
}

function DetailsCard({
  commit,
  filesChangedFallback,
}: {
  commit: GitCommitT;
  filesChangedFallback?: number | null;
}) {
  const when = commit.author.date ?? commit.committer.date;
  return (
    <div className="mx-2 my-1 p-2.5 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius)] text-[11px]">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[10.5px] text-[var(--text-muted)]">{commit.short_sha}</span>
        {commit.html_url && (
          <a
            href={commit.html_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[10.5px] text-[var(--text-muted)] hover:text-[var(--text)]"
          >
            View on GitHub
            <ArrowSquareOut size={10} weight="bold" />
          </a>
        )}
      </div>
      {commit.message && commit.message !== commit.title && (
        <pre className="mt-2 whitespace-pre-wrap text-[11px] text-[var(--text)] font-sans leading-snug">
          {commit.message}
        </pre>
      )}
      <div className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[10.5px]">
        <span className="text-[var(--text-muted)]">Author</span>
        <span className="text-[var(--text)]">
          {commit.author.name || commit.author.login || 'Unknown'}
          {commit.author.login && commit.author.name && (
            <span className="text-[var(--text-muted)]"> (@{commit.author.login})</span>
          )}
        </span>
        {when && (
          <>
            <span className="text-[var(--text-muted)]">When</span>
            <span className="text-[var(--text)]">{formatAbsoluteDate(when)}</span>
          </>
        )}
        {commit.parents.length > 0 && (
          <>
            <span className="text-[var(--text-muted)]">Parents</span>
            <span className="font-mono text-[10px] text-[var(--text)]">
              {commit.parents.map((p) => p.slice(0, 7)).join(', ')}
            </span>
          </>
        )}
      </div>
      {(commit.files_changed != null || filesChangedFallback != null) && (
        <p className="mt-2 text-[10.5px] text-[var(--text-muted)]">
          {commit.files_changed ?? filesChangedFallback} file
          {(commit.files_changed ?? filesChangedFallback ?? 0) === 1 ? '' : 's'} changed
        </p>
      )}
    </div>
  );
}

export function GraphTab({ projectSlug }: GraphTabProps) {
  const [data, setData] = useState<GitCommitsResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    projectsApi
      .getGitCommits(projectSlug, { limit: 100, includeStats: false })
      .then((res) => {
        if (cancelled) return;
        setData(res);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Could not load commits');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectSlug]);

  const layout = useMemo(() => {
    if (!data?.commits) return null;
    return layoutCommitGraph(data.commits.map((c) => ({ sha: c.sha, parents: c.parents })));
  }, [data]);

  const fileBucketsBySha = useMemo(() => {
    const out = new Map<string, ReturnType<typeof summarizeFileBuckets>>();
    if (!data?.commits) return out;
    // We don't fetch per-commit files unless explicitly asked (would require
    // a follow-up request per commit). Left intentionally empty — the
    // DetailsCard will fall back to the commit's files_changed count.
    return out;
  }, [data]);

  if (loading) return <LoadingState label="Loading commit graph…" />;
  if (error) return <ErrorState message={error} />;
  if (data?.status === 'no_remote') {
    return <NoRemoteState feature="your commit history" />;
  }
  if (data?.status === 'error' || !data?.commits) {
    return <ErrorState message={data?.message ?? 'GitHub is not responding right now.'} />;
  }
  if (data.commits.length === 0 || !layout) {
    return (
      <InfoState
        title="No commits yet."
        body="Once your first change is saved, it'll appear here on the timeline."
      />
    );
  }

  const totalRows = data.commits.length;
  const svgHeight = totalRows * ROW_HEIGHT;
  const svgWidth = LEFT_PADDING * 2 + layout.laneCount * LANE_WIDTH;

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 text-[10.5px] text-[var(--text-muted)] border-b border-[var(--border)]">
        Showing the {totalRows} most recent commits. Click a row to see the full message.
      </div>
      <div className="flex-1 overflow-auto">
        <div className="relative">
          {/* Edges layer — positioned absolutely to overlay the rows. */}
          <svg
            aria-hidden="true"
            width={svgWidth}
            height={svgHeight}
            className="absolute top-0 left-0 pointer-events-none"
          >
            {layout.edges.map((edge, idx) => {
              const yOffset = edge.fromIndex * ROW_HEIGHT;
              return (
                <g key={idx} transform={`translate(0, ${yOffset})`}>
                  <path
                    d={edgePath(edge)}
                    stroke={laneColor(edge.isMergeIn ? edge.toLane : edge.fromLane)}
                    strokeWidth={1.5}
                    fill="none"
                    opacity={edge.isMergeIn ? 0.75 : 0.5}
                  />
                </g>
              );
            })}
          </svg>

          {/* Rows */}
          <div className="relative" style={{ paddingLeft: 0, minWidth: svgWidth }}>
            {data.commits.map((commit, idx) => {
              const node = layout.nodes[idx];
              const isSel = selected === commit.sha;
              return (
                <div key={commit.sha}>
                  <GraphRow
                    commit={commit}
                    lane={node.lane}
                    isMerge={node.isMergeCommit}
                    totalLanes={layout.laneCount}
                    selected={isSel}
                    onSelect={(sha) => setSelected((prev) => (prev === sha ? null : sha))}
                  />
                  {isSel && (
                    <DetailsCard
                      commit={commit}
                      filesChangedFallback={
                        fileBucketsBySha.get(commit.sha)?.reduce((a, b) => a + b.count, 0) ?? null
                      }
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
