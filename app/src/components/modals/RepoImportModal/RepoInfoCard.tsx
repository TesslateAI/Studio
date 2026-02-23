import { motion } from 'framer-motion';
import { Lock, Globe, Star, Clock } from '@phosphor-icons/react';
import type { GitProviderRepository } from '../../../types/git-providers';

interface RepoInfoCardProps {
  repo: GitProviderRepository;
}

export function RepoInfoCard({ repo }: RepoInfoCardProps) {
  const updatedAt = repo.updated_at
    ? new Date(repo.updated_at).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      })
    : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="bg-white/5 border border-white/10 rounded-xl p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h4 className="font-semibold text-[var(--text)] truncate">{repo.full_name}</h4>
            {repo.private ? (
              <span className="inline-flex items-center gap-1 text-xs bg-yellow-500/15 text-yellow-400 px-2 py-0.5 rounded-full flex-shrink-0">
                <Lock size={10} weight="fill" />
                Private
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-xs bg-green-500/15 text-green-400 px-2 py-0.5 rounded-full flex-shrink-0">
                <Globe size={10} weight="fill" />
                Public
              </span>
            )}
          </div>
          {repo.description && (
            <p className="text-sm text-gray-400 line-clamp-2 mb-2">{repo.description}</p>
          )}
          <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500">
            {repo.language && (
              <span className="inline-flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full bg-[var(--primary)]" />
                {repo.language}
              </span>
            )}
            {typeof repo.stars_count === 'number' && (
              <span className="inline-flex items-center gap-1">
                <Star size={12} weight="fill" className="text-yellow-500" />
                {repo.stars_count.toLocaleString()}
              </span>
            )}
            {updatedAt && (
              <span className="inline-flex items-center gap-1">
                <Clock size={12} />
                {updatedAt}
              </span>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
