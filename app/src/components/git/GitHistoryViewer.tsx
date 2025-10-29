import { useState, useEffect } from 'react';
import { Clock, GitCommit, User, Calendar } from '@phosphor-icons/react';
import { gitApi } from '../../lib/git-api';
import type { GitCommitInfo } from '../../types/git';
import { LoadingSpinner } from '../PulsingGridSpinner';
import toast from 'react-hot-toast';

interface GitHistoryViewerProps {
  projectId: number;
}

export function GitHistoryViewer({ projectId }: GitHistoryViewerProps) {
  const [commits, setCommits] = useState<GitCommitInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [limit, setLimit] = useState(20);

  useEffect(() => {
    loadCommitHistory();
  }, [projectId, limit]);

  const loadCommitHistory = async () => {
    setIsLoading(true);
    try {
      const history = await gitApi.getCommitHistory(projectId, limit);
      setCommits(history.commits);
    } catch (error: any) {
      console.error('Failed to load commit history:', error);
      toast.error('Failed to load commit history');
    } finally {
      setIsLoading(false);
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffInMinutes = (now.getTime() - date.getTime()) / (1000 * 60);

    if (diffInMinutes < 60) return `${Math.floor(diffInMinutes)}m ago`;
    if (diffInMinutes < 1440) return `${Math.floor(diffInMinutes / 60)}h ago`;
    if (diffInMinutes < 10080) return `${Math.floor(diffInMinutes / 1440)}d ago`;
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined
    });
  };

  const getCommitTypeFromMessage = (message: string) => {
    const match = message.match(/^(feat|fix|docs|style|refactor|test|chore):/);
    if (!match) return null;

    const types: Record<string, { color: string; bg: string }> = {
      feat: { color: 'text-green-400', bg: 'bg-green-500/20' },
      fix: { color: 'text-red-400', bg: 'bg-red-500/20' },
      docs: { color: 'text-blue-400', bg: 'bg-blue-500/20' },
      style: { color: 'text-purple-400', bg: 'bg-purple-500/20' },
      refactor: { color: 'text-yellow-400', bg: 'bg-yellow-500/20' },
      test: { color: 'text-cyan-400', bg: 'bg-cyan-500/20' },
      chore: { color: 'text-gray-400', bg: 'bg-gray-500/20' },
    };

    return { type: match[1], ...types[match[1]] };
  };

  const getCommitMessage = (message: string) => {
    // Remove prefix if present
    return message.replace(/^(feat|fix|docs|style|refactor|test|chore):\s*/, '');
  };

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <LoadingSpinner message="Loading commit history..." size={60} />
      </div>
    );
  }

  if (commits.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <GitCommit className="w-12 h-12 text-gray-500 mx-auto mb-3" />
          <p className="text-gray-400">No commits yet</p>
          <p className="text-sm text-gray-500 mt-1">Make your first commit to see history</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Clock className="w-5 h-5 text-gray-400" />
          <h3 className="font-semibold text-[var(--text)]">Commit History</h3>
          <span className="text-xs text-gray-500">({commits.length})</span>
        </div>
        <button
          onClick={() => setLimit(prev => prev + 20)}
          className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
        >
          Load More
        </button>
      </div>

      {/* Commit List */}
      <div className="flex-1 overflow-y-auto space-y-2 pr-2">
        {commits.map((commit, index) => {
          const typeInfo = getCommitTypeFromMessage(commit.message);
          const message = getCommitMessage(commit.message);

          return (
            <div
              key={commit.sha}
              className="relative bg-white/5 hover:bg-white/8 rounded-xl p-4 border border-white/10 transition-all group"
            >
              {/* Timeline Line */}
              {index < commits.length - 1 && (
                <div className="absolute left-9 top-12 bottom-0 w-px bg-white/10" />
              )}

              {/* Commit Dot */}
              <div className="absolute left-7 top-7 w-2 h-2 rounded-full bg-blue-400 ring-4 ring-[var(--surface)]" />

              {/* Content */}
              <div className="ml-8">
                {/* Header */}
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      {typeInfo && (
                        <span className={`text-xs font-semibold px-2 py-0.5 rounded ${typeInfo.bg} ${typeInfo.color}`}>
                          {typeInfo.type}
                        </span>
                      )}
                      <span className="text-sm text-[var(--text)] font-medium line-clamp-1">
                        {message}
                      </span>
                    </div>

                    {/* Meta Info */}
                    <div className="flex items-center gap-3 text-xs text-gray-500">
                      <div className="flex items-center gap-1">
                        <User className="w-3 h-3" />
                        <span>{commit.author}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <Calendar className="w-3 h-3" />
                        <span>{formatDate(commit.date)}</span>
                      </div>
                    </div>
                  </div>

                  {/* SHA */}
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-gray-400 bg-white/5 px-2 py-1 rounded">
                      {commit.sha.substring(0, 7)}
                    </span>
                  </div>
                </div>

                {/* Branch Badge */}
                {commit.branch && (
                  <div className="mt-2">
                    <span className="text-xs text-gray-400 flex items-center gap-1">
                      <GitCommit className="w-3 h-3" />
                      {commit.branch}
                    </span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
